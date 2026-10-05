#!/usr/bin/env bash
set -euo pipefail

# keycloak_migrate_roles.sh — migrate the LIVE realm to the four-role model
# (v0.3.0, docs/PLAN_ROLES_SETTINGS_STAGED.md §2/§3 Step 1 + §6 flags).
#
# What it does (idempotent — safe to re-run; additive only — NEVER deletes a
# realm role or group):
#   1. creates the realm roles PLATFORM_ADMIN / ORG_ADMIN / REVIEWER if missing
#      (legacy SUPER_ADMIN / DEVELOPER / GUEST are left alone);
#   2. creates the groups /platform-admins, /org-admins, /reviewers (and
#      /developers when absent) and binds each to its realm role;
#   3. MOVES members: SUPER_ADMIN holders -> /platform-admins (adding the new
#      group first, then leaving /super-admins — the user is never left
#      without an admin claim); DEVELOPER holders -> /developers when they are
#      in no group yet. Legacy role assignments that do not come from
#      /super-admins are kept — the one-release compat map treats them
#      identically;
#   4. does NOT touch GUEST members (F4/N5): they are LISTED for manual
#      assignment, as are users with no recognized realm role at all (they
#      derive NONE, or hit the temporary broker fallback — F1);
#   5. prints both lists in --dry-run AND in the real run.
#
# Runs kcadm.sh inside the keycloak pod (master-realm admin credentials come
# from secret/keycloak-secret); JSON is parsed on this host with python3
# (no jq on this host).
#
# Usage:
#   scripts/keycloak_migrate_roles.sh --dry-run   # print the plan, change nothing
#   scripts/keycloak_migrate_roles.sh [--yes]     # apply (asks for confirmation)
#
# Env overrides: K8S_NAMESPACE (codesage), KEYCLOAK_REALM (codesage-realm),
# KEYCLOAK_POD (auto-detected), KEYCLOAK_ADMIN_USER (from the secret).

NS="${K8S_NAMESPACE:-codesage}"
REALM="${KEYCLOAK_REALM:-codesage-realm}"
SECRET_NAME="keycloak-secret"
KC_SERVER="http://localhost:8080/auth"
KCADM="/opt/keycloak/bin/kcadm.sh"

DRY_RUN=0
YES=0
usage() {
  sed -n '4,36p' "$0" | sed 's/^# \{0,1\}//'
}
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes | -y) YES=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

command -v kubectl >/dev/null || die "kubectl not found"
command -v python3 >/dev/null || die "python3 not found (JSON parsing)"

if [[ -z "${KEYCLOAK_POD:-}" ]]; then
  KEYCLOAK_POD="$(
    kubectl -n "$NS" get pod -l app=keycloak \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
  )"
fi
[[ -n "$KEYCLOAK_POD" ]] || die "no keycloak pod found in namespace $NS"
[[ "$(kubectl -n "$NS" get pod "$KEYCLOAK_POD" -o jsonpath='{.status.phase}')" == "Running" ]] \
  || die "keycloak pod $KEYCLOAK_POD is not Running"

secret_value() {
  kubectl -n "$NS" get secret "$SECRET_NAME" \
    -o jsonpath="{.data.$1}" | base64 -d
}
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-$(secret_value KEYCLOAK_ADMIN)}"
ADMIN_PASS="$(secret_value KEYCLOAK_ADMIN_PASSWORD)"
[[ -n "$ADMIN_USER" && -n "$ADMIN_PASS" ]] \
  || die "cannot read admin credentials from secret $SECRET_NAME"
# NOTE: ADMIN_PASS is never echoed (no set -x anywhere in this script).

# --- kcadm.sh inside the pod --------------------------------------------------
# NOTE: -i (stdin passthrough) is used ONLY where a JSON body is piped in
# (kc_body, -f -). Plain kubectl exec -i inside a `while read` loop would
# drain the loop's here-string stdin — it silently truncated the group/user
# scans on the live realm during dry-run testing.
kc() {
  kubectl exec -n "$NS" "$KEYCLOAK_POD" -- "$KCADM" "$@" -r "$REALM"
}
kc_body() { # for calls that pipe a body on stdin (-f -)
  kubectl exec -i -n "$NS" "$KEYCLOAK_POD" -- "$KCADM" "$@" -r "$REALM"
}
kc_try() { kc "$@" 2>/dev/null || true; }

echo "Configuring kcadm against $KC_SERVER (master admin: $ADMIN_USER)..." >&2
kubectl exec -n "$NS" "$KEYCLOAK_POD" -- "$KCADM" config credentials \
  --server "$KC_SERVER" --realm master --user "$ADMIN_USER" \
  --password "$ADMIN_PASS" >/dev/null \
  || die "kcadm.sh config credentials failed"

# --- host-side JSON helpers (python3 — no jq on this host) --------------------
# json_lines <keys,csv> — stdin: JSON object or array → one TSV line per object.
json_lines() {
  python3 -c '
import json, sys
keys = sys.argv[1].split(",")
raw = sys.stdin.read().strip()
data = json.loads(raw) if raw else []
if isinstance(data, dict):
    data = [data]
for obj in data:
    print("\t".join(str(obj.get(k, "")) for k in keys))
' "$1"
}

# group_info — stdin: one group's full repr → "path<TAB>role1 role2 ...".
# realmRoles is a list of role-name strings (GroupRepresentation).
group_info() {
  python3 -c '
import json, sys
raw = sys.stdin.read().strip()
group = json.loads(raw) if raw else {}
names = []
for r in (group.get("realmRoles") or []):
    names.append(r if isinstance(r, str) else r.get("name", ""))
print(group.get("path", "") + "\t" + " ".join(names))
'
}

# --- gather: realm groups (full repr: path + bound realm roles) ---------------
declare -A GROUP_ID GROUP_PATH GROUP_ROLE
declare -A CREATED_GROUP_ID # refreshed during apply (arrays are point-in-time)
while IFS=$'\t' read -r gid; do
  [[ -n "$gid" ]] || continue
  info="$(kc get "groups/$gid" | group_info)"
  GROUP_ID[$gid]="$gid"
  GROUP_PATH[$gid]="${info%%$'\t'*}"
  GROUP_ROLE[$gid]="${info#*$'\t'}"
done <<<"$(kc_try get groups | json_lines id)"

path_to_id() { # /developers → group id (empty when missing)
  local want="$1" g
  [[ -n "${CREATED_GROUP_ID[$want]:-}" ]] && { echo "${CREATED_GROUP_ID[$want]}"; return 0; }
  for g in "${!GROUP_PATH[@]}"; do
    [[ "${GROUP_PATH[$g]}" == "$want" ]] && { echo "$g"; return 0; }
  done
  return 0
}

role_id() { kc_try get "roles/$1" | json_lines id | head -n1; }

NEW_ROLES=("PLATFORM_ADMIN" "ORG_ADMIN" "REVIEWER")
NEW_ROLE_DESCS=(
  "Full platform access: platform settings, user administration, reads across all orgs (v0.3.0)"
  "Administers one organization: org settings, invitations, member roles"
  "Validates review findings (confirm / false positive / severity override) in their orgs"
)
NEW_GROUPS=("platform-admins" "org-admins" "reviewers")
NEW_GROUP_ROLES=("PLATFORM_ADMIN" "ORG_ADMIN" "REVIEWER")

MISSING_ROLES=()
for r in "${NEW_ROLES[@]}"; do
  [[ -n "$(role_id "$r")" ]] || MISSING_ROLES+=("$r")
done
MISSING_GROUPS=()
for g in "${NEW_GROUPS[@]}" "developers"; do
  [[ -n "$(path_to_id "/$g")" ]] || MISSING_GROUPS+=("/$g")
done

# --- users: classify (F4 lists are always printed) ----------------------------
USERS="$(kc get users | json_lines id,username)"
declare -A PLAN_ADD_GROUP PLAN_LEAVE_GROUP
GUESTS=() NOROLE=() MOVES=() NOTES=()

while IFS=$'\t' read -r uid uname; do
  [[ -n "$uid" ]] || continue

  member_paths=" $(kc_try get "users/$uid/groups" | json_lines path | tr '\n' ' ') "
  direct_roles=" $(kc_try get "users/$uid/role-mappings/realm" | json_lines name | tr '\n' ' ') "

  # Effective realm roles = direct mappings ∪ roles of member groups.
  effective="$direct_roles"
  for g in "${!GROUP_ID[@]}"; do
    case "$member_paths" in
      *" ${GROUP_PATH[$g]} "*) effective+=" ${GROUP_ROLE[$g]:-} " ;;
    esac
  done
  effective=" $(echo "$effective" | tr ' ' '\n' | sort -u | tr '\n' ' ') "

  has() { case "$effective" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

  if has SUPER_ADMIN; then
    if [[ "$member_paths" != *" /platform-admins "* ]]; then
      PLAN_ADD_GROUP["$uid"]="/platform-admins"
      MOVES+=("$uname: joins /platform-admins")
    fi
    if [[ "$member_paths" == *" /super-admins "* ]]; then
      PLAN_LEAVE_GROUP["$uid"]="/super-admins"
      MOVES+=("$uname: leaves /super-admins (after joining /platform-admins)")
    else
      NOTES+=("$uname: SUPER_ADMIN not granted via /super-admins — kept (compat maps it to PLATFORM_ADMIN)")
    fi
    if has GUEST; then
      NOTES+=("$uname: also has the GUEST claim — untouched (PLATFORM_ADMIN outranks NONE)")
    fi
  elif has GUEST; then
    # F4/N5: never moved automatically — listed for manual assignment.
    # (Checked before DEVELOPER: GUEST outranks DEVELOPER — see derive_role.)
    GUESTS+=("$uname")
  elif has DEVELOPER; then
    if [[ "$member_paths" != *" /developers "* ]]; then
      PLAN_ADD_GROUP["$uid"]="/developers"
      MOVES+=("$uname: joins /developers")
    fi
  elif ! has PLATFORM_ADMIN && ! has ORG_ADMIN && ! has REVIEWER; then
    # No recognized or legacy realm role at all (F4): derives NONE, or hits
    # the temporary broker fallback (F1) when the session is GitHub-brokered.
    NOROLE+=("$uname")
  fi
done <<<"$USERS"

# --- print the plan ------------------------------------------------------------
echo
echo "Keycloak role migration plan — realm: $REALM, pod: $KEYCLOAK_POD"
echo "-------------------------------------------------------------------"
if ((${#MISSING_ROLES[@]})); then
  echo "Roles to create:    ${MISSING_ROLES[*]}"
else
  echo "Roles to create:    (none — already present)"
fi
if ((${#MISSING_GROUPS[@]})); then
  echo "Groups to create:   ${MISSING_GROUPS[*]} (each bound to its realm role)"
else
  echo "Groups to create:   (none — already present)"
fi
if ((${#MOVES[@]})); then
  echo "Members to move:"
  printf '  - %s\n' "${MOVES[@]}"
else
  echo "Members to move:    (none)"
fi
if ((${#NOTES[@]})); then
  echo "Notes:"
  printf '  - %s\n' "${NOTES[@]}"
fi
echo "GUEST users (NOT moved — manual assignment; legacy /guests kept):"
if ((${#GUESTS[@]})); then printf '  - %s\n' "${GUESTS[@]}"; else echo "  (none)"; fi
echo "Users with NO recognized realm role (derive NONE / broker fallback — manual):"
if ((${#NOROLE[@]})); then printf '  - %s\n' "${NOROLE[@]}"; else echo "  (none)"; fi
echo "Never deleted: legacy roles (SUPER_ADMIN, GUEST) and groups"
echo "               (/super-admins, /guests) — removal is a manual v0.4.0 follow-up."
echo "-------------------------------------------------------------------"

if ((DRY_RUN)); then
  echo "Dry run — nothing was changed."
  exit 0
fi

if ((!YES)); then
  if [[ -t 0 ]]; then
    read -r -p "Apply these changes? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted — nothing was changed."; exit 1; }
  else
    die "stdin is not a terminal — re-run with --yes to apply"
  fi
fi

# --- apply (idempotent; add-first so nobody loses their claim) -----------------
apply_role() {
  local name="$1" desc="$2"
  [[ -n "$(role_id "$name")" ]] && return 0
  kc create roles -s "name=$name" -s "description=$desc" >/dev/null
  echo "created role $name"
}

apply_group() { # <group-name-without-slash> <realm-role>
  local g="$1" role="$2" gid rid probe
  gid="$(path_to_id "/$g")"
  if [[ -z "$gid" ]]; then
    kc create groups -s "name=$g" >/dev/null 2>&1
    # kcadm logs "Created new group with id '...'" through its logger
    # (stderr) — resolve the id from a fresh GET instead of parsing the
    # create output, which never reaches stdout.
    while IFS= read -r probe; do
      [[ -n "$probe" ]] || continue
      if [[ "$(kc get "groups/$probe" | group_info | cut -f1)" == "/$g" ]]; then
        gid="$probe"
        break
      fi
    done <<<"$(kc_try get groups | json_lines id)"
    [[ -n "$gid" ]] || die "group /$g was created but its id could not be resolved"
    CREATED_GROUP_ID["/$g"]="$gid"
    GROUP_PATH[$gid]="/$g"
    GROUP_ROLE[$gid]=""
    echo "created group /$g"
  fi
  rid="$(role_id "$role")"
  [[ -n "$rid" ]] || die "role $role missing before binding /$g"
  if ! [[ " ${GROUP_ROLE[$gid]:-} " == *" $role "* ]]; then
    kc_body create "groups/$gid/role-mappings/realm" -f - >/dev/null <<JSON
[{"id": "$rid", "name": "$role"}]
JSON
    GROUP_ROLE[$gid]="${GROUP_ROLE[$gid]:-} $role"
    echo "bound /$g -> $role"
  fi
}

for i in "${!NEW_ROLES[@]}"; do
  apply_role "${NEW_ROLES[$i]}" "${NEW_ROLE_DESCS[$i]}"
done
for i in "${!NEW_GROUPS[@]}"; do
  apply_group "${NEW_GROUPS[$i]}" "${NEW_GROUP_ROLES[$i]}"
done
apply_group "developers" "DEVELOPER"

for uid in "${!PLAN_ADD_GROUP[@]}"; do
  gid="$(path_to_id "${PLAN_ADD_GROUP[$uid]}")"
  [[ -n "$gid" ]] || die "group ${PLAN_ADD_GROUP[$uid]} missing during apply"
  kc update "users/$uid/groups/$gid" >/dev/null   # KC24: PUT adds (POST 404s), idempotent
  echo "user $uid added to ${PLAN_ADD_GROUP[$uid]}"
done
for uid in "${!PLAN_LEAVE_GROUP[@]}"; do
  gid="$(path_to_id "${PLAN_LEAVE_GROUP[$uid]}")"
  if [[ -n "$gid" ]]; then
    kc delete "users/$uid/groups/$gid" >/dev/null
    echo "user $uid left ${PLAN_LEAVE_GROUP[$uid]}"
  fi
done

echo "Done. GUEST and no-realm-role users above still need manual assignment."

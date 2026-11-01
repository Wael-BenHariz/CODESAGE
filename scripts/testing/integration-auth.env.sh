# Source this helper to pass the dedicated local Keycloak test accounts to
# integration pytest without printing passwords or tokens.
if [[ -z "${E2E_USERS_JSON:-}" && -f "$ROOT/frontend/e2e/.auth/users.json" && -f "$ROOT/backend/.env.e2e" ]]; then
  export E2E_USERS_JSON="$(CODESAGE_ROOT="$ROOT" "$ROOT/scripts/testing/python.sh" -c '
import json, os
from pathlib import Path
from dotenv import dotenv_values

root = Path(os.environ["CODESAGE_ROOT"])
users = json.loads((root / "frontend/e2e/.auth/users.json").read_text())
settings = dotenv_values(root / "backend/.env.e2e")
password = settings.get("E2E_USER_PASSWORD", "")
mapped = {}
keys = {"PLATFORM_ADMIN": "platform", "ORG_ADMIN": "org_admin", "REVIEWER": "reviewer", "DEVELOPER": "developer"}
for user in users:
    role = user["role"]
    username = user["username"]
    if role == "NONE":
        key = "invitee" if "invitee" in username.lower() else "none"
    else:
        key = keys[role]
    mapped[key] = {"username": username, "password": password}
if password and all(key in mapped for key in ("platform", "org_admin", "reviewer", "developer", "none", "invitee")):
    print(json.dumps(mapped))
')"
  if [[ -n "$E2E_USERS_JSON" ]]; then
    export E2E_API_URL="${E2E_API_URL:-http://127.0.0.1:${E2E_API_PORT:-8002}}"
    export KEYCLOAK_PUBLIC_URL="${KEYCLOAK_PUBLIC_URL:-$(CODESAGE_ROOT="$ROOT" "$ROOT/scripts/testing/python.sh" -c 'import os; from pathlib import Path; from dotenv import dotenv_values; print(dotenv_values(Path(os.environ["CODESAGE_ROOT"]).joinpath("backend/.env.e2e")).get("KEYCLOAK_PUBLIC_URL", ""))')}"
    export KEYCLOAK_REALM="${KEYCLOAK_REALM:-codesage-realm}"
  fi
fi

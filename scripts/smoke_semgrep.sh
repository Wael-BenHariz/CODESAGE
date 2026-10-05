#!/usr/bin/env bash
#
# Smoke-test the k8s semgrep-service end to end from this machine.
#
#   [1/5] in-cluster connectivity : worker pod  -> http://semgrep-service:8080
#   [2/5] port-forward            : kubectl port-forward svc/semgrep-service
#   [3/5] raw scan                : tar.gz upload -> POST /scan -> findings
#   [4/5] pytest e2e              : backend/tests/e2e (connectivity, scan,
#                                   parallel pipeline evidence, failure modes)
#   [5/5] pass
#
# Usage:
#   scripts/smoke_semgrep.sh
#
# Env:
#   SMOKE_NAMESPACE   k8s namespace          (default: codesage)
#   SMOKE_PORT        local forward port     (default: 18080)
#   SMOKE_SKIP_PYTEST=1   run only phases 1-3 (no backend venv needed)
#
# Needs: kubectl with cluster access, curl, backend venv (phase 4).
# No sudo, no writes outside a private mktemp dir (and /tmp for logs).
# Postgres/Redis are NOT required — the e2e tests are DB-free.

set -euo pipefail

NS="${SMOKE_NAMESPACE:-codesage}"
WORKER="${SMOKE_WORKER_DEPLOY:-codesage-worker}"
SVC="semgrep-service"
PORT="${SMOKE_PORT:-18080}"
URL="http://127.0.0.1:${PORT}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO_ROOT/backend/venv/bin/python"

PF_PID=""
WORK_DIR=""

cleanup() {
    if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
        kill "$PF_PID" 2>/dev/null || true
        wait "$PF_PID" 2>/dev/null || true
    fi
    if [[ -n "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

die() {
    echo "SMOKE FAIL: $*" >&2
    exit 1
}

echo "== semgrep-service smoke (namespace=$NS, local $URL) =="

# --- preflight ---------------------------------------------------------------
command -v kubectl >/dev/null 2>&1 || die "kubectl not on PATH"
command -v curl >/dev/null 2>&1 || die "curl not on PATH"
[[ -x "$VENV_PY" ]] || die "backend venv missing: cd backend && python -m venv venv && pip install -r requirements.txt"
kubectl -n "$NS" get "svc/$SVC" >/dev/null || die "svc/$SVC not found in namespace $NS"
kubectl -n "$NS" get "deploy/$WORKER" >/dev/null || die "deploy/$WORKER not found in namespace $NS"

# --- [1/5] in-cluster connectivity (the real consumer: worker -> service) ----
echo "[1/5] in-cluster connectivity: deploy/$WORKER -> http://$SVC:8080/readyz"
INCLUSTER="$(kubectl -n "$NS" exec "deploy/$WORKER" -- \
    wget -q -T 5 -O - "http://$SVC:8080/readyz" 2>/dev/null)" \
    || die "worker pod cannot reach $SVC (in-cluster DNS/network broken)"
echo "      ok: $INCLUSTER"

# --- [2/5] port-forward (reuse an existing healthy listener if present) ------
if curl -sf --max-time 2 "$URL/readyz" >/dev/null 2>&1; then
    echo "[2/5] reusing existing listener on $URL"
else
    echo "[2/5] kubectl -n $NS port-forward svc/$SVC $PORT:8080"
    WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/smoke-semgrep.XXXXXX")"
    kubectl -n "$NS" port-forward "svc/$SVC" "$PORT:8080" \
        >"$WORK_DIR/port-forward.log" 2>&1 &
    PF_PID=$!
    for _ in $(seq 1 40); do
        curl -sf --max-time 2 "$URL/readyz" >/dev/null 2>&1 && break
        if ! kill -0 "$PF_PID" 2>/dev/null; then
            cat "$WORK_DIR/port-forward.log" >&2 || true
            die "port-forward died (port $PORT already taken?)"
        fi
        sleep 0.5
    done
fi
HEALTH="$(curl -s --max-time 5 "$URL/healthz")" || die "healthz unreachable on $URL"
READY="$(curl -s --max-time 5 "$URL/readyz")" || die "readyz unreachable on $URL"
echo "      ok: healthz=$HEALTH readyz=$READY"

# --- [3/5] raw scan over the port-forward ------------------------------------
echo "[3/5] raw scan: tar.gz fixture -> POST /scan?timeout=60&languages=python"
WORK_DIR="${WORK_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/smoke-semgrep.XXXXXX")}"
"$VENV_PY" - "$WORK_DIR/scan.tar.gz" <<'PYEOF'
import io
import sys
import tarfile

files = {
    "src/app.py": (
        "import pickle\n"
        "\n"
        "def run(user_input, blob):\n"
        "    eval(user_input)\n"
        "    pickle.loads(blob)\n"
    ),
    "src/util.py": "x = 1\n",
}
with tarfile.open(sys.argv[1], "w:gz") as tar:
    for name, content in files.items():
        data = content.encode()
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
PYEOF
SCAN_JSON="$(curl -sf --max-time 150 \
    -F "file=@$WORK_DIR/scan.tar.gz" \
    "$URL/scan?timeout=60&languages=python")" || die "POST /scan failed"
COUNT="$(printf '%s' "$SCAN_JSON" | "$VENV_PY" -c \
    'import json, sys; print(len(json.load(sys.stdin).get("results", [])))')" \
    || die "response was not a semgrep report"
[[ "$COUNT" -gt 0 ]] || die "zero findings for the eval/pickle fixture"
echo "      ok: $COUNT finding(s)"

# --- [4/5] pytest e2e (scan normalization, parallel pipeline, failures) ------
if [[ "${SMOKE_SKIP_PYTEST:-0}" == "1" ]]; then
    echo "[4/5] skipped (SMOKE_SKIP_PYTEST=1)"
else
    echo "[4/5] pytest tests/e2e (SEMGREP_E2E_URL=$URL)"
    (cd "$REPO_ROOT/backend" && SEMGREP_E2E_URL="$URL" \
        "$VENV_PY" -m pytest tests/e2e -v) || die "e2e pytest suite failed"
fi

echo "[5/5] all phases passed"
echo "SMOKE PASS"

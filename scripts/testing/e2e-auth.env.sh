# Source this helper; it exports local test credentials without printing them.
if [[ -z "${E2E_USERNAME:-}" && -f "$ROOT/frontend/e2e/.auth/users.json" && -f "$ROOT/backend/.env.e2e" ]]; then
  E2E_ROLE="${E2E_ROLE:-ORG_ADMIN}"
  export E2E_ROLE
  export E2E_USERNAME="$(CODESAGE_ROOT="$ROOT" "$ROOT/scripts/testing/python.sh" -c 'import json, os; from pathlib import Path; users=json.loads(Path(os.environ["CODESAGE_ROOT"]).joinpath("frontend/e2e/.auth/users.json").read_text()); match=next((u for u in users if u["role"]==os.environ["E2E_ROLE"]), None); print(match["username"] if match else "")')"
  export E2E_USER_PASSWORD="$(CODESAGE_ROOT="$ROOT" "$ROOT/scripts/testing/python.sh" -c 'import os; from dotenv import dotenv_values; from pathlib import Path; print(dotenv_values(Path(os.environ["CODESAGE_ROOT"]).joinpath("backend/.env.e2e")).get("E2E_USER_PASSWORD", ""))')"
fi

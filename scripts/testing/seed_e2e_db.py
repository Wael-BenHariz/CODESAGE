#!/usr/bin/env python3
"""Apply migrations to the disposable codesage_e2e database."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def main() -> None:
    envfile = BACKEND / ".env.e2e"
    if not envfile.is_file():
        raise SystemExit("Run scripts/testing/bootstrap_env.py first")
    sys.path.insert(0, str(BACKEND))

    load_dotenv(envfile, override=True)
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "codesage_e2e":
        raise SystemExit("Refusing to migrate a database outside loopback codesage_e2e")
    subprocess.run(
        [
            "docker",
            "exec",
            "codesage-test-db",
            "psql",
            "-U",
            "codesage",
            "-d",
            "postgres",
            "-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='codesage_e2e'",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "codesage-test-db",
            "dropdb",
            "-U",
            "codesage",
            "--if-exists",
            "codesage_e2e",
        ],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "codesage-test-db",
            "createdb",
            "-U",
            "codesage",
            "codesage_e2e",
        ],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True
    )
    seed_sql = """
        INSERT INTO users (id, role, login, email, name)
        VALUES ('00000000-0000-4000-8000-000000000001', 'ORG_ADMIN', 'e2e-seed-admin',
                'e2e-seed-admin@example.test', 'E2E Seed Admin')
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO orgs (id, name, account_type, installation_id)
        VALUES ('00000000-0000-4000-8000-000000000002', 'e2e-seed-org', 'Organization', NULL)
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO org_members (id, org_id, user_id, role)
        VALUES ('00000000-0000-4000-8000-000000000003',
                '00000000-0000-4000-8000-000000000002',
                '00000000-0000-4000-8000-000000000001', 'ORG_ADMIN')
        ON CONFLICT (id) DO NOTHING;
    """
    subprocess.run(
        [
            "docker",
            "exec",
            "codesage-test-db",
            "psql",
            "-U",
            "codesage",
            "-d",
            "codesage_e2e",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            seed_sql,
        ],
        check=True,
    )
    print("E2E database reset, migrated, and loaded with deterministic seed UUIDs.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Org seed report — dry-run summary (default) or heal (--apply).

Shows what org provisioning would create before/after migration 013 runs
(plan Q1 / Step 13 gate):

- planned orgs from ``github_installations`` + linked users, with the
  least-privilege member role per org,
- current state of ``orgs``/``org_members`` (works BEFORE migration 013:
  the table is simply reported as absent),
- orgs without an ORG_ADMIN (the "two or more linked users → all
  DEVELOPER" case — flagged so an ORG_ADMIN can be assigned manually).

``--apply`` provisions every missing org/member through the shared helper
``app.services.org_provisioning`` — the exact code the webhook/link hooks
run (idempotent, never downgrades an existing member row).

Run with the backend venv (repo root or backend/ both work):

    ./venv/bin/python ../scripts/org_seed_report.py            # dry-run
    ./venv/bin/python ../scripts/org_seed_report.py --apply    # heal
    ./venv/bin/python ../scripts/org_seed_report.py --database-url postgresql+asyncpg://...

Connection: ``--database-url`` > ``DATABASE_URL`` env > backend config
(``.env``). Missing required config values are stubbed with throwaway
test values so the script can run standalone (it never touches GitHub,
Redis or the LLMs).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# --- environment bootstrap (before any app import) ---------------------------

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _bootstrap_env() -> None:
    """Stub the config's required-but-irrelevant secrets when missing.

    Only affects this process; values are never used (no GitHub/LLM
    calls). DATABASE_URL is honored from the real environment.
    """
    from cryptography.fernet import Fernet

    # Deliberate process-local throwaway placeholders — the report performs
    # no GitHub/Redis/LLM work, and only DATABASE_URL is trusted for real:
    defaults = {
        "SECRET_KEY": "org-seed-report-standalone-0123456789abcdef",  # nosec B105
        "GITHUB_CLIENT_ID": "standalone",
        "GITHUB_CLIENT_SECRET": "standalone",  # nosec B105
        "GITHUB_APP_ID": "0",
        "GITHUB_APP_PRIVATE_KEY": (
            "-----BEGIN PRIVATE KEY-----\nstandalone\n-----END PRIVATE KEY-----"
        ),
        "GITHUB_WEBHOOK_SECRET": "standalone",  # nosec B105
        "STATE_TOKEN_SECRET": "standalone",  # nosec B105
        "GEMINI_API_KEY": "standalone",
        "GROQ_API_KEY": "standalone",
        "LLM_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_bootstrap_env()

# --- application imports (after the env block, mirroring tests/conftest) -----

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import GitHubInstallation
from app.services.org_provisioning import (
    provision_installation_org,
    seed_report,
)


def _resolve_database_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    return os.environ.get("DATABASE_URL") or settings.DATABASE_URL


def _print_dry_run(report, *, dry_run: bool = True) -> None:
    mode = "DRY RUN (no changes)" if dry_run else "after apply"
    print(f"CodeSage org seed report — {mode}\n")
    print("=" * 72)
    print("Planned state (from github_installations + linked users):")
    if not report.planned:
        print("  (no GitHub App installations found)")
    for entry in report.planned:
        members = ", ".join(f"{m['login']}:{m['role']}" for m in entry.members)
        exists = "yes" if entry.org_exists else "NO (would be created)"
        missing = ", ".join(entry.missing_members) or "none"
        print(
            f"  - {entry.name} ({entry.account_type}, "
            f"installation {entry.installation_id})"
        )
        print(
            f"      members: [{members or 'none'}]  org exists: {exists}  "
            f"missing member rows: {missing}"
        )

    state = (
        "orgs table present"
        if report.orgs_table_exists
        else "orgs table ABSENT — migration 013 not applied yet"
    )
    print(f"\nCurrent state ({state}):")
    if report.orgs_table_exists:
        if not report.current:
            print("  (no orgs yet)")
        for org in report.current:
            print(
                f"  - {org['name']} (installation {org['installation_id']}): "
                f"{len(org['members'])} member(s) "
                f"[{', '.join(org['members']) or 'none'}]"
            )

    # Actionable: members exist (planned or current) but nobody administers
    # the org — the ">=2 linked users → all DEVELOPER" branch.
    no_admin = sorted(
        {
            entry.name
            for entry in report.planned
            if entry.members and not entry.has_org_admin
        }
        | {
            org["name"]
            for org in report.current
            if org["members"] and not org["has_org_admin"]
        }
    )
    print(f"\nWarnings: {len(no_admin)} org(s) without an ORG_ADMIN")
    for name in no_admin:
        print(f"  ! {name} — assign an ORG_ADMIN manually")


async def _apply(db) -> None:
    result = await db.execute(
        select(GitHubInstallation).order_by(GitHubInstallation.account_login.asc())
    )
    installations = result.scalars().all()
    for installation in installations:
        org = await provision_installation_org(db, installation)
        print(
            f"  provisioned: {org.name} (installation {org.installation_id}, "
            f"org_id={org.id})"
        )
    await db.commit()
    print(f"\n--apply finished: {len(installations)} installation(s) provisioned.")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Async SQLAlchemy URL (default: DATABASE_URL env / config)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Provision missing orgs/members (default: dry-run report)",
    )
    args = parser.parse_args()

    url = _resolve_database_url(args.database_url)
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            if args.apply:
                print(
                    "CodeSage org seed report — APPLY " "(provisioning missing rows)\n"
                )
                await _apply(db)
                report = await seed_report(db)
                print()
                _print_dry_run(report, dry_run=False)
            else:
                report = await seed_report(db)
                _print_dry_run(report, dry_run=True)
    except Exception as exc:  # noqa: BLE001 — CLI surface: message + failure code
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

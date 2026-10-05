#!/usr/bin/env python3
"""Review-access pre-check — F3 gate before the Step 7 org retrofit.

Flag F3 retrofits org-membership 404s onto every existing review and
pull-request route. Before applying that retrofit (and again before a
cluster release), this report answers: *who would lose access?*

Section A — users that triggered reviews but hold no ``org_members``
row anywhere: after the retrofit these users (unless PLATFORM_ADMIN)
get 404 on every review they used to read.

Section B — reviews whose repository chains into no org row, or into an
org with zero members: invisible to everybody except PLATFORM_ADMIN.

Read-only: it never writes. Exit code 1 when either section has
findings (so it can gate a release script), 0 when clean.

Run with the backend venv (repo root or backend/ both work):

    ./venv/bin/python ../scripts/review_access_precheck.py
    ./venv/bin/python ../scripts/review_access_precheck.py \\
        --database-url postgresql+asyncpg://...

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

    defaults = {
        "SECRET_KEY": "precheck-standalone-secret-key-0123456789abcdef",  # nosec B105
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

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgMember,
    PullRequest,
    Repository,
    Review,
    User,
)


def _resolve_database_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    return os.environ.get("DATABASE_URL") or settings.DATABASE_URL


async def _section_a(db) -> list:
    """Users with >=1 triggered review and zero org_members rows."""
    stmt = (
        select(
            User.id,
            User.login,
            User.role,
            func.count(Review.id).label("review_count"),
        )
        .join(Review, Review.user_id == User.id)
        .outerjoin(OrgMember, OrgMember.user_id == User.id)
        .where(OrgMember.user_id.is_(None))
        .group_by(User.id, User.login, User.role)
        .order_by(func.count(Review.id).desc())
    )
    return (await db.execute(stmt)).all()


async def _section_b(db) -> list:
    """Reviews whose chain org is missing or has zero members.

    Returns one row per installation/org with distinct review and member
    counts (distinct counts: the outer joins multiply rows).
    """
    stmt = (
        select(
            GitHubInstallation.installation_id,
            GitHubInstallation.account_login,
            Org.id.label("org_id"),
            func.count(func.distinct(Review.id)).label("review_count"),
            func.count(func.distinct(OrgMember.user_id)).label("member_count"),
        )
        .join(PullRequest, PullRequest.id == Review.pull_request_id)
        .join(Repository, Repository.id == PullRequest.repository_id)
        .join(GitHubInstallation, GitHubInstallation.id == Repository.installation_id)
        .outerjoin(Org, Org.installation_id == GitHubInstallation.installation_id)
        .outerjoin(OrgMember, OrgMember.org_id == Org.id)
        .group_by(
            GitHubInstallation.installation_id,
            GitHubInstallation.account_login,
            Org.id,
        )
        .order_by(GitHubInstallation.installation_id)
    )
    rows = (await db.execute(stmt)).all()
    return [r for r in rows if r.org_id is None or r.member_count == 0]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="F3 review-access pre-check (read-only report)"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Async SQLAlchemy URL (default: DATABASE_URL env / config)",
    )
    args = parser.parse_args()

    url = _resolve_database_url(args.database_url)
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    findings = 0
    try:
        async with session_factory() as db:
            # org_members/orgs missing = migration 013 not applied yet.
            try:
                tables = await db.run_sync(
                    lambda sync_session: inspect(
                        sync_session.connection()
                    ).get_table_names()
                )
            except ProgrammingError:
                tables = []
            if "org_members" not in tables:
                print(
                    "org_members table ABSENT (migration 013 not applied) — "
                    "after the retrofit EVERY review route 404s for "
                    "non-platform users. Run the org seed first."
                )
                return 1

            print("CodeSage review-access pre-check (F3, Step 7)\n")
            print("=" * 72)

            section_a = await _section_a(db)
            findings += len(section_a)
            print(
                "A) Users with reviews but NO org_members row "
                f"(lose review access): {len(section_a)}"
            )
            for row in section_a:
                print(
                    f"  ! {row.login} (role={row.role}, "
                    f"{row.review_count} review(s), user_id={row.id})"
                )

            section_b = await _section_b(db)
            findings += sum(r.review_count for r in section_b)
            print(
                "\nB) Reviews in orgs that are missing/memberless "
                f"(visible to PLATFORM_ADMIN only): "
                f"{sum(r.review_count for r in section_b)} review(s)"
            )
            for row in section_b:
                org = str(row.org_id) if row.org_id else "NO ORG ROW"
                print(
                    f"  ! installation {row.installation_id} "
                    f"({row.account_login}): {row.review_count} review(s), "
                    f"org={org}, members={row.member_count}"
                )

            verdict = (
                "FINDINGS — remediate with scripts/org_seed_report.py --apply"
                if findings
                else "clean (safe to retrofit)"
            )
            print(f"\nResult: {verdict}")
    finally:
        await engine.dispose()

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

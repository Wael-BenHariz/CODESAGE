#!/usr/bin/env python3
"""Create a private disposable backend environment from backend/.env."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/.env.example"
TARGET = ROOT / "backend/.env.e2e"


def main() -> None:
    if TARGET.exists():
        print(f"Using existing {TARGET.relative_to(ROOT)}")
        return
    if not SOURCE.is_file():
        raise SystemExit(
            "backend/.env.example is required as the source for placeholder configuration"
        )
    values = {k: v for k, v in dotenv_values(SOURCE).items() if v is not None}
    spa_origin = os.getenv("E2E_BASE_URL", "http://10.171.24.201").rstrip("/")
    keycloak_url = os.getenv("E2E_KEYCLOAK_URL", f"{spa_origin}/auth").rstrip("/")
    values.update(
        DATABASE_URL="postgresql+asyncpg://codesage:codesage@127.0.0.1:5432/codesage_e2e",
        REDIS_URL="redis://127.0.0.1:6379/14",
        HOST="127.0.0.1",
        PORT="8002",
        KEYCLOAK_URL=keycloak_url,
        KEYCLOAK_PUBLIC_URL=keycloak_url,
        DEBUG="false",
        SECRET_KEY=secrets.token_urlsafe(48),
        STATE_TOKEN_SECRET=secrets.token_urlsafe(48),
        LLM_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    TARGET.touch(mode=0o600)
    for key, value in values.items():
        set_key(str(TARGET), key, str(value), quote_mode="always")
    TARGET.chmod(0o600)
    print(
        f"Created {TARGET.relative_to(ROOT)} with loopback-only database and Redis settings"
    )


if __name__ == "__main__":
    main()

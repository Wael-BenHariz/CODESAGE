"""Shared fixtures for the CodeSage backend test suite.

IMPORTANT: the environment block below executes BEFORE any ``app.*`` import.
``app.config`` validates a complete secret set at import time, and
pydantic-settings gives real environment variables precedence over
``backend/.env`` — assigning unconditionally (never ``setdefault``) guarantees
tests run against dedicated test resources (``codesage_test`` DB, Redis DB 15)
and never inherit production credentials from the local ``.env``.
"""

import os

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# --- Test environment (must precede every app import) ----------------------

_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PRIVATE_KEY_PEM = _TEST_PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

os.environ["SECRET_KEY"] = "test-secret-key-0123456789-abcdefghijklmnop"
os.environ["GITHUB_CLIENT_ID"] = "test-github-client-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-github-client-secret"
os.environ["GITHUB_APP_ID"] = "12345"
os.environ["GITHUB_APP_PRIVATE_KEY"] = _TEST_PRIVATE_KEY_PEM
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["STATE_TOKEN_SECRET"] = "test-state-token-secret"
os.environ["GEMINI_API_KEY"] = "test-gemini-api-key"
os.environ["GROQ_API_KEY"] = "test-groq-api-key"
os.environ["LLM_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://codesage:codesage@localhost:5432/codesage_test"
)
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["FRONTEND_URL"] = "http://localhost:4200"
os.environ["API_V1_PREFIX"] = "/api/v1"
# Docs are off in tests (the route-inventory test asserts no public docs
# routes exist) — pin it regardless of the developer's local .env.
os.environ["ENABLE_API_DOCS"] = "False"
os.environ["OAUTH_STATE_TTL_SECONDS"] = "600"
os.environ["AUTH_REFRESH_ROTATION"] = "true"
# Keycloak (identity authority) — tests mint RS256 tokens with a throwaway
# RSA key instead of talking to a realm.
os.environ["KEYCLOAK_URL"] = "http://keycloak.test"
os.environ["KEYCLOAK_REALM"] = "codesage-realm"
os.environ["KEYCLOAK_CLIENT_ID"] = "codesage-backend"
os.environ["KEYCLOAK_PUBLIC_URL"] = "http://localhost:4200/auth"
os.environ["KEYCLOAK_AUDIENCE"] = "codesage-angular"

# --- Application imports (deliberately after the environment block) --------

from jose import jwk as jose_jwk
from jose import jwt as jose_jwt

from app.config import settings
from app.db import async_session_factory, close_db, engine
from app.db.base import Base
from app.db.models import User
from app.main import app
from app.redis import close_redis, get_redis
from app.services.github import github_service

# --- Keycloak token test harness -------------------------------------------

_KC_KID = "test-realm-key-1"


def _build_kc_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_jwk = jose_jwk.construct(key.public_key(), algorithm="RS256")
    jwk_dict = pub_jwk.to_dict()
    jwk_dict["kid"] = _KC_KID
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"
    return priv_pem, {"keys": [jwk_dict]}


_KC_PRIVATE_PEM, KC_JWKS = _build_kc_key()


def make_keycloak_token(
    sub: str = "kc-sub-test-user",
    roles: tuple[str, ...] | list[str] | None = ("DEVELOPER",),
    *,
    issuer: str | None = None,
    azp: str = "codesage-angular",
    iat: int | None = None,
    exp_in: int = 300,
    **claims,
) -> str:
    """Mint a valid RS256 Keycloak-shaped access token for tests.

    Defaults to an access token (``typ: "Bearer"``) carrying realm roles.
    Pass ``roles=None`` to omit ``realm_access`` entirely (a token minted
    without the roles scope), and override any claim — including ``typ`` —
    through ``**claims`` (applied last, so ``typ="ID"`` wins).
    """
    import time as _time

    now = int(_time.time()) if iat is None else iat
    payload = {
        "sub": sub,
        "iss": issuer if issuer is not None else settings.KEYCLOAK_ISSUER,
        "azp": azp,
        "typ": "Bearer",
        "iat": now,
        "exp": now + exp_in,
        "preferred_username": claims.pop("preferred_username", "kc-user"),
    }
    if roles is not None:
        payload["realm_access"] = {"roles": list(roles)}
    payload.update(claims)
    return jose_jwt.encode(
        payload, _KC_PRIVATE_PEM, algorithm="RS256", headers={"kid": _KC_KID}
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db_schema():
    """Create the schema once per session; dispose the engine at teardown.

    ``init_db()`` is deliberately not used: it runs ``create_all`` on
    ``app.db.database.Base``, a different DeclarativeBase that no model
    registers on (it is empty), while every model inherits from
    ``app.db.base.Base`` — so the models' metadata is created directly.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await close_db()


@pytest_asyncio.fixture(autouse=True)
async def _clean_state(_db_schema):
    """Start every test from a clean DB and a clean Redis test database.

    Redis (index 15) is flushed before each test; the shared client is closed
    on teardown so the next test — which runs in its own event loop — opens
    fresh connections instead of reusing loop-bound ones.
    """
    tables = ", ".join(Base.metadata.tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()
    yield
    await close_redis()


@pytest_asyncio.fixture
async def client(_clean_state):
    """httpx AsyncClient bound to the FastAPI app (ASGITransport runs no lifespan)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest_asyncio.fixture
async def db(_clean_state):
    """A dedicated SQLAlchemy session for test setup and assertions."""
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def user(db):
    """A persisted user row that the auth endpoints can resolve."""
    row = User(
        github_id=111222333,
        login="test-user",
        keycloak_id="kc-sub-test-user",
        role="DEVELOPER",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def personal_workspace(db, user):
    """A personal workspace for the test user."""
    from app.db.models.workspaces import Workspace
    
    workspace = Workspace(
        type="PERSONAL",
        name=f"{user.login}'s Personal Workspace",
        owner_user_id=user.id,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@pytest_asyncio.fixture
async def org_workspace(db):
    """An organization workspace for testing."""
    from app.db.models.workspaces import Workspace
    
    workspace = Workspace(
        type="ORG",
        name="Test Organization",
        github_account_login="test-org",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@pytest_asyncio.fixture
async def workspace_member(db, org_workspace, user):
    """A workspace member in the organization workspace with DEVELOPER role."""
    from app.db.models.workspaces import WorkspaceMember
    
    member = WorkspaceMember(
        workspace_id=org_workspace.id,
        user_id=user.id,
        role="DEVELOPER",
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest_asyncio.fixture
async def org_admin_user(db):
    """A user with ORG_ADMIN role in an organization workspace."""
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace, WorkspaceMember
    
    # Create user
    user = User(
        github_id=444555666,
        login="org-admin-user",
        keycloak_id="kc-sub-org-admin",
        role="DEVELOPER",  # Global role, workspace role will be ORG_ADMIN
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Create organization workspace
    workspace = Workspace(
        type="ORG",
        name="Admin Test Organization",
        github_account_login="admin-test-org",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    
    # Add user as ORG_ADMIN in the workspace
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="ORG_ADMIN",
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return user, workspace, member


@pytest_asyncio.fixture
async def reviewer_user(db):
    """A user with REVIEWER role in an organization workspace."""
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace, WorkspaceMember
    
    # Create user
    user = User(
        github_id=777888999,
        login="reviewer-user",
        keycloak_id="kc-sub-reviewer",
        role="DEVELOPER",  # Global role, workspace role will be REVIEWER
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Create organization workspace
    workspace = Workspace(
        type="ORG",
        name="Reviewer Test Organization",
        github_account_login="reviewer-test-org",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    
    # Add user as REVIEWER in the workspace
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="REVIEWER",
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return user, workspace, member


@pytest_asyncio.fixture
async def developer_user(db):
    """A user with DEVELOPER role in an organization workspace."""
    from app.db.models.users import User
    from app.db.models.workspaces import Workspace, WorkspaceMember
    
    # Create user
    user = User(
        github_id=111222333,
        login="developer-user",
        keycloak_id="kc-sub-developer",
        role="DEVELOPER",  # Global role, workspace role will be DEVELOPER
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Create organization workspace
    workspace = Workspace(
        type="ORG",
        name="Developer Test Organization",
        github_account_login="developer-test-org",
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    
    # Add user as DEVELOPER in the workspace
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="DEVELOPER",
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return user, workspace, member


@pytest.fixture(autouse=True)
def mock_jwks(monkeypatch):
    """Serve the throwaway realm JWKS instead of hitting a real Keycloak."""

    async def fake_get_jwks(force: bool = False):
        return KC_JWKS

    from app.security import keycloak as kc

    monkeypatch.setattr(kc, "_get_jwks", fake_get_jwks)
    kc.reset_jwks_cache()


@pytest.fixture(autouse=True)
def mock_github(monkeypatch):
    """Replace GitHub network calls with canned responses (no network I/O)."""

    async def fake_exchange_code_for_token(code):
        return {
            "access_token": "gho_test_access_token",
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": "ghr_test_refresh_token",
        }

    async def fake_get_user_info(access_token):
        return {
            "id": 424242,
            "login": "test-octocat",
            "name": "Test Octocat",
            "email": "octocat@example.com",
            "avatar_url": "https://example.com/avatar.png",
        }

    monkeypatch.setattr(
        github_service, "exchange_code_for_token", fake_exchange_code_for_token
    )
    monkeypatch.setattr(github_service, "get_user_info", fake_get_user_info)

"""Org & platform settings: capability-model guards + merge chain (Step 3).

Contract per docs/PLAN_ROLES_SETTINGS_STAGED.md §2/§3:

- guard order: NONE on a write → 403 first, membership miss → 404
  (uniform detail — cross-org never learns the org exists), effective
  role below requirement → 403; PLATFORM_ADMIN bypasses membership on
  read/settings only (flag F2);
- merge chain: org override → platform default → config/code default,
  numerics clamped to the platform ceiling on read;
- PUT semantics: absent field = keep, explicit null = reset, any
  violation (ceiling/vocabulary/blank model) → 422 **before** persistence;
- audit = structured log with per-field {old, new} (no secrets exist in
  these settings).
"""

import logging
import uuid

import pytest
import pytest_asyncio
from conftest import make_keycloak_token

from app.config import settings
from app.db.models import (
    GitHubInstallation,
    Org,
    OrgSetting,
    PlatformSetting,
    User,
)
from app.services.agents.specialist_agents import MAX_FINDINGS_PER_AGENT
from app.services.org_settings import HARD_CAPS, SETTINGS_FIELDS
from app.services.review_orchestrator import AGENT_DOMAINS
from app.workers.review_processor import DIFF_MAX_CHARS

API = settings.API_V1_PREFIX

_ORG_URL = f"{API}/orgs/{{org_id}}/settings"
_PLATFORM_URL = f"{API}/platform/settings"

_INSTALLATION_ID = 100_111


def _auth(keycloak_id: str, roles: tuple[str, ...] = ("DEVELOPER",)) -> dict:
    return {
        "Authorization": f"Bearer {make_keycloak_token(sub=keycloak_id, roles=roles)}"
    }


async def _make_user(db, keycloak_id: str, *, github_id: int | None = None) -> User:
    row = User(
        keycloak_id=keycloak_id,
        login=keycloak_id,
        role="DEVELOPER",
        github_id=github_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _make_org(
    db, *, name: str = "acme", installation_id: int = _INSTALLATION_ID
) -> Org:
    installation = GitHubInstallation(
        app_id=1,
        installation_id=installation_id,
        account_id=900_001,
        account_login=name,
        account_type="Organization",
    )
    db.add(installation)
    await db.flush()
    org = Org(
        name=name,
        account_type="Organization",
        installation_id=installation_id,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _make_member(db, org: Org, user: User, role: str) -> None:
    from app.db.models import OrgMember

    db.add(OrgMember(org_id=org.id, user_id=user.id, role=role))
    await db.commit()


@pytest_asyncio.fixture
async def platform_settings(db):
    """The single platform_settings row exactly as migration 013 seeds it.

    ``create_all`` (the test schema) creates the table without data, so
    tests asserting the *initial* ceilings mirror the migration's seed.
    """
    row = PlatformSetting(
        ceiling_diff_char_cap=100_000,
        ceiling_max_findings_per_agent=50,
        ceiling_max_concurrent_reviews=10,
    )
    db.add(row)
    await db.commit()
    return row


# ---------------------------------------------------------------------------
# GET /orgs/{org_id}/settings — guard matrix
# ---------------------------------------------------------------------------


async def test_org_get_requires_auth(client):
    resp = await client.get(_ORG_URL.format(org_id=uuid.uuid4()))
    assert resp.status_code == 401


async def test_org_get_unknown_org_is_404(client, db):
    """Org that does not exist → uniform 404 (never 403)."""
    await _make_user(db, "kc-plain")
    resp = await client.get(
        _ORG_URL.format(org_id=uuid.uuid4()),
        headers=_auth("kc-plain", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Organization not found"


async def test_org_get_cross_org_is_404(client, db):
    """The one cross-org test for GET: ORG_ADMIN of B, reading A → 404."""
    org_a = await _make_org(db, name="org-a", installation_id=1)
    org_b = await _make_org(db, name="org-b", installation_id=2)
    admin = await _make_user(db, "kc-admin-b")
    await _make_member(db, org_b, admin, "ORG_ADMIN")

    resp = await client.get(
        _ORG_URL.format(org_id=org_a.id),
        headers=_auth("kc-admin-b", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Organization not found"


async def test_org_get_none_is_404_not_403(client, db):
    """NONE has no membership (never stored) → 404 on reads, not 403."""
    org = await _make_org(db)
    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-none", ("NONE",)),
    )
    assert resp.status_code == 404


async def test_org_get_member_below_org_admin_is_403(client, db):
    org = await _make_org(db)
    dev = await _make_user(db, "kc-dev")
    rev = await _make_user(db, "kc-rev")
    await _make_member(db, org, dev, "DEVELOPER")
    await _make_member(db, org, rev, "REVIEWER")

    resp = await client.get(
        _ORG_URL.format(org_id=org.id), headers=_auth("kc-dev", ("DEVELOPER",))
    )
    assert resp.status_code == 403

    resp = await client.get(
        _ORG_URL.format(org_id=org.id), headers=_auth("kc-rev", ("REVIEWER",))
    )
    assert resp.status_code == 403


async def test_org_get_global_role_without_membership_is_404(client, db):
    """A global ORG_ADMIN claim alone never grants org access (§2 step 2)."""
    org = await _make_org(db)
    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-global-admin", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 404


async def test_org_get_member_org_admin_200(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-member-admin")
    await _make_member(db, org, admin, "ORG_ADMIN")

    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-member-admin", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["org_id"] == str(org.id)


async def test_org_get_effective_role_is_max_of_jwt_and_member(client, db):
    """Global DEVELOPER + org_members ORG_ADMIN → effective ORG_ADMIN (200)."""
    org = await _make_org(db)
    member = await _make_user(db, "kc-dev-but-org-admin")
    await _make_member(db, org, member, "ORG_ADMIN")

    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-dev-but-org-admin", ("DEVELOPER",)),
    )
    assert resp.status_code == 200


async def test_org_get_platform_admin_bypasses_membership(client, db):
    """F2: PLATFORM_ADMIN may read settings without an org_members row."""
    org = await _make_org(db)
    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-platform", ("PLATFORM_ADMIN",)),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /orgs/{org_id}/settings — guard matrix
# ---------------------------------------------------------------------------


async def test_org_put_none_is_403_first_even_for_unknown_org(client):
    """NONE hits step 1 on writes — 403 before any 404 lookup."""
    resp = await client.put(
        _ORG_URL.format(org_id=uuid.uuid4()),
        headers=_auth("kc-none-put", ("NONE",)),
        json={"diff_char_cap": 1000},
    )
    assert resp.status_code == 403


async def test_org_put_cross_org_is_404(client, db):
    """The one cross-org test for PUT: ORG_ADMIN of B writing A → 404."""
    org_a = await _make_org(db, name="org-a", installation_id=11)
    org_b = await _make_org(db, name="org-b", installation_id=12)
    admin = await _make_user(db, "kc-admin-b2")
    await _make_member(db, org_b, admin, "ORG_ADMIN")

    resp = await client.put(
        _ORG_URL.format(org_id=org_a.id),
        headers=_auth("kc-admin-b2", ("ORG_ADMIN",)),
        json={"diff_char_cap": 1000},
    )
    assert resp.status_code == 404


async def test_org_put_member_developer_is_403(client, db):
    """Membership passes (step 2), effective DEVELOPER < ORG_ADMIN (step 3)."""
    org = await _make_org(db)
    dev = await _make_user(db, "kc-dev-put")
    await _make_member(db, org, dev, "DEVELOPER")

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-dev-put", ("DEVELOPER",)),
        json={"diff_char_cap": 1000},
    )
    assert resp.status_code == 403

    # And nothing was written: an ORG_ADMIN member still sees no overrides.
    admin = await _make_user(db, "kc-dev-put-admin")
    await _make_member(db, org, admin, "ORG_ADMIN")
    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-dev-put-admin", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["overrides"]["diff_char_cap"] is None


async def test_org_put_platform_admin_bypasses_membership(client, db):
    """F2: PUT /orgs/{id}/settings is a settings endpoint → bypass allowed."""
    org = await _make_org(db)
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-platform-put", ("PLATFORM_ADMIN",)),
        json={"diff_char_cap": 9000},
    )
    assert resp.status_code == 200
    assert resp.json()["overrides"]["diff_char_cap"] == 9000


# ---------------------------------------------------------------------------
# Merge chain: defaults → override → null-reset → ceilings
# ---------------------------------------------------------------------------


async def test_org_get_defaults_from_config(client, db, platform_settings):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-defaults")
    await _make_member(db, org, admin, "ORG_ADMIN")

    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-defaults", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    body = resp.json()

    # Every stored override starts NULL (config/code defaults win).
    assert all(body["overrides"][f] is None for f in SETTINGS_FIELDS)
    assert all(body["overridden"][f] is False for f in SETTINGS_FIELDS)

    effective = body["effective"]
    assert effective["diff_char_cap"] == settings.LLM_DIFF_CHAR_CAP
    assert effective["max_findings_per_agent"] == MAX_FINDINGS_PER_AGENT
    assert effective["max_concurrent_reviews"] == settings.BULLMQ_CONCURRENCY
    assert effective["enabled_agents"] == list(AGENT_DOMAINS)
    assert effective["sonarqube_enabled"] is True
    assert effective["semgrep_enabled"] == settings.SEMGREP_ENABLED
    assert effective["review_triggers"] == ["pull_request", "manual"]
    assert effective["min_severity_to_post"] == "info"
    assert effective["posting_mode"] == "auto"
    assert effective["ai_model"] is None

    assert body["ceilings"] == {
        "diff_char_cap": 100_000,
        "max_findings_per_agent": 50,
        "max_concurrent_reviews": 10,
    }


async def test_org_put_override_wins_and_absent_fields_keep(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-override")
    await _make_member(db, org, admin, "ORG_ADMIN")
    headers = _auth("kc-override", ("ORG_ADMIN",))

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"diff_char_cap": 5000},
    )
    assert resp.status_code == 200
    assert resp.json()["effective"]["diff_char_cap"] == 5000
    assert resp.json()["overridden"]["diff_char_cap"] is True

    # Absent field (max_findings_per_agent) must stay untouched…
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"max_findings_per_agent": 7},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["effective"]["diff_char_cap"] == 5000
    assert body["effective"]["max_findings_per_agent"] == 7
    assert body["overridden"]["diff_char_cap"] is True


async def test_org_put_explicit_null_resets_to_default(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-reset")
    await _make_member(db, org, admin, "ORG_ADMIN")
    headers = _auth("kc-reset", ("ORG_ADMIN",))

    await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"diff_char_cap": 5000, "max_findings_per_agent": 7},
    )
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"diff_char_cap": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overrides"]["diff_char_cap"] is None
    assert body["overridden"]["diff_char_cap"] is False
    assert body["effective"]["diff_char_cap"] == settings.LLM_DIFF_CHAR_CAP
    # The other override survives the reset.
    assert body["overridden"]["max_findings_per_agent"] is True


async def test_org_put_numeric_above_ceiling_is_422_and_not_persisted(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-ceiling")
    await _make_member(db, org, admin, "ORG_ADMIN")
    headers = _auth("kc-ceiling", ("ORG_ADMIN",))

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"diff_char_cap": 100_001},
    )
    assert resp.status_code == 422
    assert "ceiling" in resp.json()["detail"]

    # Rejected before persistence.
    resp = await client.get(_ORG_URL.format(org_id=org.id), headers=headers)
    assert resp.json()["overrides"]["diff_char_cap"] is None


async def test_org_put_below_one_is_422(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-floor")
    await _make_member(db, org, admin, "ORG_ADMIN")

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-floor", ("ORG_ADMIN",)),
        json={"max_findings_per_agent": 0},
    )
    assert resp.status_code == 422


async def test_org_numeric_is_clamped_to_ceiling_on_read(client, db):
    """Even a hand-edited row above the ceiling serves the ceiling."""
    org = await _make_org(db)
    admin = await _make_user(db, "kc-clamp")
    await _make_member(db, org, admin, "ORG_ADMIN")
    db.add(OrgSetting(org_id=org.id, diff_char_cap=999_999))
    await db.commit()

    resp = await client.get(
        _ORG_URL.format(org_id=org.id),
        headers=_auth("kc-clamp", ("ORG_ADMIN",)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["effective"]["diff_char_cap"] == 100_000  # clamped to ceiling
    assert body["overrides"]["diff_char_cap"] == 999_999  # stored value shown
    assert body["overridden"]["diff_char_cap"] is True


async def test_org_put_agent_vocabulary(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-agents")
    await _make_member(db, org, admin, "ORG_ADMIN")
    headers = _auth("kc-agents", ("ORG_ADMIN",))

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"enabled_agents": ["security", "bogus-agent"]},
    )
    assert resp.status_code == 422
    assert "bogus-agent" in resp.json()["detail"]

    # Empty list is valid: summary-only runs.
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"enabled_agents": []},
    )
    assert resp.status_code == 200
    assert resp.json()["effective"]["enabled_agents"] == []

    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={"enabled_agents": ["security"]},
    )
    assert resp.status_code == 200
    assert resp.json()["effective"]["enabled_agents"] == ["security"]


async def test_org_put_enum_vocabulary(client, db):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-enums")
    await _make_member(db, org, admin, "ORG_ADMIN")
    headers = _auth("kc-enums", ("ORG_ADMIN",))

    for payload in (
        {"posting_mode": "manual"},
        {"min_severity_to_post": "blocker"},
        {"review_triggers": ["push"]},
        {"ai_model": "   "},
    ):
        resp = await client.put(
            _ORG_URL.format(org_id=org.id), headers=headers, json=payload
        )
        assert resp.status_code == 422, payload

    # Valid values persist.
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=headers,
        json={
            "posting_mode": "staged",
            "min_severity_to_post": "high",
            "review_triggers": ["manual"],
            "ai_model": "llama-3.3-70b",
        },
    )
    assert resp.status_code == 200
    effective = resp.json()["effective"]
    assert effective["posting_mode"] == "staged"
    assert effective["min_severity_to_post"] == "high"
    assert effective["review_triggers"] == ["manual"]
    assert effective["ai_model"] == "llama-3.3-70b"


async def test_org_put_writes_structured_audit_log(client, db, caplog):
    org = await _make_org(db)
    admin = await _make_user(db, "kc-audit")
    await _make_member(db, org, admin, "ORG_ADMIN")

    with caplog.at_level(logging.INFO, logger="app.api.routes.orgs"):
        resp = await client.put(
            _ORG_URL.format(org_id=org.id),
            headers=_auth("kc-audit", ("ORG_ADMIN",)),
            json={"diff_char_cap": 4321},
        )
    assert resp.status_code == 200

    records = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("org_settings_updated")
    ]
    assert records, "audit log line missing"
    message = records[0]
    assert "actor_id=" in message
    assert "actor_login=kc-audit" in message
    assert f"org_id={org.id}" in message
    assert "'old': None" in message
    assert "'new': 4321" in message


# ---------------------------------------------------------------------------
# GET/PUT /platform/settings — PLATFORM_ADMIN only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "roles", [("DEVELOPER",), ("ORG_ADMIN",), ("REVIEWER",), ("NONE",)]
)
async def test_platform_get_non_admin_is_403(client, roles):
    resp = await client.get(_PLATFORM_URL, headers=_auth("kc-x", roles))
    assert resp.status_code == 403


@pytest.mark.parametrize("roles", [("DEVELOPER",), ("ORG_ADMIN",), ("NONE",)])
async def test_platform_put_non_admin_is_403(client, roles):
    resp = await client.put(
        _PLATFORM_URL, headers=_auth("kc-y", roles), json={"defaults": {}}
    )
    assert resp.status_code == 403


async def test_platform_settings_require_auth(client):
    resp = await client.get(_PLATFORM_URL)
    assert resp.status_code == 401


async def test_platform_get_defaults(client, platform_settings):
    resp = await client.get(_PLATFORM_URL, headers=_auth("kc-pa", ("PLATFORM_ADMIN",)))
    assert resp.status_code == 200
    body = resp.json()

    assert all(body["defaults"][f] is None for f in SETTINGS_FIELDS)
    assert body["ceilings"] == {
        "diff_char_cap": 100_000,
        "max_findings_per_agent": 50,
        "max_concurrent_reviews": 10,
    }
    # HARD_CAPS are unraisable in-code maxima — strictly above the seeded
    # ceilings for findings/concurrency.
    assert body["hard_caps"] == {
        "diff_char_cap": 100_000,
        "max_findings_per_agent": 100,
        "max_concurrent_reviews": 50,
    }
    effective = body["effective_defaults"]
    assert effective["diff_char_cap"] == settings.LLM_DIFF_CHAR_CAP
    assert effective["posting_mode"] == "auto"
    assert effective["enabled_agents"] == list(AGENT_DOMAINS)


async def test_platform_put_ceiling_and_reset(client):
    headers = _auth("kc-pa-put", ("PLATFORM_ADMIN",))

    resp = await client.put(
        _PLATFORM_URL, headers=headers, json={"ceilings": {"diff_char_cap": 50_000}}
    )
    assert resp.status_code == 200
    assert resp.json()["ceilings"]["diff_char_cap"] == 50_000

    # Explicit null resets the ceiling to the hard cap.
    resp = await client.put(
        _PLATFORM_URL, headers=headers, json={"ceilings": {"diff_char_cap": None}}
    )
    assert resp.status_code == 200
    assert resp.json()["ceilings"]["diff_char_cap"] == HARD_CAPS["diff_char_cap"]


async def test_platform_put_ceiling_above_hard_cap_422(client):
    resp = await client.put(
        _PLATFORM_URL,
        headers=_auth("kc-pa-hc", ("PLATFORM_ADMIN",)),
        json={"ceilings": {"diff_char_cap": HARD_CAPS["diff_char_cap"] + 1}},
    )
    assert resp.status_code == 422
    assert "hard cap" in resp.json()["detail"]


async def test_platform_put_default_above_final_ceiling_422(client):
    """Ceiling lowered and default raised in ONE request → 422 on default."""
    resp = await client.put(
        _PLATFORM_URL,
        headers=_auth("kc-pa-combo", ("PLATFORM_ADMIN",)),
        json={
            "ceilings": {"max_findings_per_agent": 10},
            "defaults": {"max_findings_per_agent": 15},
        },
    )
    assert resp.status_code == 422
    assert "ceiling" in resp.json()["detail"]


async def test_platform_put_default_enum_and_blank_422(client):
    headers = _auth("kc-pa-enum", ("PLATFORM_ADMIN",))
    for payload in (
        {"defaults": {"posting_mode": "weird"}},
        {"defaults": {"enabled_agents": ["nope"]}},
        {"defaults": {"ai_model": ""}},
    ):
        resp = await client.put(_PLATFORM_URL, headers=headers, json=payload)
        assert resp.status_code == 422, payload


async def test_platform_default_flows_to_org_and_ceiling_guards_org_put(client, db):
    """Platform default becomes the org default; platform ceiling gates PUTs."""
    org = await _make_org(db)
    admin = await _make_user(db, "kc-flow")
    await _make_member(db, org, admin, "ORG_ADMIN")
    org_headers = _auth("kc-flow", ("ORG_ADMIN",))
    pa_headers = _auth("kc-pa-flow", ("PLATFORM_ADMIN",))

    resp = await client.put(
        _PLATFORM_URL,
        headers=pa_headers,
        json={
            "defaults": {"diff_char_cap": 8000},
            "ceilings": {"diff_char_cap": 9000},
        },
    )
    assert resp.status_code == 200

    # Org has no override → platform default (8000) wins over config (16000).
    resp = await client.get(_ORG_URL.format(org_id=org.id), headers=org_headers)
    assert resp.json()["effective"]["diff_char_cap"] == 8000
    assert resp.json()["ceilings"]["diff_char_cap"] == 9000

    # Org override below the platform ceiling works…
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=org_headers,
        json={"diff_char_cap": 6000},
    )
    assert resp.status_code == 200
    assert resp.json()["effective"]["diff_char_cap"] == 6000

    # …above it is rejected (ceiling comes from the platform row, live).
    resp = await client.put(
        _ORG_URL.format(org_id=org.id),
        headers=org_headers,
        json={"diff_char_cap": 9001},
    )
    assert resp.status_code == 422


async def test_platform_put_writes_structured_audit_log(client, caplog):
    headers = _auth("kc-pa-audit", ("PLATFORM_ADMIN",))
    with caplog.at_level(logging.INFO, logger="app.api.routes.platform"):
        resp = await client.put(
            _PLATFORM_URL,
            headers=headers,
            json={"defaults": {"posting_mode": "staged"}},
        )
    assert resp.status_code == 200

    records = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("platform_settings_updated")
    ]
    assert records, "audit log line missing"
    assert "actor_id=" in records[0]
    assert "'old': None" in records[0]
    assert "'new': 'staged'" in records[0]


# ---------------------------------------------------------------------------
# Cross-cutting invariants
# ---------------------------------------------------------------------------


def test_hard_caps_match_worker_constants():
    """The comment in org_settings.py promises this parity pin."""
    assert HARD_CAPS["diff_char_cap"] == DIFF_MAX_CHARS
    assert HARD_CAPS == {
        "diff_char_cap": 100_000,
        "max_findings_per_agent": 100,
        "max_concurrent_reviews": 50,
    }

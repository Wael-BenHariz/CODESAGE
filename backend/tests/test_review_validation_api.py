"""Step 9 — reviewer validation endpoint (plan §3).

Contracts covered here:

- **Guard matrix**: DEVELOPER member → 403, NONE → 403 first (before any
  lookup), cross-org → the uniform 404, PLATFORM_ADMIN without a
  membership row → 404 (F2 carve-out list includes ``validate``).
- **Upsert**: one row per (comment, reviewer) — a second verdict from the
  same reviewer replaces the first (``ON CONFLICT ... DO UPDATE``), while
  two different reviewers keep two rows.
- **Enums**: unknown ``verdict`` or ``severity_override`` → 422 (pydantic
  ``Literal`` mirrors the migration 016 CHECK constraints).
- **Detail round-trip**: ``GET /reviews/{id}`` carries each comment's
  validations (verdict, severity_override, note, reviewer login,
  timestamps); untouched findings report an empty list.
- **Notes**: stored as-is (plain text) — no server-side sanitization, the
  frontend escapes on render (static guarantee in
  ``test_frontend_render_safety.py``).
"""

from types import SimpleNamespace

import pytest_asyncio
from test_review_api_staged import _auth, _comment_of, _make_chain, _make_user

from app.config import settings
from app.db.models import OrgMember

_REVIEWS = f"{settings.API_V1_PREFIX}/reviews"


@pytest_asyncio.fixture
async def vstage(db):
    """Org A's review plus members at every elevation the tests need."""
    a = await _make_chain(
        db, installation_id=777301, owner="owner-a", org_name="org-a", number=1
    )
    b = await _make_chain(
        db, installation_id=777302, owner="owner-b", org_name="org-b", number=2
    )
    dev = await _make_user(db, "kc-dev-a")
    reviewer = await _make_user(db, "kc-reviewer-a")
    reviewer2 = await _make_user(db, "kc-reviewer-b")
    pa = await _make_user(db, "kc-pa", role="PLATFORM_ADMIN")
    none_user = await _make_user(db, "kc-none")
    other = await _make_user(db, "kc-dev-b")

    db.add(OrgMember(org_id=a.org.id, user_id=dev.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=a.org.id, user_id=reviewer.id, role="REVIEWER"))
    db.add(OrgMember(org_id=a.org.id, user_id=reviewer2.id, role="REVIEWER"))
    db.add(OrgMember(org_id=a.org.id, user_id=none_user.id, role="DEVELOPER"))
    db.add(OrgMember(org_id=b.org.id, user_id=other.id, role="DEVELOPER"))
    await db.commit()
    return SimpleNamespace(
        a=a,
        b=b,
        dev=dev,
        reviewer=reviewer,
        reviewer2=reviewer2,
        pa=pa,
        none_user=none_user,
        other=other,
    )


def _validate_url(review, comment) -> str:
    return f"{_REVIEWS}/{review.id}/comments/{comment.id}/validate"


# ---------------------------------------------------------------------------
# Guard matrix: DEVELOPER 403, NONE 403, cross-org 404, F2 carve-out
# ---------------------------------------------------------------------------


async def test_developer_member_is_403(client, vstage):
    """Membership alone is not enough: verdicts need effective >= REVIEWER."""
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "confirmed"},
        headers=_auth("kc-dev-a"),
    )
    assert resp.status_code == 403


async def test_none_is_403_first(client, vstage):
    """NONE-first: 403 before membership (the member row exists here)."""
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "confirmed"},
        headers=_auth("kc-none", ("NONE",)),
    )
    assert resp.status_code == 403


async def test_cross_org_validate_is_404(client, vstage):
    """Uniform 404: a member of org B must not learn org A's review id."""
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "confirmed"},
        headers=_auth("kc-dev-b"),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_platform_admin_without_membership_is_404(client, vstage):
    """F2 carve-out: validate joins dismiss/restore/summary/post — no bypass."""
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "confirmed"},
        headers=_auth("kc-pa", ("PLATFORM_ADMIN",)),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Review not found"


async def test_comment_from_another_review_is_404(client, vstage):
    """An existing comment of a different review is never revealed."""
    foreign = _comment_of(vstage.b.review, severity="info")
    resp = await client.patch(
        _validate_url(vstage.a.review, foreign),
        json={"verdict": "confirmed"},
        headers=_auth("kc-dev-a", ("REVIEWER",)),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Comment not found"


# ---------------------------------------------------------------------------
# Enums → 422
# ---------------------------------------------------------------------------


async def test_unknown_verdict_is_422(client, vstage):
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "banana"},
        headers=_auth("kc-reviewer-a"),
    )
    assert resp.status_code == 422


async def test_unknown_severity_override_is_422(client, vstage):
    comment = _comment_of(vstage.a.review, severity="error")
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "confirmed", "severity_override": "critical"},
        headers=_auth("kc-reviewer-a"),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Happy path, upsert, detail round-trip
# ---------------------------------------------------------------------------


async def test_reviewer_validates_and_detail_round_trips(client, vstage):
    comment = _comment_of(vstage.a.review, severity="error")
    note = "True positive — see src/a.py:10"
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={
            "verdict": "confirmed",
            "severity_override": "error",
            "note": note,
        },
        headers=_auth("kc-reviewer-a"),  # JWT DEVELOPER + org role REVIEWER
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "confirmed"
    assert body["severity_override"] == "error"
    assert body["note"] == note
    assert body["reviewer_login"] == "kc-reviewer-a"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None

    # Step 10 renders verdicts from the review detail.
    resp = await client.get(
        f"{_REVIEWS}/{vstage.a.review.id}", headers=_auth("kc-reviewer-a")
    )
    assert resp.status_code == 200
    comments = {c["severity"]: c for c in resp.json()["comments"]}
    validations = comments["error"]["validations"]
    assert len(validations) == 1
    assert validations[0]["verdict"] == "confirmed"
    assert validations[0]["severity_override"] == "error"
    assert validations[0]["note"] == note
    assert validations[0]["reviewer_login"] == "kc-reviewer-a"
    # The untouched finding reports an empty list, not a missing key.
    assert comments["info"]["validations"] == []


async def test_upsert_replaces_prior_verdict(client, vstage):
    """A changed mind REPLACES the verdict: one row per reviewer."""
    comment = _comment_of(vstage.a.review, severity="error")
    url = _validate_url(vstage.a.review, comment)

    first = await client.patch(
        url,
        json={"verdict": "false_positive", "note": "FP"},
        headers=_auth("kc-reviewer-a"),
    )
    assert first.status_code == 200
    assert first.json()["verdict"] == "false_positive"

    second = await client.patch(
        url,
        json={
            "verdict": "needs_investigation",
            "severity_override": "warning",
            "note": "changed my mind",
        },
        headers=_auth("kc-reviewer-a"),
    )
    assert second.status_code == 200
    assert second.json()["verdict"] == "needs_investigation"
    assert second.json()["severity_override"] == "warning"
    # Same row: created_at is stable, updated_at moved.
    assert second.json()["created_at"] == first.json()["created_at"]
    assert second.json()["updated_at"] >= first.json()["created_at"]

    resp = await client.get(
        f"{_REVIEWS}/{vstage.a.review.id}", headers=_auth("kc-reviewer-a")
    )
    validations = next(
        c["validations"] for c in resp.json()["comments"] if c["severity"] == "error"
    )
    assert len(validations) == 1  # replaced, not appended
    assert validations[0]["verdict"] == "needs_investigation"
    assert validations[0]["note"] == "changed my mind"


async def test_two_reviewers_keep_two_rows(client, vstage):
    """UNIQUE (comment_id, reviewer_id): each reviewer owns their verdict."""
    comment = _comment_of(vstage.a.review, severity="error")
    url = _validate_url(vstage.a.review, comment)

    resp = await client.patch(
        url, json={"verdict": "confirmed"}, headers=_auth("kc-reviewer-a")
    )
    assert resp.status_code == 200
    resp = await client.patch(
        url, json={"verdict": "false_positive"}, headers=_auth("kc-reviewer-b")
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"{_REVIEWS}/{vstage.a.review.id}", headers=_auth("kc-reviewer-a")
    )
    validations = next(
        c["validations"] for c in resp.json()["comments"] if c["severity"] == "error"
    )
    assert len(validations) == 2
    assert {v["reviewer_login"] for v in validations} == {
        "kc-reviewer-a",
        "kc-reviewer-b",
    }


async def test_note_is_stored_as_plain_text(client, vstage):
    """Notes are stored verbatim — no server-side sanitization or parsing."""
    comment = _comment_of(vstage.a.review, severity="error")
    note = '<script>alert("x")</script> & @alice stays literal'
    resp = await client.patch(
        _validate_url(vstage.a.review, comment),
        json={"verdict": "needs_investigation", "note": note},
        headers=_auth("kc-reviewer-a"),
    )
    assert resp.status_code == 200
    assert resp.json()["note"] == note

    resp = await client.get(
        f"{_REVIEWS}/{vstage.a.review.id}", headers=_auth("kc-reviewer-a")
    )
    validations = next(
        c["validations"] for c in resp.json()["comments"] if c["severity"] == "error"
    )
    assert validations[0]["note"] == note

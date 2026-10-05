"""Step 7b — source-finding enrichment + review detail panel contract.

Plan §3 (Step 7b):

- ``_find_source_finding``: the deterministic match of a specialist
  comment back to the normalized finding it refines — domain-scoped via
  the orchestrator-stamped ``source_domain``, line-level range match,
  file-level match only for a file with exactly one finding, ties
  resolved tightest-range-first. Unmatched → all-NULL enrichment.
- ``ReviewOrchestrator`` stamps ``source_domain`` AFTER parsing (never
  trusting the LLM) and the stamp survives the deterministic merge.
- ``process_review_job`` persists tool/rule_id/cwe/line_start/line_end/
  snippet/also_detected_by onto each new comment; comments that don't
  match (wrong domain, line outside every range, other file) stay NULL.
- ``GET /reviews/{id}`` exposes the enrichment columns and ``viewer_role``
  (caller's effective org role; PLATFORM_ADMIN without a membership row
  reads via the F2 bypass and sees its own role).
"""

import json
import re
from types import SimpleNamespace

from sqlalchemy import select
from test_review_api_staged import (
    _auth as staged_auth,
)
from test_review_api_staged import (
    _make_chain as staged_chain,
)
from test_review_api_staged import _make_user

# Imported for its pytest side effect: registers the shared ``pipeline``
# fixture in this module's namespace (used as a fixture parameter below —
# that parameter is what ruff sees as a "redefinition").
from test_worker_org_settings import (
    _DEFAULT_PAYLOAD,
    _Result,
    _run_job,
    pipeline,  # noqa: F401
)
from test_worker_org_settings import _make_chain as worker_chain

from app.config import settings
from app.db.models import OrgMember, ReviewComment
from app.services.agents import ReviewContext
from app.services.agents.schemas import AgentComment
from app.services.llm_client import BaseLLMClient
from app.services.normalizers.schema import NormalizedFinding
from app.services.review_orchestrator import ReviewOrchestrator
from app.workers import review_processor as rp

API = settings.API_V1_PREFIX
_REVIEWS = f"{API}/reviews"


def _finding(**overrides) -> NormalizedFinding:
    base = {
        "tool": "sonarqube",
        "rule_id": "java:S2077",
        "message": "Use parameterized statements",
        "severity": "high",
        "category": "vulnerability",  # -> security domain
        "file_path": "a.py",
        "line_start": 10,
        "line_end": 12,
        "snippet": "10: query(userInput)",
        "cwe": ["CWE-89"],
        "also_detected_by": ["semgrep"],
    }
    base.update(overrides)
    return NormalizedFinding(**base)


# --- _find_source_finding (unit) ---------------------------------------------


def test_line_comment_matches_finding_range():
    comment = {"file_path": "a.py", "line_number": 11}
    found = rp._find_source_finding(comment, [_finding()])
    assert found is not None
    assert found.rule_id == "java:S2077"


def test_single_line_finding_matches_only_its_own_line():
    finding = _finding(line_start=10, line_end=None)
    assert rp._find_source_finding({"file_path": "a.py", "line_number": 10}, [finding])
    assert (
        rp._find_source_finding({"file_path": "a.py", "line_number": 11}, [finding])
        is None
    )


def test_line_comment_outside_every_range_is_unmatched():
    assert (
        rp._find_source_finding({"file_path": "a.py", "line_number": 99}, [_finding()])
        is None
    )


def test_line_comment_never_falls_back_to_file_level():
    # A lineless finding on the same file must NOT absorb a line comment
    # that falls outside its (nonexistent) range.
    finding = _finding(line_start=None, line_end=None)
    assert (
        rp._find_source_finding({"file_path": "a.py", "line_number": 3}, [finding])
        is None
    )


def test_file_level_comment_matches_single_finding():
    finding = _finding(line_start=None, line_end=None)
    found = rp._find_source_finding(
        {"file_path": "a.py", "line_number": None}, [finding]
    )
    assert found is finding


def test_file_level_comment_with_multiple_findings_is_unmatched():
    findings = [_finding(rule_id="R1"), _finding(rule_id="R2", file_path="a.py")]
    assert (
        rp._find_source_finding({"file_path": "a.py", "line_number": None}, findings)
        is None
    )


def test_match_is_scoped_to_source_domain():
    findings = [_finding()]  # routes to the security domain
    right = {"file_path": "a.py", "line_number": 11, "source_domain": "security"}
    wrong = {"file_path": "a.py", "line_number": 11, "source_domain": "style"}
    assert rp._find_source_finding(right, findings) is not None
    # Same file+line, but the finding belongs to another domain's slice.
    assert rp._find_source_finding(wrong, findings) is None


def test_comment_without_provenance_matches_flat():
    findings = [_finding()]
    comment = {"file_path": "a.py", "line_number": 11}  # no source_domain
    assert rp._find_source_finding(comment, findings) is not None


def test_overlapping_ranges_pick_tightest_then_lowest():
    loose = _finding(rule_id="B-wide", line_start=5, line_end=15)
    tight = _finding(rule_id="A-tight", line_start=10, line_end=12)
    found = rp._find_source_finding(
        {"file_path": "a.py", "line_number": 11}, [loose, tight]
    )
    assert found is tight  # tightest range wins regardless of input order
    found = rp._find_source_finding(
        {"file_path": "a.py", "line_number": 11}, [tight, loose]
    )
    assert found is tight


def test_other_file_never_matches():
    assert (
        rp._find_source_finding({"file_path": "b.py", "line_number": 11}, [_finding()])
        is None
    )


# --- orchestrator stamps source_domain ---------------------------------------


class _FakeLLM(BaseLLMClient):
    """Answers each specialist with one comment; synthesis with a summary.

    The security answer deliberately sends a bogus ``source_domain`` —
    the orchestrator must overwrite it with the real domain.
    """

    def __init__(self):
        super().__init__(api_key="test-key", model="fake-model")

    @property
    def model_name(self) -> str:
        return self.model

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        if "You are synthesizing a GitHub PR code review" in prompt:
            return json.dumps(
                {"summary": "Synthesized summary.", "overall_severity": "info"}
            )
        if "No issues found in this category." in prompt:
            return json.dumps({"confidence": 0.5, "comments": []})
        domain = re.search(r"## Findings \(([^)]+)\)", prompt).group(1)
        comments = {
            "security": [
                {
                    "file_path": "a.py",
                    "line_number": 11,
                    "severity": "error",
                    "category": "security",
                    "body": "sql risk",
                    "source_domain": "bogus",  # must be overwritten
                }
            ],
            "style and maintainability": [
                {
                    "file_path": "b.py",
                    "line_number": 5,
                    "severity": "info",
                    "category": "style",
                    "body": "import order",
                }
            ],
        }[domain]
        return json.dumps({"confidence": 0.9, "comments": comments})


async def test_orchestrator_stamps_domain_and_never_trusts_llm():
    context = ReviewContext(
        pr_title="t",
        diff="",
        findings=[
            _finding(),  # security domain
            _finding(
                tool="semgrep",
                rule_id="python.style.import-order",
                category="best_practice",
                file_path="b.py",
                line_start=5,
                line_end=None,
            ),  # style domain
        ],
    )
    result = await ReviewOrchestrator(_FakeLLM()).run(context)

    by_body = {c.body: c for c in result.comments}
    assert by_body["sql risk"].source_domain == "security"  # LLM's "bogus" lost
    assert by_body["import order"].source_domain == "style"


def test_agent_comment_source_domain_defaults_to_none():
    assert AgentComment(file_path="a.py").source_domain is None


# --- worker persists the enrichment ------------------------------------------


_ENRICHED_PAYLOAD = {
    **_DEFAULT_PAYLOAD,
    "comments": [
        # in range + own domain -> enriched
        {
            "file_path": "a.py",
            "line_number": 11,
            "severity": "error",
            "category": "security",
            "body": "SQL injection risk",
            "source_domain": "security",
        },
        # line outside every range -> NULL
        {
            "file_path": "a.py",
            "line_number": 99,
            "severity": "warning",
            "category": "general",
            "body": "Far away",
            "source_domain": "security",
        },
        # right line, WRONG domain -> NULL (domain scoping)
        {
            "file_path": "a.py",
            "line_number": 11,
            "severity": "info",
            "category": "general",
            "body": "Different domain",
            "source_domain": "style",
        },
        # other file -> NULL
        {
            "file_path": "other.py",
            "line_number": 3,
            "severity": "info",
            "category": "general",
            "body": "Other file",
            "source_domain": "security",
        },
    ],
}


async def test_worker_stamps_enrichment_on_new_comments(
    pipeline, db, user, monkeypatch  # noqa: F811 — shared fixture, see import
):
    async def fake_static(**kwargs):
        return SimpleNamespace(
            sonar_error=None,
            semgrep_error=None,
            report=SimpleNamespace(findings=[_finding()]),
            both_failed=False,
        )

    monkeypatch.setattr(rp, "run_static_analysis", fake_static)
    pipeline.result = _Result(dict(_ENRICHED_PAYLOAD))

    chain = await worker_chain(db, user)
    result = await _run_job(db, chain.review)
    assert result["success"] is True
    assert result["comments_count"] == 4

    rows = (
        (
            await db.execute(
                select(ReviewComment).where(ReviewComment.review_id == chain.review.id)
            )
        )
        .scalars()
        .all()
    )
    by_body = {r.body: r for r in rows}
    assert len(by_body) == 4

    enriched = by_body["SQL injection risk"]
    assert enriched.tool == "sonarqube"
    assert enriched.rule_id == "java:S2077"
    assert list(enriched.cwe) == ["CWE-89"]
    assert (enriched.line_start, enriched.line_end) == (10, 12)
    assert enriched.snippet == "10: query(userInput)"
    assert list(enriched.also_detected_by) == ["semgrep"]
    assert enriched.line_number == 11  # the anchor stays the comment's line

    for body in ("Far away", "Different domain", "Other file"):
        unmatched = by_body[body]
        assert unmatched.tool is None, body
        assert unmatched.rule_id is None, body
        assert unmatched.cwe is None, body
        assert unmatched.snippet is None, body
        assert unmatched.also_detected_by is None, body


# --- GET /reviews/{id}: enrichment fields + viewer_role ----------------------


def _auth(keycloak_id: str, roles: tuple[str, ...] = ("DEVELOPER",)) -> dict:
    return staged_auth(keycloak_id, roles)


async def test_review_detail_exposes_enrichment_and_viewer_role(client, db):
    dev = await _make_user(db, "kc-dev-a")
    stage = await staged_chain(
        db, installation_id=777101, owner="owner-a", org_name="org-a", number=1
    )
    db.add(OrgMember(org_id=stage.org.id, user_id=dev.id, role="DEVELOPER"))

    comment = stage.review.comments[0]
    comment.tool = "sonarqube"
    comment.rule_id = "java:S2077"
    comment.cwe = ["CWE-89"]
    comment.line_start = 8
    comment.line_end = 12
    comment.snippet = "8: query(userInput)"
    comment.also_detected_by = ["semgrep"]
    await db.commit()

    resp = await client.get(f"{_REVIEWS}/{stage.review.id}", headers=_auth("kc-dev-a"))
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["viewer_role"] == "DEVELOPER"

    enriched = next(c for c in payload["comments"] if c["id"] == str(comment.id))
    assert enriched["tool"] == "sonarqube"
    assert enriched["rule_id"] == "java:S2077"
    assert enriched["cwe"] == ["CWE-89"]
    assert (enriched["line_start"], enriched["line_end"]) == (8, 12)
    assert enriched["snippet"] == "8: query(userInput)"
    assert enriched["also_detected_by"] == ["semgrep"]

    # The untouched comment degrades gracefully: every enrichment NULL.
    plain = next(c for c in payload["comments"] if c["id"] != str(comment.id))
    assert plain["tool"] is None
    assert plain["rule_id"] is None
    assert plain["cwe"] is None
    assert plain["line_start"] is None
    assert plain["line_end"] is None
    assert plain["snippet"] is None
    assert plain["also_detected_by"] is None


async def test_review_detail_viewer_role_platform_admin_bypass(client, db):
    await _make_user(db, "kc-pa", role="PLATFORM_ADMIN")  # no membership row
    stage = await staged_chain(
        db, installation_id=777102, owner="owner-b", org_name="org-b", number=2
    )

    resp = await client.get(
        f"{_REVIEWS}/{stage.review.id}",
        headers=staged_auth("kc-pa", roles=("PLATFORM_ADMIN",)),
    )
    assert resp.status_code == 200
    assert resp.json()["viewer_role"] == "PLATFORM_ADMIN"

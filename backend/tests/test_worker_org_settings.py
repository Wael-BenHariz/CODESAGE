"""Worker consumption of org settings (plan Step 4).

``process_review_job`` is exercised end-to-end with every external seam
stubbed at the module boundary (GitHub, static analysis, LLM, posting) so
each effective setting can be observed changing exactly one downstream
behaviour: trigger gate, diff cap, scanner flags, agent seams, model
precedence, min-severity gate, posting mode, and the per-org slot
semaphore. The resolver (``resolve_org_settings``) is mocked per test —
the merge chain itself is covered by ``test_org_settings``.
"""

import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

import app.services.review_orchestrator as ro
from app.db.models import (
    GitHubInstallation,
    Org,
    PullRequest,
    Repository,
    Review,
    ReviewComment,
)
from app.redis import get_redis
from app.services import static_analysis
from app.services.agents import AgentResult
from app.services.agents.schemas import ReviewContext
from app.services.agents.specialist_agents import format_findings
from app.services.llm_client import BaseLLMClient
from app.services.normalizers.schema import NormalizedFinding
from app.services.org_settings import merge_settings
from app.services.review_orchestrator import ReviewOrchestrator
from app.workers import review_processor as rp

_INSTALLATION_ID = 987654
_TRUNCATION_NOTE = (
    "\n[diff truncated for LLM context limit — " "review the visible portion only]"
)


# --- unit seams --------------------------------------------------------------


def test_cap_diff_applies_note_only_over_limit():
    short = "x" * 10
    assert rp._cap_diff(short, 10) == short
    capped = rp._cap_diff("y" * 100, 40)
    assert capped == "y" * 40 + _TRUNCATION_NOTE


def test_effective_model_precedence():
    # per-user -> org ai_model -> system default (None)
    assert rp._effective_model("user-model", "org-model") == "user-model"
    assert rp._effective_model(None, "org-model") == "org-model"
    assert rp._effective_model(None, None) is None


@pytest.mark.parametrize(
    ("comments", "threshold", "expected"),
    [
        # Default floor: always posts (byte-identical auto path).
        ([], "info", True),
        ([{"severity": "info"}], "info", True),
        # Threshold above the floor needs a finding that reaches it.
        ([], "low", False),
        ([{"severity": "info"}], "low", False),
        ([{"severity": "suggestion"}], "low", True),  # suggestion -> low
        ([{"severity": "warning"}], "medium", True),  # warning -> medium
        ([{"severity": "warning"}], "high", False),
        ([{"severity": "error"}], "high", True),  # error -> high
        ([{"severity": "error"}], "critical", False),
        # Unknown severity maps to the floor, never silently promoted.
        ([{"severity": "weird"}], "low", False),
        ([{"severity": "weird"}], "info", True),
    ],
)
def test_meets_min_severity_mapping(comments, threshold, expected):
    assert rp._meets_min_severity(comments, threshold) is expected


def test_format_findings_honors_limit_param():
    findings = [
        NormalizedFinding(
            tool="sonarqube", rule_id="R_HIGH", message="h", severity="high"
        ),
        NormalizedFinding(
            tool="sonarqube", rule_id="R_MEDIUM", message="m", severity="medium"
        ),
        NormalizedFinding(
            tool="sonarqube", rule_id="R_LOW", message="l", severity="low"
        ),
    ]
    capped = format_findings(findings, limit=2)
    assert "R_HIGH" in capped and "R_MEDIUM" in capped
    assert "R_LOW" not in capped
    assert "1 lower-severity findings omitted" in capped
    # Default limit unchanged (module constant = 15).
    assert "R_LOW" in format_findings(findings)


# --- static analysis org flags ----------------------------------------------


@pytest.fixture
def scanner_calls(monkeypatch):
    """Recording stubs at the static_analysis module boundary."""
    calls = SimpleNamespace(sonar=0, semgrep=0)

    async def fake_sonar_scan(**kwargs):
        calls.sonar += 1
        return {}

    class StubSemgrep:
        async def async_scan(self, archive, **kwargs):
            calls.semgrep += 1
            return {"version": "1.0", "results": []}

    monkeypatch.setattr(static_analysis.sonarqube_service, "scan", fake_sonar_scan)
    monkeypatch.setattr(static_analysis, "SemgrepClient", StubSemgrep)
    return calls


async def test_scanner_flags_disabled_skip_both_tools(scanner_calls):
    result = await static_analysis.run_static_analysis(
        review_id="r-1",
        project_key="codesage-review-deadbeef",
        files=[{"filename": "a.py", "content": "x = 1\n"}],
        language="python",
        sonar_enabled=False,
        semgrep_enabled=False,
    )
    # Disabled != broken: never called, never failed, no note.
    assert scanner_calls.sonar == 0 and scanner_calls.semgrep == 0
    assert result.report.tools_run == []
    assert result.report.tools_failed == []
    assert result.sonar_error is None and result.semgrep_error is None
    assert result.report.findings == []


async def test_scanner_sonar_only_when_semgrep_disabled(scanner_calls):
    result = await static_analysis.run_static_analysis(
        review_id="r-1",
        project_key="codesage-review-deadbeef",
        files=[{"filename": "a.py", "content": "x = 1\n"}],
        language="python",
        sonar_enabled=True,
        semgrep_enabled=False,
    )
    assert scanner_calls.sonar == 1 and scanner_calls.semgrep == 0
    assert result.report.tools_run == ["sonarqube"]
    assert result.report.tools_failed == []


# --- orchestrator: enabled_agents -------------------------------------------


def _stub_agent_class(domain: str, calls: list[str]):
    class _Stub:
        AGENT_NAME = domain

        def __init__(self, client):
            pass

        async def run(self, context):
            calls.append(domain)
            return AgentResult(agent=domain, confidence=1.0, comments=[])

    return _Stub


@pytest.fixture
def agent_calls(monkeypatch):
    calls: list[str] = []
    for attr, domain in (
        ("SecurityAgent", "security"),
        ("ComplexityAgent", "complexity"),
        ("PerformanceAgent", "performance"),
        ("StyleAgent", "style"),
        ("TestCoverageAgent", "test_coverage"),
    ):
        monkeypatch.setattr(ro, attr, _stub_agent_class(domain, calls))
    return calls


async def test_enabled_agents_filters_specialist_list(agent_calls):
    llm = _RecordingLLM()
    context = ReviewContext(pr_title="t", diff="", enabled_agents=["security", "style"])
    result = await ReviewOrchestrator(llm).run(context)

    assert set(agent_calls) == {"security", "style"}
    assert len(agent_calls) == 2
    # The orchestrator summary always runs.
    assert any("You are synthesizing a GitHub PR code review" in p for p in llm.prompts)
    assert result.summary


async def test_enabled_agents_none_runs_all_specialists(agent_calls):
    llm = _RecordingLLM()
    await ReviewOrchestrator(llm).run(ReviewContext(pr_title="t", diff=""))
    assert set(agent_calls) == {
        "security",
        "complexity",
        "performance",
        "style",
        "test_coverage",
    }


# --- process_review_job harness ---------------------------------------------


class _Result:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self, exclude_none: bool = False):
        if exclude_none:
            return {k: v for k, v in self.payload.items() if v is not None}
        return dict(self.payload)


_DEFAULT_PAYLOAD = {
    "summary": "## Review\nLooks good.",
    "overall_severity": "info",
    "comments": [
        {
            "file_path": "a.py",
            "line_number": 1,
            "severity": "warning",
            "category": "general",
            "body": "A warning.",
        }
    ],
}


class _RecordingLLM(BaseLLMClient):
    """Minimal client: records prompts, answers with canned JSON."""

    def __init__(self):
        super().__init__(api_key="test-key", model="fake-model")
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return self.model

    async def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        if "You are synthesizing a GitHub PR code review" in prompt:
            return json.dumps(
                {"summary": "Synthesized summary.", "overall_severity": "info"}
            )
        return json.dumps({"confidence": 0.5, "comments": []})


@pytest.fixture
def pipeline(monkeypatch):
    """Stub every external seam of process_review_job; recording state."""
    state = SimpleNamespace(
        contexts=[],
        posts=[],
        tokens=0,
        static_calls=[],
        llm_kwargs=[],
        resolved_org_ids=[],
        persists=0,
        result=_Result(dict(_DEFAULT_PAYLOAD)),
        on_run=None,
    )

    class FakeOrchestrator:
        def __init__(self, client=None):
            self.client = client

        async def run(self, context):
            state.contexts.append(context)
            if state.on_run is not None:
                await state.on_run(context)
            return state.result

    async def fake_token(installation_id):
        state.tokens += 1
        return "tok"

    async def fake_get_files(*args, **kwargs):
        return [
            {
                "filename": "a.py",
                "status": "modified",
                "additions": 1,
                "deletions": 1,
                "patch": "@@ -1 +1 @@\n-print(1)\n+print(2)",
            }
        ]

    async def fake_fetch_file_content(**kwargs):
        return "print(2)\n"

    async def fake_static_analysis(**kwargs):
        state.static_calls.append(kwargs)
        return SimpleNamespace(
            sonar_error=None,
            semgrep_error=None,
            report=SimpleNamespace(findings=[]),
            both_failed=False,
        )

    async def fake_persist(db, review_id, report):
        state.persists += 1

    def fake_resolve_llm_client(**kwargs):
        state.llm_kwargs.append(kwargs)
        return SimpleNamespace(model_name="fake-model")

    async def fake_post_pr_review(**kwargs):
        state.posts.append(kwargs)
        return 999

    async def fake_resolve(db, org_id):
        state.resolved_org_ids.append(org_id)
        return merge_settings(None, None)

    monkeypatch.setattr(rp, "get_installation_token", fake_token)
    monkeypatch.setattr(rp.github_service, "get_pull_request_files", fake_get_files)
    monkeypatch.setattr(rp, "fetch_file_content", fake_fetch_file_content)
    monkeypatch.setattr(rp, "run_static_analysis", fake_static_analysis)
    monkeypatch.setattr(rp, "persist_scan_report", fake_persist)
    monkeypatch.setattr(rp, "resolve_llm_client", fake_resolve_llm_client)
    monkeypatch.setattr(rp, "ReviewOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(rp, "post_pr_review", fake_post_pr_review)
    monkeypatch.setattr(rp, "resolve_org_settings", fake_resolve)
    return state


def _use_settings(monkeypatch, state, **overrides):
    """Replace the resolver with one serving the given effective settings."""
    effective = replace(merge_settings(None, None), **overrides)

    async def fake_resolve(db, org_id):
        state.resolved_org_ids.append(org_id)
        return effective

    monkeypatch.setattr(rp, "resolve_org_settings", fake_resolve)


async def _make_chain(db, user, *, with_org=True):
    """installation -> org? -> repo -> PR -> pending review."""
    installation = GitHubInstallation(
        app_id=1,
        installation_id=_INSTALLATION_ID,
        account_id=900_001,
        account_login="test-owner",
        account_type="User",
    )
    db.add(installation)
    await db.flush()

    org = None
    if with_org:
        org = Org(
            name="test-owner",
            account_type="User",
            installation_id=_INSTALLATION_ID,
        )
        db.add(org)
        await db.flush()

    repository = Repository(
        installation_id=installation.id,
        github_repo_id=111,
        name="demo",
        full_name="test-owner/demo",
    )
    db.add(repository)
    await db.flush()

    pull_request = PullRequest(
        repository_id=repository.id,
        github_pr_id=222,
        number=7,
        title="Add feature",
        author_login="test-owner",
        base_branch="main",
        head_branch="feature",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    db.add(pull_request)
    await db.flush()

    review = Review(
        pull_request_id=pull_request.id,
        user_id=user.id,
        status="pending",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return SimpleNamespace(
        installation=installation,
        org=org,
        repository=repository,
        pr=pull_request,
        review=review,
    )


async def _run_job(db, review, *, trigger_key_present=False, trigger=None):
    job = {"review_id": str(review.id)}
    if trigger_key_present:
        job["trigger"] = trigger
    return await rp.process_review_job(job, db)


def _slot_key(org_id) -> str:
    return rp.ORG_SLOT_KEY.format(org_id=org_id)


# --- auto path (default settings) -------------------------------------------


async def test_auto_path_unchanged(pipeline, db, user):
    """Defaults: one GitHub post of the summary, completed, slot freed."""
    chain = await _make_chain(db, user)
    redis = get_redis()
    seen = {}

    async def hook(_context):
        seen["slot_count"] = await redis.get(_slot_key(chain.org.id))

    pipeline.on_run = hook

    result = await _run_job(db, chain.review)

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["github_review_id"] == 999
    assert result["comments_count"] == 1

    assert len(pipeline.posts) == 1
    assert pipeline.posts[0]["body"] == "## Review\nLooks good."
    assert pipeline.posts[0]["full_name"] == "test-owner/demo"
    assert pipeline.posts[0]["pr_number"] == 7
    assert pipeline.posts[0]["commit_sha"] == "b" * 40

    # Chain join reached the org and the slot was held during the job…
    assert pipeline.resolved_org_ids == [chain.org.id]
    assert seen["slot_count"] == "1"
    # …and released afterwards (key cleaned up).
    assert not await redis.exists(_slot_key(chain.org.id))

    await db.refresh(chain.review)
    assert chain.review.status == "completed"
    assert chain.review.github_review_id == 999
    assert chain.review.error_message is None
    assert chain.review.gemini_model == "fake-model"

    comments = (
        await db.execute(
            select(func.count())
            .select_from(ReviewComment)
            .where(ReviewComment.review_id == chain.review.id)
        )
    ).scalar_one()
    assert comments == 1


async def test_without_org_runs_unlimited(pipeline, db, user):
    """No org row -> no per-org slot, global defaults still apply."""
    chain = await _make_chain(db, user, with_org=False)
    redis = get_redis()
    seen = {}

    async def hook(_context):
        seen["slot_keys"] = await redis.keys("codesage:org:*")

    pipeline.on_run = hook

    result = await _run_job(db, chain.review)

    assert result["success"] is True
    assert pipeline.resolved_org_ids == [None]
    assert seen["slot_keys"] == []  # no slot was ever taken
    assert len(pipeline.posts) == 1
    await db.refresh(chain.review)
    assert chain.review.status == "completed"


# --- trigger gate ------------------------------------------------------------


async def test_trigger_disabled_completes_with_note(pipeline, monkeypatch, db, user):
    """pull_request disabled -> completed + note; no token, no slot, no post."""
    _use_settings(monkeypatch, pipeline, review_triggers=["manual"])
    chain = await _make_chain(db, user)

    # No trigger key: defaults to pull_request (in-flight job compat).
    result = await _run_job(db, chain.review)

    assert result == {
        "success": True,
        "review_id": str(chain.review.id),
        "skipped": "trigger disabled",
    }
    assert pipeline.tokens == 0
    assert pipeline.posts == []
    assert not await get_redis().exists(_slot_key(chain.org.id))

    await db.refresh(chain.review)
    assert chain.review.status == "completed"  # not "failed"
    assert chain.review.error_message is not None
    assert chain.review.error_message.startswith(
        "Review skipped: trigger 'pull_request' disabled"
    )
    assert chain.review.completed_at is not None
    assert chain.review.github_review_id is None


async def test_trigger_manual_allowed_when_enabled(pipeline, monkeypatch, db, user):
    """review_triggers=['manual'] lets an explicit manual job through."""
    _use_settings(monkeypatch, pipeline, review_triggers=["manual"])
    chain = await _make_chain(db, user)

    result = await _run_job(
        db, chain.review, trigger_key_present=True, trigger="manual"
    )

    assert result["success"] is True
    assert len(pipeline.posts) == 1
    await db.refresh(chain.review)
    assert chain.review.status == "completed"


# --- posting mode: staged -----------------------------------------------------


async def test_staged_mode_never_posts(pipeline, monkeypatch, db, user):
    """posting_mode='staged' -> ready_to_post, zero GitHub calls."""
    _use_settings(monkeypatch, pipeline, posting_mode="staged")
    chain = await _make_chain(db, user)

    result = await _run_job(db, chain.review)

    assert pipeline.posts == []
    assert result["github_review_id"] is None
    assert result["status"] == "ready_to_post"

    await db.refresh(chain.review)
    assert chain.review.status == "ready_to_post"
    assert chain.review.github_review_id is None
    assert chain.review.summary == "## Review\nLooks good."
    assert chain.review.error_message is None  # staged is not a note-worthy state
    assert chain.review.completed_at is not None

    # Comments still persisted for the panel / staged findings section.
    comments = (
        await db.execute(
            select(func.count())
            .select_from(ReviewComment)
            .where(ReviewComment.review_id == chain.review.id)
        )
    ).scalar_one()
    assert comments == 1


# --- min_severity_to_post (auto mode) ----------------------------------------


async def test_min_severity_not_met_skips_post(pipeline, monkeypatch, db, user):
    """Threshold above every finding -> no GitHub post, review completes."""
    _use_settings(monkeypatch, pipeline, min_severity_to_post="high")
    chain = await _make_chain(db, user)

    result = await _run_job(
        db, chain.review
    )  # payload comment severity: warning->medium

    assert pipeline.posts == []
    assert result["github_review_id"] is None
    await db.refresh(chain.review)
    assert chain.review.status == "completed"
    assert chain.review.error_message is not None
    assert "min_severity_to_post=high" in chain.review.error_message
    # Findings are still stored regardless of the post gate.
    comments = (
        await db.execute(
            select(func.count())
            .select_from(ReviewComment)
            .where(ReviewComment.review_id == chain.review.id)
        )
    ).scalar_one()
    assert comments == 1


async def test_min_severity_met_posts(pipeline, monkeypatch, db, user):
    """A finding at the threshold (error -> high) lets the post through."""
    _use_settings(monkeypatch, pipeline, min_severity_to_post="high")
    pipeline.result = _Result(
        {
            "summary": "S",
            "overall_severity": "info",
            "comments": [
                {
                    "file_path": "a.py",
                    "line_number": 2,
                    "severity": "error",
                    "category": "bug",
                    "body": "Broken.",
                }
            ],
        }
    )
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    assert len(pipeline.posts) == 1
    await db.refresh(chain.review)
    assert chain.review.status == "completed"
    assert chain.review.error_message is None


async def test_default_info_posts_even_with_zero_comments(pipeline, db, user):
    """Default threshold keeps the auto path byte-identical (empty posts)."""
    pipeline.result = _Result(
        {"summary": "Nothing to flag.", "overall_severity": "info", "comments": []}
    )
    chain = await _make_chain(db, user)

    result = await _run_job(db, chain.review)

    assert len(pipeline.posts) == 1
    assert pipeline.posts[0]["body"] == "Nothing to flag."
    assert result["comments_count"] == 0
    await db.refresh(chain.review)
    assert chain.review.status == "completed"
    assert chain.review.error_message is None


# --- effective values change the right seam ----------------------------------


async def test_diff_char_cap_flows_to_context(pipeline, monkeypatch, db, user):
    _use_settings(monkeypatch, pipeline, diff_char_cap=40)
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    context = pipeline.contexts[0]
    assert context.diff.endswith(_TRUNCATION_NOTE)
    assert len(context.diff) == 40 + len(_TRUNCATION_NOTE)
    assert context.diff.startswith("\n" + "=" * 10)


async def test_agent_seams_flow_to_context(pipeline, monkeypatch, db, user):
    _use_settings(
        monkeypatch,
        pipeline,
        max_findings_per_agent=3,
        enabled_agents=["security"],
    )
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    context = pipeline.contexts[0]
    assert context.max_findings_per_agent == 3
    assert context.enabled_agents == ["security"]


async def test_scanner_flags_flow_to_static_analysis(pipeline, monkeypatch, db, user):
    _use_settings(monkeypatch, pipeline, sonarqube_enabled=False, semgrep_enabled=False)
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    assert len(pipeline.static_calls) == 1
    assert pipeline.static_calls[0]["sonar_enabled"] is False
    assert pipeline.static_calls[0]["semgrep_enabled"] is False


async def test_org_ai_model_applies_when_user_has_none(pipeline, monkeypatch, db, user):
    _use_settings(monkeypatch, pipeline, ai_model="org-org-model")
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    assert pipeline.llm_kwargs[0]["model"] == "org-org-model"


async def test_user_model_beats_org_ai_model(pipeline, monkeypatch, db, user):
    _use_settings(monkeypatch, pipeline, ai_model="org-org-model")
    # The worker resolves the LLM owner via github_installation_id.
    user.github_installation_id = _INSTALLATION_ID
    user.llm_model = "user-model"
    await db.commit()
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    assert pipeline.llm_kwargs[0]["model"] == "user-model"


async def test_no_model_falls_back_to_system_default(pipeline, db, user):
    chain = await _make_chain(db, user)

    await _run_job(db, chain.review)

    assert pipeline.llm_kwargs[0]["model"] is None


# --- per-org concurrency slot -------------------------------------------------


async def test_org_slot_acquire_refuse_release():
    org_id = uuid.uuid4()
    key = _slot_key(org_id)
    redis = get_redis()

    assert await rp._acquire_org_slot(org_id, 1, max_wait_seconds=0) is True
    assert int(await redis.get(key)) == 1
    assert await redis.ttl(key) > 0  # crash safety TTL

    # Over the limit: refused, the attempt is given back (INCR -> DECR).
    assert await rp._acquire_org_slot(org_id, 1, max_wait_seconds=0) is False
    assert int(await redis.get(key)) == 1

    await rp._release_org_slot(org_id)
    assert not await redis.exists(key)

    # Slot available again after release.
    assert await rp._acquire_org_slot(org_id, 1, max_wait_seconds=0) is True
    await rp._release_org_slot(org_id)
    assert not await redis.exists(key)


async def test_org_slot_unavailable_client_proceeds_without_slot():
    class BrokenRedis:
        async def incr(self, key):
            raise RuntimeError("redis down")

    # Availability over strict enforcement: no exception, no slot.
    assert await rp._acquire_org_slot(uuid.uuid4(), 5, client=BrokenRedis()) is False


async def test_org_slot_release_never_raises():
    class BrokenRedis:
        async def decr(self, key):
            raise RuntimeError("redis down")

    # Must swallow the failure (called from finally).
    assert await rp._release_org_slot(uuid.uuid4(), client=BrokenRedis()) is None


async def test_slot_released_on_pipeline_failure(pipeline, monkeypatch, db, user):
    """Exception after acquire -> review failed AND slot given back."""
    chain = await _make_chain(db, user)
    key = _slot_key(chain.org.id)

    async def broken_token(installation_id):
        raise RuntimeError("token boom")

    monkeypatch.setattr(rp, "get_installation_token", broken_token)

    result = await _run_job(db, chain.review)

    assert result["success"] is False
    assert result["error"] == "token boom"
    assert not await get_redis().exists(key)  # finally released

    await db.refresh(chain.review)
    assert chain.review.status == "failed"
    assert chain.review.error_message == "token boom"

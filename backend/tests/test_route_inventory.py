"""Route inventory regression gate + API-docs exposure.

Every route must carry an auth dependency (``get_current_user`` or a role
guard) unless it is explicitly allow-listed below as reachable without a
token. Adding an endpoint without auth — or removing one from a guard —
fails these tests.
"""

from app.config import Settings, settings
from app.main import app
from app.security.dependencies import get_current_user
from app.security.roles import require_developer, require_super_admin

API = settings.API_V1_PREFIX

# Dependency functions that make a route authenticated. Identity comparison
# (``dependant.call is <fn>``) — require_* are single closures created once
# at import, so this is stable.
_AUTH_CALLS = {get_current_user, require_developer, require_super_admin}

# The complete set of (METHOD, path) pairs reachable WITHOUT an auth
# dependency. Every entry needs a documented reason; anything else that
# lacks a guard fails test_no_unguarded_routes_outside_allowlist.
_UNAUTHENTICATED_OK: set[tuple[str, str]] = {
    ("GET", "/"),  # name/version splash page, no data
    ("GET", f"{API}/health"),  # orchestrator liveness probe
    ("GET", f"{API}/health/ready"),
    ("GET", f"{API}/health/live"),
    # Signed with GITHUB_WEBHOOK_SECRET (HMAC verified in-handler), not JWT.
    ("POST", f"{API}/webhooks/github"),
    # SPA bootstrap before login exists; returns public client config only.
    ("GET", f"{API}/auth/keycloak/config"),
    # Redirect sink: validates a state JWT (STATE_TOKEN_SECRET) and
    # redirects to the frontend — never returns data to the caller.
    ("GET", f"{API}/auth/github/app/callback"),
    # Validates its Bearer token in the handler itself (401 without a
    # valid one) — test_auth_logout.py pins that; no get_current_user
    # dependency exists for the walker to see.
    ("POST", f"{API}/auth/logout"),
}
# Docs routes exist only when ENABLE_API_DOCS=true — public by explicit
# opt-in (they are deliberately absent under the test environment).
if app.docs_url:
    _UNAUTHENTICATED_OK |= {
        ("GET", app.docs_url),
        ("GET", app.redoc_url),
        ("GET", app.openapi_url),
    }


def _iter_route_contexts(routes=None):
    """Yield effective route contexts (full path, methods, dependant).

    fastapi 0.141 no longer flattens included routers into ``app.routes``:
    each ``include_router`` call appends an ``_IncludedRouter`` that is
    resolved lazily through ``effective_candidates()`` — the same machinery
    request matching uses, which also merges include-level dependencies and
    computes the prefixed path.
    """
    for route in app.routes if routes is None else routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            items = list(candidates())
            low_priority = getattr(route, "effective_low_priority_routes", None)
            if callable(low_priority):
                items.extend(low_priority())
            yield from _iter_route_contexts(items)
        else:
            yield route


def _dependency_calls(dependant) -> set:
    """All callables in a FastAPI dependency tree (recursive)."""
    calls = {dep.call for dep in dependant.dependencies}
    for dep in dependant.dependencies:
        calls |= _dependency_calls(dep)
    return calls


def _route_auth_calls(context) -> set:
    """Auth-relevant callables for one effective route context.

    ``_EffectiveRouteContext.dependant`` carries the merged dependency tree
    (route signature + include-level dependencies); the plain ``APIRoute``
    fallback (the root ``/``) exposes ``dependant`` directly.
    """
    calls: set = set()
    dependant = getattr(context, "dependant", None)
    if dependant is not None:
        calls |= _dependency_calls(dependant)
    original = getattr(context, "original_route", None)
    if original is not None and getattr(original, "dependant", None) is not None:
        calls |= _dependency_calls(original.dependant)
    return calls


def _unguarded_routes() -> set[tuple[str, str]]:
    """(METHOD, path) for every route with no auth dependency in its tree."""
    unguarded: set[tuple[str, str]] = set()
    for context in _iter_route_contexts():
        if _route_auth_calls(context) & _AUTH_CALLS:
            continue
        for method in (context.methods or set()) - {"HEAD", "OPTIONS"}:
            unguarded.add((method, context.path))
    return unguarded


def test_no_unguarded_routes_outside_allowlist():
    """Nothing unauthenticated beyond the documented allow-list."""
    offenders = sorted(_unguarded_routes() - _UNAUTHENTICATED_OK)
    assert not offenders, (
        "Routes reachable with no auth dependency — add Depends(get_current_user)"
        " or a require_* guard, or (if genuinely public) allow-list them in "
        "_UNAUTHENTICATED_OK with a reason:\n  " + "\n  ".join(offenders)
    )


def test_allowlist_matches_reality():
    """Allow-list entries must exist AND still lack a guard (no stale entries)."""
    stale = sorted(_UNAUTHENTICATED_OK - _unguarded_routes())
    assert not stale, (
        "Allow-list entries whose route no longer exists or now requires auth "
        "(remove them from _UNAUTHENTICATED_OK): "
        + ", ".join(f"{m} {p}" for m, p in stale)
    )


# --- API docs exposure (ENABLE_API_DOCS) ------------------------------------


def test_docs_flag_defaults_to_false():
    """The setting itself defaults to off, whatever the environment says."""
    assert Settings.model_fields["ENABLE_API_DOCS"].default is False


def test_docs_routes_disabled_in_test_environment():
    """ENABLE_API_DOCS=false → docs/redoc/openapi URLs are None (no routes)."""
    assert settings.ENABLE_API_DOCS is False
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


async def test_docs_paths_return_404(client):
    """The docs endpoints are not registered at all when disabled."""
    for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
        resp = await client.get(path)
        assert resp.status_code == 404, f"{path} should not be served"

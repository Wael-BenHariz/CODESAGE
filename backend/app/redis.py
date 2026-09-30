"""
Shared Redis Client
Lazy, process-wide async Redis client for application state (OAuth state,
refresh-token rotation, access-token revocation).

Importing this module (and therefore ``app.main``) never opens a connection:
the client is created on the first ``get_redis()`` call. Key names are
namespaced ``codesage:*`` so they coexist with BullMQ's ``bull:*`` keys in the
same Redis database.
"""

import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Key namespaces (single source of truth for the codesage:* prefix).
OAUTH_STATE_KEY = "codesage:oauth:state:{state}"
REFRESH_JTIS_KEY = "codesage:auth:refresh:{user_id}"
REVOKED_AT_KEY = "codesage:auth:revoked:{user_id}"

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the shared Redis client, connecting lazily on first use."""
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def close_redis() -> None:
    """Close the shared client if one was opened (no-op otherwise)."""
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    finally:
        _client = None

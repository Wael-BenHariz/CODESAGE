"""Redis sliding-window rate limit for invitations (plan Step 11).

20 invitations per org per hour → 429. A sorted set per org: members are
monotonic ids scored by creation time; entries older than the window are
pruned on every check and the key self-expires after the window, so a
quiet org costs nothing.

Redis being down must never block inviting — the limit fails **open**
with a warning (availability over strictness for an admin-only action
that is itself guarded by ORG_ADMIN).
"""

import logging
import time
import uuid

from app.redis import get_redis

logger = logging.getLogger(__name__)

INVITE_LIMIT_PER_HOUR = 20
WINDOW_SECONDS = 3600

_KEY = "codesage:invites:{org_id}"


async def allow_invitation(org_id: str) -> bool:
    """True when one more invite is inside the org's hourly window.

    Consumes a slot when allowed; a rejected call consumes nothing.
    """
    key = _KEY.format(org_id=org_id)
    now = time.time()
    cutoff = now - WINDOW_SECONDS
    try:
        client = get_redis()
        # Prune the previous window, then read the live count.
        await client.zremrangebyscore(key, "-inf", cutoff)
        count = await client.zcard(key)
        if int(count) >= INVITE_LIMIT_PER_HOUR:
            return False
        await client.zadd(key, {uuid.uuid4().hex: now})
        await client.expire(key, WINDOW_SECONDS + 60)  # survive the full window
        return True
    except Exception:
        logger.warning(
            "invite_rate_limit_unavailable org_id=%s — allowing the invite",
            org_id,
            exc_info=True,
        )
        return True

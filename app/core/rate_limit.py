"""Fixed-window rate limiting on Redis (INCR + EXPIRE), exposed as FastAPI dependencies.

Each (scope, client, window) gets its own counter key:
    rl:{scope}:{identity}:{window_start}
INCR and EXPIRE run in one MULTI/EXEC, so the counter can never be left without a TTL.
Over the limit -> 429 with Retry-After = seconds until the window rolls over.

Trade-off: a fixed window allows up to 2x the limit in a burst straddling a window
boundary, in exchange for O(1) memory and a single round trip per request.

Fails open: if Redis is unreachable the request is allowed and a warning is logged.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.deps import CurrentUserId, RedisDep, SettingsDep
from app.core.errors import RateLimitedError
from app.core.security import hash_ip

logger = logging.getLogger(__name__)

RateLimitDependency = Callable[..., Awaitable[None]]


def _now() -> float:
    return time.time()


async def enforce(redis: Redis, scope: str, identity: str, limit: int, window: int) -> None:
    now = _now()
    window_start = int(now // window) * window
    key = f"rl:{scope}:{identity}:{window_start}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window)
            count, _ = await pipe.execute()
    except (RedisError, OSError):
        logger.warning("Rate limiter unavailable (Redis error); allowing request", exc_info=True)
        return

    if count > limit:
        raise RateLimitedError(retry_after=max(1, math.ceil(window_start + window - now)))


def limit_by_ip(scope: str, limit_setting: str) -> RateLimitDependency:
    """Limit per client IP (IP is HMAC-hashed before it goes into the Redis key)."""

    async def dependency(request: Request, settings: SettingsDep, redis: RedisDep) -> None:
        if not settings.rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        await enforce(
            redis,
            scope,
            f"ip:{hash_ip(ip, settings.ip_hash_secret)}",
            getattr(settings, limit_setting),
            settings.rate_limit_window_seconds,
        )

    return dependency


def limit_by_user(scope: str, limit_setting: str) -> RateLimitDependency:
    """Limit per authenticated user (runs after JWT auth, so 401 beats 429)."""

    async def dependency(user_id: CurrentUserId, settings: SettingsDep, redis: RedisDep) -> None:
        if not settings.rate_limit_enabled:
            return
        await enforce(
            redis,
            scope,
            f"user:{user_id}",
            getattr(settings, limit_setting),
            settings.rate_limit_window_seconds,
        )

    return dependency


auth_rate_limit = limit_by_ip("auth", "rate_limit_auth")
create_url_rate_limit = limit_by_user("create_url", "rate_limit_create_url")
redirect_rate_limit = limit_by_ip("redirect", "rate_limit_redirect")

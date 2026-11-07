"""Redis cache for the redirect hot path. Key: url:{code}.

Values:
  - '{"id": 1, "url": "https://..."}'  -> positive entry, TTL = url_cache_ttl_seconds
  - "__nf__"                           -> negative entry, TTL = not_found_cache_ttl_seconds

Every operation fails open: a Redis error is logged and treated as a cache miss, so a
Redis outage degrades redirects to Postgres instead of taking them down.
"""

import json
import logging
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings

logger = logging.getLogger(__name__)

NOT_FOUND_VALUE: Final = "__nf__"


@dataclass(frozen=True, slots=True)
class CachedUrl:
    id: int
    url: str


class _CachedNotFound:
    __slots__ = ()

    def __repr__(self) -> str:
        return "CACHED_NOT_FOUND"


CACHED_NOT_FOUND: Final = _CachedNotFound()
CacheEntry = CachedUrl | _CachedNotFound


def cache_key(code: str) -> str:
    return f"url:{code}"


class UrlCache:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._ttl = settings.url_cache_ttl_seconds
        self._not_found_ttl = settings.not_found_cache_ttl_seconds

    async def get(self, code: str) -> CacheEntry | None:
        """Positive entry, CACHED_NOT_FOUND, or None on a miss (or Redis error)."""
        try:
            raw = await self._redis.get(cache_key(code))
        except (RedisError, OSError):
            logger.warning("Redis GET failed for %s; falling back to DB", code, exc_info=True)
            return None
        if raw is None:
            return None
        if raw == NOT_FOUND_VALUE:
            return CACHED_NOT_FOUND
        try:
            data = json.loads(raw)
            return CachedUrl(id=int(data["id"]), url=str(data["url"]))
        except (ValueError, KeyError, TypeError):
            logger.warning("Corrupt cache entry for %s; ignoring", code)
            return None

    async def set_url(self, code: str, entry: CachedUrl) -> None:
        # NX: never overwrite an existing value, in particular the tombstone written by
        # invalidate(). Without it, a reader that loaded the row just before a delete
        # committed could re-cache the dead URL for a full TTL.
        value = json.dumps({"id": entry.id, "url": entry.url}, separators=(",", ":"))
        await self._safe_set(code, value, self._ttl, nx=True)

    async def set_not_found(self, code: str) -> None:
        await self._safe_set(code, NOT_FOUND_VALUE, self._not_found_ttl, nx=True)

    async def invalidate(self, code: str) -> None:
        """Called after a delete commits: overwrite with a short-lived tombstone (see set_url)."""
        await self._safe_set(code, NOT_FOUND_VALUE, self._not_found_ttl, nx=False)

    async def _safe_set(self, code: str, value: str, ttl: int, *, nx: bool) -> None:
        try:
            await self._redis.set(cache_key(code), value, ex=ttl, nx=nx)
        except (RedisError, OSError):
            logger.warning("Redis SET failed for %s", code, exc_info=True)

from redis.asyncio import Redis

from app.config import Settings


def create_redis(settings: Settings) -> Redis:
    # Short timeouts so a dead Redis degrades requests quickly (we fail open).
    client: Redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    return client

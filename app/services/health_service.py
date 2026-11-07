import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


async def check_database(session: AsyncSession) -> bool:
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), CHECK_TIMEOUT_SECONDS)
        return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


async def check_redis(redis: Redis) -> bool:
    try:
        return bool(await asyncio.wait_for(redis.ping(), CHECK_TIMEOUT_SECONDS))
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False

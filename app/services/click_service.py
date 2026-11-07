import logging
from dataclasses import dataclass
from typing import Self

from fastapi import Request
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.security import get_client_ip, hash_ip
from app.models import Click, Url
from app.models.click import MAX_REFERRER_LENGTH, MAX_USER_AGENT_LENGTH

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClickInfo:
    ip_hash: str
    user_agent: str | None
    referrer: str | None

    @classmethod
    def from_request(cls, request: Request, settings: Settings) -> Self:
        ip = get_client_ip(request, settings.client_ip_header)
        return cls(
            ip_hash=hash_ip(ip, settings.ip_hash_secret),
            user_agent=request.headers.get("user-agent", "")[:MAX_USER_AGENT_LENGTH] or None,
            referrer=request.headers.get("referer", "")[:MAX_REFERRER_LENGTH] or None,
        )


async def record_click(
    sessionmaker: async_sessionmaker[AsyncSession], url_id: int, info: ClickInfo
) -> None:
    """Runs as a BackgroundTask after the redirect response has been sent.

    Uses its own session (the request's session is already closed). The click row and
    the counter increment commit atomically, and the increment is done in SQL
    (click_count = click_count + 1) so concurrent clicks never lose updates.
    Failures are logged, never raised: analytics must not break redirects.
    """
    try:
        async with sessionmaker() as session, session.begin():
            await session.execute(
                insert(Click).values(
                    url_id=url_id,
                    ip_hash=info.ip_hash,
                    user_agent=info.user_agent,
                    referrer=info.referrer,
                )
            )
            await session.execute(
                update(Url).where(Url.id == url_id).values(click_count=Url.click_count + 1)
            )
    except Exception:
        logger.exception("Failed to record click for url_id=%s", url_id)

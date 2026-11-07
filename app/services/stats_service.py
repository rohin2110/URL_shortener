from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import Click
from app.schemas.stats import DailyClicks, ReferrerCount, UrlStats, UserAgentCount
from app.services.url_service import get_owned_url

STATS_DAYS = 30
TOP_N = 10


async def get_stats_for_owner(session: AsyncSession, owner_id: int, code: str) -> UrlStats:
    url = await get_owned_url(session, owner_id, code)  # 404 / 403
    assert url.short_code is not None

    return UrlStats(
        code=url.short_code,
        total_clicks=url.click_count,
        clicks_per_day=await _clicks_per_day(session, url.id),
        top_referrers=[
            ReferrerCount(referrer=value, clicks=n)
            for value, n in await _top_values(session, url.id, Click.referrer)
        ],
        top_user_agents=[
            UserAgentCount(user_agent=value, clicks=n)
            for value, n in await _top_values(session, url.id, Click.user_agent)
        ],
    )


async def _clicks_per_day(session: AsyncSession, url_id: int) -> list[DailyClicks]:
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=STATS_DAYS - 1)
    since = datetime.combine(first_day, time.min, tzinfo=UTC)

    # Range scan on ix_clicks_url_id_clicked_at; bucket by UTC calendar day.
    day = func.date(func.timezone("UTC", Click.clicked_at)).label("day")
    rows = await session.execute(
        select(day, func.count())
        .where(Click.url_id == url_id, Click.clicked_at >= since)
        .group_by(day)
    )
    counts: dict[date, int] = {row_day: n for row_day, n in rows.tuples()}

    days = (first_day + timedelta(days=i) for i in range(STATS_DAYS))
    return [DailyClicks(date=d, clicks=counts.get(d, 0)) for d in days]


async def _top_values(
    session: AsyncSession, url_id: int, column: InstrumentedAttribute[str | None]
) -> list[tuple[str, int]]:
    clicks = func.count().label("clicks")
    rows = await session.execute(
        select(column, clicks)
        .where(Click.url_id == url_id, column.is_not(None))
        .group_by(column)
        .order_by(desc(clicks), column)
        .limit(TOP_N)
    )
    return [(value, n) for value, n in rows.tuples() if value is not None]

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select, update

from app.models import Click, Url
from tests.helpers import auth_headers


async def setup_url(client: AsyncClient, email: str = "owner@example.com") -> tuple[dict, str]:
    headers = await auth_headers(client, email)
    resp = await client.post("/api/urls", json={"url": "https://example.com"}, headers=headers)
    return headers, resp.json()["code"]


async def add_clicks(client: AsyncClient, code: str, *clicked_at: datetime) -> None:
    """Insert historical clicks directly (the API can only create clicks 'now')."""
    async with client.app.state.sessionmaker() as session, session.begin():  # type: ignore[attr-defined]
        url_id = await session.scalar(select(Url.id).where(Url.short_code == code))
        for ts in clicked_at:
            await session.execute(
                insert(Click).values(url_id=url_id, clicked_at=ts, ip_hash="x" * 64)
            )
        await session.execute(
            update(Url).where(Url.id == url_id).values(click_count=Url.click_count + len(clicked_at))
        )


async def test_stats(client: AsyncClient) -> None:
    headers, code = await setup_url(client)
    visits = [
        ("https://google.com/", "Firefox"),
        ("https://google.com/", "Chrome"),
        ("https://news.example/", "Chrome"),
        (None, "Chrome"),  # direct visit: counted, but not a referrer
    ]
    for referrer, agent in visits:
        req_headers = {"User-Agent": agent} | ({"Referer": referrer} if referrer else {})
        assert (await client.get(f"/{code}", headers=req_headers)).status_code == 302

    now = datetime.now(UTC)
    await add_clicks(client, code, now - timedelta(days=5), now - timedelta(days=5))
    await add_clicks(client, code, now - timedelta(days=40))  # outside the 30-day window

    resp = await client.get(f"/api/urls/{code}/stats", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()

    assert stats["code"] == code
    assert stats["total_clicks"] == 7  # all-time

    per_day = stats["clicks_per_day"]
    today = now.date()
    assert len(per_day) == 30
    assert per_day[0]["date"] == (today - timedelta(days=29)).isoformat()
    assert per_day[-1] == {"date": today.isoformat(), "clicks": 4}
    by_day = {date.fromisoformat(d["date"]): d["clicks"] for d in per_day}
    assert by_day[today - timedelta(days=5)] == 2
    assert sum(by_day.values()) == 6  # the 40-day-old click is excluded

    assert stats["top_referrers"] == [
        {"referrer": "https://google.com/", "clicks": 2},
        {"referrer": "https://news.example/", "clicks": 1},
    ]
    assert stats["top_user_agents"] == [
        {"user_agent": "Chrome", "clicks": 3},
        {"user_agent": "Firefox", "clicks": 1},
    ]


async def test_stats_for_url_without_clicks(client: AsyncClient) -> None:
    headers, code = await setup_url(client)
    stats = (await client.get(f"/api/urls/{code}/stats", headers=headers)).json()
    assert stats["total_clicks"] == 0
    assert len(stats["clicks_per_day"]) == 30
    assert all(d["clicks"] == 0 for d in stats["clicks_per_day"])
    assert stats["top_referrers"] == [] and stats["top_user_agents"] == []


async def test_stats_of_someone_elses_url_is_403(client: AsyncClient) -> None:
    _, code = await setup_url(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    resp = await client.get(f"/api/urls/{code}/stats", headers=bob)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_stats_requires_auth(client: AsyncClient) -> None:
    _, code = await setup_url(client)
    assert (await client.get(f"/api/urls/{code}/stats")).status_code == 401


@pytest.mark.parametrize("deleted", [False, True])
async def test_stats_missing_or_deleted_is_404(client: AsyncClient, deleted: bool) -> None:
    headers, code = await setup_url(client)
    if deleted:
        await client.delete(f"/api/urls/{code}", headers=headers)
    else:
        code = "zzzz"
    assert (await client.get(f"/api/urls/{code}/stats", headers=headers)).status_code == 404

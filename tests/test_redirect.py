import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.security import hash_ip
from app.models import Click, Url
from app.services.cache_service import NOT_FOUND_VALUE, cache_key
from tests.conftest import ClientFactory
from tests.helpers import auth_headers

TARGET = "https://example.com/landing?utm=1"


async def make_url(client: AsyncClient, headers: dict | None = None) -> str:
    headers = headers or await auth_headers(client, "owner@example.com")
    resp = await client.post("/api/urls", json={"url": TARGET}, headers=headers)
    assert resp.status_code == 201
    return resp.json()["code"]


def redis(client: AsyncClient):  # noqa: ANN201
    return client.app.state.redis  # type: ignore[attr-defined]


async def test_cache_miss_hits_db_then_populates_cache(client: AsyncClient) -> None:
    code = await make_url(client)
    assert await redis(client).get(cache_key(code)) is None  # create doesn't warm the cache

    resp = await client.get(f"/{code}")
    assert resp.status_code == 302
    assert resp.headers["location"] == TARGET

    cached = json.loads(await redis(client).get(cache_key(code)))
    assert cached["url"] == TARGET
    ttl = await redis(client).ttl(cache_key(code))
    assert 86_400 - 5 < ttl <= 86_400


async def test_cache_hit_does_not_read_db(client: AsyncClient) -> None:
    code = await make_url(client)
    await client.get(f"/{code}")  # warm the cache

    # Change the row behind the cache's back: a cache hit must not see this.
    async with client.app.state.sessionmaker() as session, session.begin():  # type: ignore[attr-defined]
        await session.execute(
            update(Url).where(Url.short_code == code).values(original_url="https://changed.example")
        )

    resp = await client.get(f"/{code}")
    assert resp.status_code == 302
    assert resp.headers["location"] == TARGET


async def test_unknown_code_is_404_and_negatively_cached(client: AsyncClient) -> None:
    resp = await client.get("/zzzzzz")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"

    assert await redis(client).get(cache_key("zzzzzz")) == NOT_FOUND_VALUE
    assert 0 < await redis(client).ttl(cache_key("zzzzzz")) <= 60


@pytest.mark.parametrize("code", ["bad-code", "api", "static"])
async def test_invalid_or_reserved_code_is_404_without_caching(
    client: AsyncClient, code: str
) -> None:
    assert (await client.get(f"/{code}")).status_code == 404
    assert await redis(client).get(cache_key(code)) is None


async def test_real_routes_are_not_shadowed(client: AsyncClient) -> None:
    assert (await client.get("/health")).json()["status"] == "ok"
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/openapi.json")).status_code == 200
    index = await client.get("/")
    assert index.status_code == 200 and "<title>URL Shortener</title>" in index.text
    assert (await client.get("/static/index.html")).status_code == 200


async def test_delete_invalidates_cache(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    code = await make_url(client, headers)
    assert (await client.get(f"/{code}")).status_code == 302  # now cached

    assert (await client.delete(f"/api/urls/{code}", headers=headers)).status_code == 204
    assert await redis(client).get(cache_key(code)) == NOT_FOUND_VALUE
    assert (await client.get(f"/{code}")).status_code == 404


async def test_inactive_url_is_404(client: AsyncClient) -> None:
    code = await make_url(client)
    async with client.app.state.sessionmaker() as session, session.begin():  # type: ignore[attr-defined]
        await session.execute(update(Url).where(Url.short_code == code).values(is_active=False))
    assert (await client.get(f"/{code}")).status_code == 404


async def test_click_is_recorded_with_hashed_ip(client: AsyncClient) -> None:
    headers = await auth_headers(client, "owner@example.com")
    code = await make_url(client, headers)

    for _ in range(2):  # 1st = cache miss, 2nd = cache hit; both must be counted
        resp = await client.get(
            f"/{code}", headers={"User-Agent": "pytest-agent", "Referer": "https://ref.example/"}
        )
        assert resp.status_code == 302

    async with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        clicks = (await session.scalars(select(Click))).all()
    assert len(clicks) == 2
    click = clicks[0]
    settings = client.app.state.settings  # type: ignore[attr-defined]
    assert click.ip_hash == hash_ip("127.0.0.1", settings.ip_hash_secret)
    assert "127.0.0.1" not in click.ip_hash and len(click.ip_hash) == 64
    assert click.user_agent == "pytest-agent"
    assert click.referrer == "https://ref.example/"

    details = await client.get(f"/api/urls/{code}", headers=headers)
    assert details.json()["click_count"] == 2


async def test_redirect_fails_open_when_redis_is_down(client_factory: ClientFactory) -> None:
    async with client_factory(redis_url="redis://localhost:1/0") as client:
        headers = await auth_headers(client, "owner@example.com")
        code = await make_url(client, headers)

        resp = await client.get(f"/{code}")
        assert resp.status_code == 302 and resp.headers["location"] == TARGET
        assert (await client.get("/zzzz")).status_code == 404
        assert (await client.delete(f"/api/urls/{code}", headers=headers)).status_code == 204
        assert (await client.get(f"/{code}")).status_code == 404

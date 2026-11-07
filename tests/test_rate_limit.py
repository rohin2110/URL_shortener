import pytest
from httpx import AsyncClient, Response

from app.core import rate_limit
from tests.conftest import ClientFactory
from tests.helpers import DEFAULT_PASSWORD, auth_headers

WINDOW = 60


def assert_429(resp: Response) -> None:
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    retry_after = int(resp.headers["Retry-After"])
    assert 1 <= retry_after <= WINDOW


async def test_auth_endpoints_are_limited_per_ip(client_factory: ClientFactory) -> None:
    async with client_factory(rate_limit_enabled=True, rate_limit_auth=3) as client:
        creds = {"email": "a@example.com", "password": DEFAULT_PASSWORD}
        assert (await client.post("/api/auth/register", json=creds)).status_code == 201
        assert (await client.post("/api/auth/login", json=creds)).status_code == 200
        assert (await client.post("/api/auth/login", json=creds)).status_code == 200
        # register + login share the "auth" budget
        assert_429(await client.post("/api/auth/login", json=creds))
        assert_429(await client.post("/api/auth/register", json=creds))


async def test_create_url_is_limited_per_user(client_factory: ClientFactory) -> None:
    async with client_factory(
        rate_limit_enabled=True, rate_limit_create_url=2, rate_limit_auth=100
    ) as client:
        alice = await auth_headers(client, "alice@example.com")
        bob = await auth_headers(client, "bob@example.com")
        body = {"url": "https://example.com"}

        for _ in range(2):
            assert (await client.post("/api/urls", json=body, headers=alice)).status_code == 201
        assert_429(await client.post("/api/urls", json=body, headers=alice))

        # Same IP, different user: separate budget.
        assert (await client.post("/api/urls", json=body, headers=bob)).status_code == 201
        # Reads are not limited by the create budget.
        assert (await client.get("/api/urls", headers=alice)).status_code == 200


async def test_unauthenticated_create_is_401_not_429(client_factory: ClientFactory) -> None:
    async with client_factory(rate_limit_enabled=True, rate_limit_create_url=1) as client:
        for _ in range(3):
            resp = await client.post("/api/urls", json={"url": "https://example.com"})
            assert resp.status_code == 401


async def test_redirect_is_limited_per_ip(client_factory: ClientFactory) -> None:
    async with client_factory(rate_limit_enabled=True, rate_limit_redirect=3) as client:
        headers = await auth_headers(client, "a@example.com")
        code = (
            await client.post("/api/urls", json={"url": "https://example.com"}, headers=headers)
        ).json()["code"]

        for _ in range(3):
            assert (await client.get(f"/{code}")).status_code == 302
        assert_429(await client.get(f"/{code}"))
        assert_429(await client.get("/zzzz"))  # 404s count too (stops code enumeration)


async def test_window_resets(
    client_factory: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: clock[0])

    async with client_factory(rate_limit_enabled=True, rate_limit_redirect=1) as client:
        assert (await client.get("/zzzz")).status_code == 404
        resp = await client.get("/zzzz")
        assert_429(resp)
        assert resp.headers["Retry-After"] == str(WINDOW - int(clock[0] % WINDOW))

        clock[0] += WINDOW  # next window
        assert (await client.get("/zzzz")).status_code == 404


async def test_rate_limit_fails_open_when_redis_is_down(client_factory: ClientFactory) -> None:
    async with client_factory(
        rate_limit_enabled=True, rate_limit_auth=1, redis_url="redis://localhost:1/0"
    ) as client:
        creds = {"email": "a@example.com", "password": DEFAULT_PASSWORD}
        assert (await client.post("/api/auth/register", json=creds)).status_code == 201
        for _ in range(3):
            assert (await client.post("/api/auth/login", json=creds)).status_code == 200

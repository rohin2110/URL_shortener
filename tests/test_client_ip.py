from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_ip
from app.models import Click
from tests.conftest import ClientFactory
from tests.helpers import auth_headers


async def _redirect_and_get_ip_hash(client: AsyncClient, headers: dict[str, str]) -> str:
    auth = await auth_headers(client, "a@example.com")
    code = (await client.post("/api/urls", json={"url": "https://example.com"}, headers=auth)).json()["code"]
    assert (await client.get(f"/{code}", headers=headers)).status_code == 302
    async with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        return (await session.scalars(select(Click.ip_hash))).one()


async def test_trusted_header_is_used_when_configured(client_factory: ClientFactory) -> None:
    async with client_factory(client_ip_header="Fly-Client-IP") as client:
        ip_hash = await _redirect_and_get_ip_hash(client, {"Fly-Client-IP": "203.0.113.7"})
        secret = client.app.state.settings.ip_hash_secret  # type: ignore[attr-defined]
    assert ip_hash == hash_ip("203.0.113.7", secret)


async def test_header_is_ignored_when_not_configured(client: AsyncClient) -> None:
    # Without a trusted proxy, a client-sent header must not override the real peer IP.
    ip_hash = await _redirect_and_get_ip_hash(client, {"Fly-Client-IP": "203.0.113.7"})
    secret = client.app.state.settings.ip_hash_secret  # type: ignore[attr-defined]
    assert ip_hash == hash_ip("127.0.0.1", secret)


async def test_rate_limit_is_per_real_client_behind_proxy(client_factory: ClientFactory) -> None:
    async with client_factory(
        client_ip_header="Fly-Client-IP", rate_limit_enabled=True, rate_limit_redirect=1
    ) as client:
        # All requests arrive from the same peer (the proxy), but are different clients.
        assert (await client.get("/zzzz", headers={"Fly-Client-IP": "198.51.100.1"})).status_code == 404
        assert (await client.get("/zzzz", headers={"Fly-Client-IP": "198.51.100.2"})).status_code == 404
        assert (await client.get("/zzzz", headers={"Fly-Client-IP": "198.51.100.1"})).status_code == 429

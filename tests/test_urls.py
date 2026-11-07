import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import base62
from app.models import Url
from app.services import url_service
from tests.helpers import auth_headers

TARGET = "https://example.com/a/very/long/path?with=query#frag"


async def create(client: AsyncClient, headers: dict, url: str = TARGET) -> dict:
    resp = await client.post("/api/urls", json={"url": url}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def get_row(client: AsyncClient, code: str) -> Url | None:
    async with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        return await session.scalar(select(Url).where(Url.short_code == code))


# --- auth -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic dXNlcjpwYXNz"}],
)
async def test_url_endpoints_require_auth(client: AsyncClient, headers: dict) -> None:
    for method, path in [
        ("POST", "/api/urls"),
        ("GET", "/api/urls"),
        ("GET", "/api/urls/1"),
        ("DELETE", "/api/urls/1"),
    ]:
        resp = await client.request(method, path, json={"url": TARGET}, headers=headers)
        assert resp.status_code == 401, (method, path)
        assert resp.json()["error"]["code"] == "unauthorized"


# --- create -----------------------------------------------------------------------


async def test_create_short_url(client: AsyncClient) -> None:
    headers = await auth_headers(client, "a@example.com")
    body = await create(client, headers)

    assert body["original_url"] == TARGET
    assert body["short_url"] == f"http://test/{body['code']}"
    assert body["click_count"] == 0 and body["is_active"] is True

    row = await get_row(client, body["code"])
    assert row is not None
    assert body["code"] == base62.encode(row.id)  # code is base62(row id)


async def test_codes_follow_ids(client: AsyncClient) -> None:
    headers = await auth_headers(client, "a@example.com")
    codes = [(await create(client, headers))["code"] for _ in range(3)]
    assert [base62.decode(c) for c in codes] == [1, 2, 3]


async def test_reserved_codes_are_skipped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(url_service, "RESERVED_CODES", frozenset({"1", "2"}))
    headers = await auth_headers(client, "a@example.com")
    body = await create(client, headers)
    assert body["code"] == "3"
    assert await get_row(client, "1") is None and await get_row(client, "2") is None


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/file",
        "javascript:alert(1)",
        "mailto:a@example.com",
        "example.com",
        "http://",
        "https://exa mple.com",
        "https://example.com/\nfoo",
        "https://example.com/" + "a" * 2048,  # > 2048 chars
        "",
    ],
)
async def test_create_rejects_invalid_urls(client: AsyncClient, bad_url: str) -> None:
    headers = await auth_headers(client, "a@example.com")
    resp = await client.post("/api/urls", json={"url": bad_url}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_create_accepts_http_and_max_length(client: AsyncClient) -> None:
    headers = await auth_headers(client, "a@example.com")
    longest = "http://example.com/" + "a" * (2048 - len("http://example.com/"))
    assert len(longest) == 2048
    assert (await create(client, headers, longest))["original_url"] == longest


# --- list -------------------------------------------------------------------------


async def test_list_is_paginated_newest_first_and_scoped_to_owner(client: AsyncClient) -> None:
    alice = await auth_headers(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    codes = [(await create(client, alice, f"https://example.com/{i}"))["code"] for i in range(3)]
    await create(client, bob)

    page1 = (await client.get("/api/urls?limit=2", headers=alice)).json()
    assert page1["total"] == 3 and page1["limit"] == 2 and page1["offset"] == 0
    assert [u["code"] for u in page1["items"]] == [codes[2], codes[1]]

    page2 = (await client.get("/api/urls?limit=2&offset=2", headers=alice)).json()
    assert [u["code"] for u in page2["items"]] == [codes[0]]

    bob_page = (await client.get("/api/urls", headers=bob)).json()
    assert bob_page["total"] == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
async def test_list_rejects_bad_pagination(client: AsyncClient, query: str) -> None:
    headers = await auth_headers(client, "a@example.com")
    assert (await client.get(f"/api/urls?{query}", headers=headers)).status_code == 422


# --- details ----------------------------------------------------------------------


async def test_get_details(client: AsyncClient) -> None:
    headers = await auth_headers(client, "a@example.com")
    created = await create(client, headers)
    resp = await client.get(f"/api/urls/{created['code']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == created


async def test_get_details_of_someone_elses_url_is_403(client: AsyncClient) -> None:
    alice = await auth_headers(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    code = (await create(client, alice))["code"]
    resp = await client.get(f"/api/urls/{code}", headers=bob)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("code", ["zzzz", "bad-code"])
async def test_get_details_missing_is_404(client: AsyncClient, code: str) -> None:
    headers = await auth_headers(client, "a@example.com")
    resp = await client.get(f"/api/urls/{code}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- delete -----------------------------------------------------------------------


async def test_delete_soft_deletes(client: AsyncClient) -> None:
    headers = await auth_headers(client, "a@example.com")
    code = (await create(client, headers))["code"]

    resp = await client.delete(f"/api/urls/{code}", headers=headers)
    assert resp.status_code == 204 and resp.content == b""

    row = await get_row(client, code)
    assert row is not None and row.is_active is False  # row kept, just deactivated
    assert (await client.get(f"/api/urls/{code}", headers=headers)).status_code == 404
    assert (await client.get("/api/urls", headers=headers)).json()["total"] == 0
    assert (await client.delete(f"/api/urls/{code}", headers=headers)).status_code == 404


async def test_delete_someone_elses_url_is_403(client: AsyncClient) -> None:
    alice = await auth_headers(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    code = (await create(client, alice))["code"]

    assert (await client.delete(f"/api/urls/{code}", headers=bob)).status_code == 403
    row = await get_row(client, code)
    assert row is not None and row.is_active is True

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.errors import UnauthorizedError
from app.core.security import create_access_token, decode_access_token
from app.models import User
from tests.conftest import make_settings
from tests.helpers import DEFAULT_PASSWORD, login, register


async def test_register_returns_user_without_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/register", json={"email": "  Alice@Example.COM ", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert set(body) == {"id", "email", "created_at"}


async def test_password_is_stored_hashed(client: AsyncClient) -> None:
    await register(client, "bob@example.com")
    async with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        user = await session.scalar(select(User).where(User.email == "bob@example.com"))
    assert user is not None
    assert user.hashed_password != DEFAULT_PASSWORD
    assert user.hashed_password.startswith("$2b$")


async def test_register_duplicate_email_is_409(client: AsyncClient) -> None:
    await register(client, "dup@example.com")
    resp = await client.post(
        "/api/auth/register", json={"email": "DUP@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": DEFAULT_PASSWORD},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "é" * 37},  # 74 bytes > bcrypt's 72
        {"email": "a@example.com"},
    ],
)
async def test_register_validation_is_422(client: AsyncClient, payload: dict) -> None:
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert isinstance(error["details"], list) and error["details"]


async def test_login_returns_valid_token(client: AsyncClient) -> None:
    user = await register(client, "carol@example.com")
    resp = await client.post(
        "/api/auth/login", json={"email": "Carol@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 60 * 60
    settings = client.app.state.settings  # type: ignore[attr-defined]
    assert decode_access_token(body["access_token"], settings) == user["id"]


@pytest.mark.parametrize(
    ("email", "password"),
    [("dave@example.com", "wrong-password"), ("nobody@example.com", DEFAULT_PASSWORD)],
)
async def test_login_bad_credentials_is_401(client: AsyncClient, email: str, password: str) -> None:
    await register(client, "dave@example.com")
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 401
    # Same message for both cases: don't reveal which emails are registered.
    assert resp.json()["error"]["message"] == "Invalid email or password"
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_login_helper_roundtrip(client: AsyncClient) -> None:
    await register(client, "erin@example.com")
    assert await login(client, "erin@example.com")


def test_expired_token_rejected() -> None:
    settings = make_settings()
    token = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) - timedelta(seconds=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError, match="expired"):
        decode_access_token(token, settings)


def test_token_signed_with_other_secret_rejected() -> None:
    token, _ = create_access_token(1, make_settings(jwt_secret="x" * 40))
    with pytest.raises(UnauthorizedError, match="Invalid"):
        decode_access_token(token, make_settings())


def test_token_without_sub_rejected() -> None:
    settings = make_settings()
    token = jwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=5)}, settings.jwt_secret, algorithm="HS256"
    )
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, settings)

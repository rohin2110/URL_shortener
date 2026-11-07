"""Test fixtures.

Every test gets a fresh app instance (own settings, engine and Redis client) running
its real lifespan, against TEST_DATABASE_URL (tables truncated) and the TEST_REDIS_URL
DB index (flushed). The production .env is never read.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/urlshortener_test",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

# Must be set before app.main is imported (it builds a module-level app from env).
os.environ.update(
    DATABASE_URL=TEST_DATABASE_URL,
    REDIS_URL=TEST_REDIS_URL,
    JWT_SECRET="test-secret-test-secret-test-secret-0123",
    IP_HASH_SECRET="test-ip-hash-secret",
)

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402

BASE_SETTINGS: dict[str, Any] = {
    "database_url": TEST_DATABASE_URL,
    "redis_url": TEST_REDIS_URL,
    "jwt_secret": "test-secret-test-secret-test-secret-0123",
    "ip_hash_secret": "test-ip-hash-secret",
    "base_url": "http://test",
    "bcrypt_rounds": 4,  # fast hashing in tests
    "rate_limit_enabled": False,  # enabled explicitly in rate-limit tests
}


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})  # type: ignore[call-arg]


@pytest.fixture(scope="session", autouse=True)
def _fresh_schema() -> None:
    """Drop and recreate all tables once per test session."""

    async def reset() -> None:
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(reset())


async def _reset_state(app: FastAPI) -> None:
    async with app.state.engine.begin() as conn:
        await conn.execute(text("TRUNCATE clicks, urls, users RESTART IDENTITY CASCADE"))
    try:
        await app.state.redis.flushdb()
    except Exception:
        pass  # some tests deliberately point at an unreachable Redis


ClientFactory = Callable[..., Any]


@pytest.fixture
def client_factory() -> ClientFactory:
    """Build a client for an app with custom settings: `async with client_factory(**kw) as c`."""

    @asynccontextmanager
    async def factory(**overrides: Any) -> AsyncIterator[AsyncClient]:
        app = create_app(make_settings(**overrides))
        async with app.router.lifespan_context(app):
            await _reset_state(app)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                client.app = app  # type: ignore[attr-defined]  # handy for state access
                yield client

    return factory


@pytest.fixture
async def client(client_factory: ClientFactory) -> AsyncIterator[AsyncClient]:
    async with client_factory() as c:
        yield c


@pytest.fixture
def app(client: AsyncClient) -> FastAPI:
    return client.app  # type: ignore[attr-defined]

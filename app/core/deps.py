"""Shared FastAPI dependencies. Everything hangs off app.state so tests can build
isolated app instances with their own settings, engine and Redis client."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.services.cache_service import UrlCache


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    return sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker(request)() as session:
        yield session


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SessionmakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def get_url_cache(redis: RedisDep, settings: SettingsDep) -> UrlCache:
    return UrlCache(redis, settings)


UrlCacheDep = Annotated[UrlCache, Depends(get_url_cache)]

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> int:
    """Stateless JWT auth: the signed `sub` claim is trusted without a DB lookup."""
    if credentials is None:
        raise UnauthorizedError()
    return decode_access_token(credentials.credentials, settings)


CurrentUserId = Annotated[int, Depends(get_current_user_id)]

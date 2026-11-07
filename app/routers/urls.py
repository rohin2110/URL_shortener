from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.deps import CurrentUserId, SessionDep, SettingsDep, UrlCacheDep
from app.core.rate_limit import create_url_rate_limit
from app.schemas.error import ErrorResponse
from app.schemas.stats import UrlStats
from app.schemas.url import UrlCreate, UrlOut, UrlPage
from app.services import stats_service, url_service

router = APIRouter(prefix="/api/urls", tags=["urls"])


@router.post(
    "",
    response_model=UrlOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(create_url_rate_limit)],
    responses={429: {"model": ErrorResponse}},
)
async def create_url(
    body: UrlCreate, user_id: CurrentUserId, session: SessionDep, settings: SettingsDep
) -> UrlOut:
    url = await url_service.create_short_url(session, user_id, body.url)
    return UrlOut.from_model(url, settings.base_url)


@router.get("", response_model=UrlPage)
async def list_urls(
    user_id: CurrentUserId,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UrlPage:
    items, total = await url_service.list_urls(session, user_id, limit, offset)
    return UrlPage(
        items=[UrlOut.from_model(u, settings.base_url) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{code}", response_model=UrlOut)
async def get_url(
    code: str, user_id: CurrentUserId, session: SessionDep, settings: SettingsDep
) -> UrlOut:
    url = await url_service.get_owned_url(session, user_id, code)
    return UrlOut.from_model(url, settings.base_url)


@router.get("/{code}/stats", response_model=UrlStats)
async def get_url_stats(code: str, user_id: CurrentUserId, session: SessionDep) -> UrlStats:
    return await stats_service.get_stats_for_owner(session, user_id, code)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_url(
    code: str, user_id: CurrentUserId, session: SessionDep, cache: UrlCacheDep
) -> Response:
    await url_service.deactivate_url(session, cache, user_id, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

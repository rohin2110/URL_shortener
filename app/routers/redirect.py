from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import RedirectResponse

from app.core.deps import SessionDep, SessionmakerDep, SettingsDep, UrlCacheDep
from app.core.rate_limit import redirect_rate_limit
from app.schemas.error import ErrorResponse
from app.services import click_service, url_service

router = APIRouter(tags=["redirect"])


@router.get(
    "/{code}",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    dependencies=[Depends(redirect_rate_limit)],
    responses={404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def redirect(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,  # lazy: no DB connection is opened on a cache hit
    sessionmaker: SessionmakerDep,
    cache: UrlCacheDep,
    settings: SettingsDep,
) -> RedirectResponse:
    target = await url_service.resolve_redirect(session, cache, code)
    info = click_service.ClickInfo.from_request(request, settings)
    background_tasks.add_task(click_service.record_click, sessionmaker, target.id, info)
    return RedirectResponse(target.url, status_code=status.HTTP_302_FOUND)

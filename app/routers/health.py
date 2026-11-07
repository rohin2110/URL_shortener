from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.deps import RedisDep, SessionDep
from app.schemas.health import HealthOut, OverallStatus
from app.services import health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
async def health(session: SessionDep, redis: RedisDep) -> JSONResponse:
    db_ok = await health_service.check_database(session)
    redis_ok = await health_service.check_redis(redis)

    status: OverallStatus = "down" if not db_ok else "degraded" if not redis_ok else "ok"
    http_status = 503 if status == "down" else 200

    body = HealthOut(
        status=status,
        database="ok" if db_ok else "down",
        redis="ok" if redis_ok else "down",
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())

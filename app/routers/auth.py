from fastapi import APIRouter, Depends, status

from app.core.deps import SessionDep, SettingsDep
from app.core.rate_limit import auth_rate_limit
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.schemas.error import ErrorResponse
from app.services import auth_service

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    dependencies=[Depends(auth_rate_limit)],
    responses={429: {"model": ErrorResponse}},
)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: SessionDep, settings: SettingsDep) -> User:
    return await auth_service.register_user(session, body.email, body.password, settings)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenOut:
    return await auth_service.login(session, body.email, body.password, settings)

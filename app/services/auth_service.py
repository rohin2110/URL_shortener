from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import TokenOut

INVALID_CREDENTIALS = "Invalid email or password"


async def register_user(
    session: AsyncSession, email: str, password: str, settings: Settings
) -> User:
    user = User(email=email, hashed_password=await hash_password(password, settings.bcrypt_rounds))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # The unique constraint is the source of truth (no check-then-insert race).
        await session.rollback()
        raise ConflictError("Email is already registered") from None
    return user


async def login(session: AsyncSession, email: str, password: str, settings: Settings) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        await burn_password_check(password, settings.bcrypt_rounds)
        raise UnauthorizedError(INVALID_CREDENTIALS)
    if not await verify_password(password, user.hashed_password):
        raise UnauthorizedError(INVALID_CREDENTIALS)

    token, expires_in = create_access_token(user.id, settings)
    return TokenOut(access_token=token, expires_in=expires_in)

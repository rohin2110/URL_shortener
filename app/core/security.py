import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.config import Settings
from app.core.errors import UnauthorizedError

BCRYPT_MAX_PASSWORD_BYTES = 72  # bcrypt ignores (4.x) or rejects (5.x) anything longer


# --- passwords -------------------------------------------------------------------
# bcrypt is deliberately slow and CPU-bound: run it in a worker thread so it never
# blocks the event loop.


async def hash_password(password: str, rounds: int) -> str:
    def _hash() -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()

    return await run_in_threadpool(_hash)


async def verify_password(password: str, hashed_password: str) -> bool:
    return await run_in_threadpool(bcrypt.checkpw, password.encode(), hashed_password.encode())


@lru_cache
def _dummy_hash(rounds: int) -> str:
    return bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds)).decode()


async def burn_password_check(password: str, rounds: int) -> None:
    """Spend the same time as a real check, so unknown emails can't be detected by timing."""
    dummy = await run_in_threadpool(_dummy_hash, rounds)
    await verify_password(password, dummy)


# --- JWT -------------------------------------------------------------------------


def create_access_token(user_id: int, settings: Settings) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> int:
    """Validate the token and return the user id it was issued for."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid token") from None

    try:
        return int(payload["sub"])
    except (TypeError, ValueError):
        raise UnauthorizedError("Invalid token") from None


# --- client identity / privacy -----------------------------------------------------


def get_client_ip(request: Request, trusted_header: str | None) -> str:
    """Real client IP: from the proxy's header if one is configured, else the TCP peer."""
    if trusted_header:
        forwarded = request.headers.get(trusted_header, "").strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"



def hash_ip(ip: str, secret: str) -> str:
    """Keyed hash of an IP. A plain SHA-256 of an IPv4 address is trivially brute-forced
    (only 2^32 inputs); an HMAC with a server-side secret is not."""
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()

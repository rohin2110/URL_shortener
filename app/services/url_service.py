from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import base62
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.models import Url
from app.services.cache_service import CACHED_NOT_FOUND, CachedUrl, UrlCache

# Single-segment paths owned by real routes. A short code must never equal one of these,
# or the redirect route would shadow (or be shadowed by) them.
RESERVED_CODES: frozenset[str] = frozenset(
    {"api", "docs", "redoc", "openapi", "static", "health", "favicon", "robots", "index"}
)


def is_redirectable_code(code: str) -> bool:
    return base62.is_valid(code) and code not in RESERVED_CODES


async def create_short_url(session: AsyncSession, owner_id: int, original_url: str) -> Url:
    """Insert -> get ID -> base62(ID) -> set short_code, all in one transaction.

    IDs are unique, so codes are unique without any collision check. If an ID happens to
    encode to a reserved word, that row is discarded and the next ID is used.
    """
    try:
        while True:
            url = Url(original_url=original_url, owner_id=owner_id)
            session.add(url)
            await session.flush()  # INSERT ... RETURNING id
            code = base62.encode(url.id)
            if code not in RESERVED_CODES:
                break
            await session.delete(url)
            await session.flush()

        url.short_code = code
        await session.commit()
    except IntegrityError:
        # owner_id FK violation: a validly signed token for a user that no longer exists.
        await session.rollback()
        raise UnauthorizedError("User no longer exists") from None
    return url


async def list_urls(
    session: AsyncSession, owner_id: int, limit: int, offset: int
) -> tuple[Sequence[Url], int]:
    active_mine = select(Url).where(Url.owner_id == owner_id, Url.is_active)
    total = await session.scalar(select(func.count()).select_from(active_mine.subquery())) or 0
    items = (
        await session.scalars(active_mine.order_by(Url.id.desc()).limit(limit).offset(offset))
    ).all()
    return items, total


async def get_owned_url(session: AsyncSession, owner_id: int, code: str) -> Url:
    """Active URL by code; 404 if missing/deleted, 403 if it belongs to someone else."""
    url = None
    if base62.is_valid(code):
        url = await session.scalar(select(Url).where(Url.short_code == code, Url.is_active))
    if url is None:
        raise NotFoundError("Short URL not found")
    if url.owner_id != owner_id:
        raise ForbiddenError()
    return url


async def deactivate_url(session: AsyncSession, cache: UrlCache, owner_id: int, code: str) -> None:
    url = await get_owned_url(session, owner_id, code)
    url.is_active = False
    await session.commit()
    await cache.invalidate(code)  # after commit, so a concurrent miss can't re-cache it


async def resolve_redirect(session: AsyncSession, cache: UrlCache, code: str) -> CachedUrl:
    """Hot path: Redis first, Postgres on a miss; misses (incl. not-found) are cached."""
    if not is_redirectable_code(code):
        raise NotFoundError("Short URL not found")  # never touches Redis or the DB

    cached = await cache.get(code)
    if isinstance(cached, CachedUrl):
        return cached
    if cached is CACHED_NOT_FOUND:
        raise NotFoundError("Short URL not found")

    row = (
        await session.execute(
            select(Url.id, Url.original_url).where(Url.short_code == code, Url.is_active)
        )
    ).first()
    if row is None:
        await cache.set_not_found(code)
        raise NotFoundError("Short URL not found")

    entry = CachedUrl(id=row.id, url=row.original_url)
    await cache.set_url(code, entry)
    return entry

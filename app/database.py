from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import Base

TRANSACTION_POOLER_PORT = 6543


def build_connect_args(database_url: str) -> dict[str, object]:
    """asyncpg connect args for the given URL.

    Supabase's transaction pooler (Supavisor, port 6543) hands each transaction to a
    possibly different backend connection, so server-side prepared statements cannot
    be reused. Disable asyncpg's statement cache and SQLAlchemy's prepared-statement
    cache, and give every statement a unique name to avoid "already exists" clashes.
    """
    if make_url(database_url).port != TRANSACTION_POOLER_PORT:
        return {}
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=build_connect_args(settings.database_url),
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """create_all + enable RLS (idempotent).

    Supabase exposes every table in `public` through its auto-generated REST API to
    anyone holding the project's anon key. RLS with no policies denies that access;
    the app connects as the table owner, which bypasses RLS.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in Base.metadata.sorted_tables:
            await conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))

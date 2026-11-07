from httpx import AsyncClient
from sqlalchemy import inspect, text

from app.database import build_connect_args
from tests.conftest import ClientFactory


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_health_degraded_when_redis_down(client_factory: ClientFactory) -> None:
    async with client_factory(redis_url="redis://localhost:1/0") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "degraded", "database": "ok", "redis": "down"}


async def test_tables_created_on_startup(client: AsyncClient) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {"users", "urls", "clicks"} <= tables


async def test_row_level_security_enabled(client: AsyncClient) -> None:
    engine = client.app.state.engine  # type: ignore[attr-defined]
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT relname FROM pg_class WHERE relrowsecurity AND relname = ANY(:t)"),
            {"t": ["users", "urls", "clicks"]},
        )
    assert {r[0] for r in rows} == {"users", "urls", "clicks"}


def test_transaction_pooler_disables_prepared_statement_cache() -> None:
    pooler = "postgresql+asyncpg://u:p@aws-0-x.pooler.supabase.com:6543/postgres"
    session = "postgresql+asyncpg://u:p@aws-0-x.pooler.supabase.com:5432/postgres"
    args = build_connect_args(pooler)
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    assert build_connect_args(session) == {}

from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery"


async def register(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    resp = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def auth_headers(client: AsyncClient, email: str) -> dict[str, str]:
    """Register + login, return an Authorization header."""
    await register(client, email)
    return {"Authorization": f"Bearer {await login(client, email)}"}

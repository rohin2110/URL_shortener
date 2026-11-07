# URL Shortener

A URL shortener built with FastAPI, async SQLAlchemy 2.0 + asyncpg, PostgreSQL on Supabase, and Redis.

- Short codes are base62 encodings of row IDs.
- Redirects are served from a Redis cache.
- Clicks are logged in the background.
- Rate limiting is done with Redis.
- Authentication uses JWTs.
- The frontend is a single static HTML file.

## Contents

- [Setup](#setup)
- [Supabase setup](#supabase-setup)
- [Running with Docker Compose](#running-with-docker-compose)
- [Running tests](#running-tests)
- [API overview](#api-overview)
- [Project structure](#project-structure)
- [Design decisions](#design-decisions)

## Setup

Requirements: [Docker Desktop](https://www.docker.com/products/docker-desktop/) and a Supabase project. Python, Postgres and Redis run in containers, so nothing else needs installing on your machine.

```bash
cp .env.example .env
# Edit .env. At minimum set DATABASE_URL, JWT_SECRET and IP_HASH_SECRET.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # generates a secret
```

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase Postgres connection string. The scheme must be `postgresql+asyncpg://`. |
| `REDIS_URL` | Redis connection string. `redis://redis:6379/0` points at the compose service. |
| `JWT_SECRET` | Key used to sign JWTs (HS256). At least 32 characters. |
| `JWT_EXPIRE_MINUTES` | How long an access token stays valid. Default: 60. |
| `BCRYPT_ROUNDS` | bcrypt cost factor. Default: 12. |
| `IP_HASH_SECRET` | HMAC key used to hash visitor IPs before they are stored. |
| `BASE_URL` | Public origin used to build short links, e.g. `https://sho.rt` |
| `URL_CACHE_TTL_SECONDS` | How long a found URL stays in the redirect cache. Default: 86400. |
| `NOT_FOUND_CACHE_TTL_SECONDS` | How long a "not found" result stays cached. Default: 60. |
| `RATE_LIMIT_ENABLED` | Turns rate limiting on or off. |
| `RATE_LIMIT_WINDOW_SECONDS` | Length of a rate-limit window. |
| `RATE_LIMIT_AUTH` | Allowed requests per window, per IP, to `/api/auth/*` |
| `RATE_LIMIT_CREATE_URL` | Allowed requests per window, per user, to `POST /api/urls` |
| `RATE_LIMIT_REDIRECT` | Allowed requests per window, per IP, to `GET /{code}` |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | Used only by the test suite. Compose sets both. |

## Supabase setup

1. Create a project at [supabase.com](https://supabase.com).
2. Open **Connect** (top bar) and copy the **Session pooler** URI. It looks like this:
   `postgresql://postgres.<ref>:[PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`
3. Put it in `.env` as `DATABASE_URL`, with three changes:
   - Change the scheme to `postgresql+asyncpg://`.
   - Fill in the password. Percent-encode any of `@ : / # ? %` that appear in it.
   - Append `?ssl=require`. Don't use `sslmode`: asyncpg rejects it.
4. Create the tables. Use either of these:
   - Start the app. On startup it runs `create_all()` and enables row-level security (RLS).
   - Paste [`schema.sql`](schema.sql) into the Supabase **SQL editor**. It is idempotent and produces the same result as the app's startup.

### Which connection string to use

| Option | Use it? | Why |
|---|---|---|
| Direct connection (`db.<ref>.supabase.co`) | No | On the free tier it is IPv6-only, and Docker Desktop containers usually can't reach IPv6. |
| **Session pooler** (port 5432) | **Recommended** | It works over IPv4 and supports prepared statements. |
| Transaction pooler (port **6543**) | Works | Prepared statements must be disabled, and the app does this automatically. See below. |

**Transaction pooler.** In transaction mode, Supavisor can hand each transaction to a different backend connection. That means a prepared statement created on one connection may not exist on the next. When `DATABASE_URL` uses port `6543`, `app/database.py` handles this by:

- setting `connect_args={"statement_cache_size": 0}`, which disables asyncpg's statement cache;
- setting `prepared_statement_cache_size=0`, which disables SQLAlchemy's prepared-statement cache;
- giving each prepared statement a unique name, which avoids `prepared statement "…" already exists` errors.

**Row-level security.** Supabase serves every table in the `public` schema through its auto-generated REST API to anyone who has the project's `anon` key. The app therefore enables RLS on `users`, `urls` and `clicks` and defines no policies, so those REST calls return no rows. The app connects as the table owner (`postgres`), which is exempt from RLS.

## Running with Docker Compose

```bash
docker compose up --build          # API on http://localhost:8000, Redis on :6379
```

| URL | What it is |
|---|---|
| http://localhost:8000/ | Minimal frontend |
| http://localhost:8000/docs | OpenAPI / Swagger UI |
| http://localhost:8000/health | Database and Redis health check |

In development, `app/` and `static/` are bind-mounted into the container and uvicorn runs with `--reload`, so code changes take effect without rebuilding.

> **Running behind a reverse proxy?** Set `FORWARDED_ALLOW_IPS` to the proxy's IP address. Uvicorn (started with `--proxy-headers`) then trusts `X-Forwarded-For`, so rate limits and click IP hashes use the real client IP.

## Running tests

```bash
docker compose --profile test run --rm tests
docker compose --profile test run --rm tests pytest tests/test_redirect.py -v   # a subset
```

The test suite never connects to Supabase:

- **Database:** a throwaway `postgres-test` container with its data in tmpfs. Tables are dropped and recreated once per run, then truncated before every test.
- **Redis:** the compose Redis on DB index **15**, flushed before every test. The app itself uses DB 0.
- **Isolation:** each test builds its own app instance with its own settings and runs the real lifespan. Tests can therefore change rate limits or point at an unreachable Redis without affecting each other.

Coverage:

| Area | What the tests check |
|---|---|
| base62 | Known values, round trips, invalid input |
| Auth | Register, login, duplicate email (409), validation (422), wrong credentials (401), expired or forged tokens |
| URL CRUD | Create, list with pagination, details, soft delete, URL validation, reserved codes being skipped |
| Redirect | Cache miss, then fill, then hit (proven by changing the DB row behind the cache); 404 plus negative caching; cache invalidation on delete; click recording with hashed IP; keeps working with Redis down |
| Ownership | Another user's URL returns 403 on details, delete and stats |
| Rate limiting | 429 with `Retry-After` for each scope; window reset; per-user vs per-IP keys; keeps working with Redis down |
| Health | Health endpoint, tables created, RLS enabled |

## API overview

All error responses use the same shape:

```json
{"error": {"code": "not_found", "message": "Short URL not found", "details": null}}
```

The possible `code` values are `bad_request`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error` (422, with `details` listing the field errors) and `rate_limited` (429, with a `Retry-After` header).

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register` | – | Takes `{email, password}` and returns `201` with `{id, email, created_at}`. The password must be 8 characters to 72 bytes. A duplicate email returns `409`. |
| POST | `/api/auth/login` | – | Takes `{email, password}` and returns `{access_token, token_type, expires_in}` |
| POST | `/api/urls` | Bearer | Takes `{url}` and returns `201` with the URL object. Only http/https URLs up to 2048 characters are accepted. |
| GET | `/api/urls?limit=20&offset=0` | Bearer | Returns `{items, total, limit, offset}`: your active URLs, newest first. `limit` can be at most 100. |
| GET | `/api/urls/{code}` | Bearer | Returns the URL object. Someone else's URL returns `403`; a missing or deleted one returns `404`. |
| GET | `/api/urls/{code}/stats` | Bearer | Returns `{total_clicks, clicks_per_day[30], top_referrers[10], top_user_agents[10]}` |
| DELETE | `/api/urls/{code}` | Bearer | Soft-deletes the URL (`is_active=false`), invalidates its cache entry, and returns `204` |
| GET | `/{code}` | – | Redirects with `302` to the original URL. A missing or inactive code returns `404`. |
| GET | `/health` | – | Returns `{status, database, redis}`. `status` is `ok`, or `degraded` if Redis is down (still HTTP 200). If the database is down it returns `503`. |

The URL object is `{code, short_url, original_url, click_count, is_active, created_at}`.

```bash
curl -X POST localhost:8000/api/auth/register -H 'content-type: application/json' \
     -d '{"email":"me@example.com","password":"supersecret"}'
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'content-type: application/json' \
     -d '{"email":"me@example.com","password":"supersecret"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -X POST localhost:8000/api/urls -H "authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"url":"https://example.com/long"}'
```

## Project structure

```
app/
  main.py        app factory, lifespan (engine, Redis, create_all + RLS), routes, static files
  config.py      pydantic-settings
  database.py    async engine (transaction-pooler handling), sessionmaker, init_db
  redis.py       Redis client with short timeouts
  models/        User, Url, Click (SQLAlchemy 2.0 typed models)
  schemas/       Pydantic v2 request/response models
  routers/       thin HTTP layer: auth, urls (+ stats), redirect, health
  services/      business logic: auth, url, cache, click, stats, health
  core/          base62, security (bcrypt/JWT/IP hashing), rate_limit, errors, deps
static/index.html
tests/
```

Routers only parse input and call services. Services hold the logic and never import FastAPI routing. Settings, the engine and the Redis client live on `app.state` and are injected as dependencies. Because of this, tests can build isolated apps instead of overriding globals.

## Design decisions

**Why short codes are base62-encoded IDs.** Creating a link runs `INSERT`, gets the new ID back via `RETURNING`, then sets `short_code = base62(id)` and commits, all in one transaction. This has three advantages over random codes:
- Codes never collide, so there's no retry loop.
- Codes are as short as possible: 62⁶ ≈ 56 billion links fit in 6 characters.
- Encoding and decoding are O(1).

The drawback is that codes are sequential, so the volume of links is guessable. That's acceptable here because the stats endpoints check ownership, and the redirect endpoint is rate-limited and caches "not found" results.

If an ID happens to encode to a reserved route name (`api`, `docs`, `health`, `static`, …), that row is deleted inside the same transaction and the next ID is used, so the redirect route never shadows a real route. The catch-all `/{code}` route is registered last for the same reason.

**Caching strategy (cache-aside).** On a redirect, the app reads `url:{code}` from Redis:
- **Hit:** it redirects straight away. No database connection is opened, because the session is created lazily.
- **Miss:** it runs `SELECT id, original_url … WHERE short_code = $1 AND is_active` and caches the result as `{"id", "url"}` for 24 h.
- **Missing code:** it caches a `__nf__` marker for 60 s, so scanners and broken links can't repeatedly hit Postgres.

Codes that aren't valid base62 are rejected before Redis or the database is touched.

Deleting a link commits first, then overwrites the cache key with a short-lived `__nf__` tombstone instead of just deleting the key. Cache fills use `SET NX`, so a request that read the row just before the delete committed can't write the dead URL back into the cache for 24 h.

Every Redis call **fails open**: on an error the app logs it and falls back to Postgres. A Redis outage makes redirects slower but doesn't break them.

**Rate limiting.** This is a fixed-window counter, written by hand as a FastAPI dependency in `app/core/rate_limit.py`. Each window has its own key, `rl:{scope}:{identity}:{window_start}`, and `INCR` and `EXPIRE` run together in one `MULTI/EXEC`, so a counter can never be left without an expiry. Over the limit, the app returns `429` with `Retry-After` set to the seconds remaining in the window.

There are three scopes:

| Scope | Keyed by | Default limit |
|---|---|---|
| auth | Client IP (HMAC-hashed) | 10/min |
| create URL | User ID | 30/min |
| redirect | Client IP | 300/min |

The create-URL limiter runs after JWT authentication, so a request without a token gets `401` before it can get `429`. A fixed window was chosen over a sliding log because it costs one round trip and one small key per client per window. The trade-off is that a client can make up to 2× the limit in a burst that straddles a window boundary, which is acceptable for abuse protection. Like the cache, the limiter fails open: if Redis is down, requests are allowed.

**Background click logging.** The redirect is sent first. A FastAPI `BackgroundTask` then records the click using its own session, in one transaction that does two things:
- `INSERT` a row into `clicks`;
- `UPDATE urls SET click_count = click_count + 1`. The increment is done atomically in SQL, so concurrent clicks never lose updates.

Failures are logged and never reach the visitor. Visitor IPs are stored as `HMAC-SHA256(IP_HASH_SECRET, ip)`. A plain SHA-256 isn't enough, because all 2³² IPv4 addresses can be hashed in seconds to reverse it. User-agent and referrer values are truncated to their column sizes.

At very high traffic, two changes would help:
- Very popular links contend on their `click_count` row. Those increments could be buffered in Redis (`INCR`) and flushed in batches.
- BackgroundTasks don't survive a process crash. A queue (Redis Streams, or a task worker) would make click logging durable.

**Other choices**
- **Authentication:** bcrypt is used directly rather than through passlib, which is unmaintained and breaks with bcrypt ≥ 4.1. Hashing runs in a thread pool so it doesn't block the event loop, and passwords are capped at 72 bytes, bcrypt's input limit. JWTs are created and checked with PyJWT, are stateless, and carry the user ID in `sub`.
- **Login timing:** a login with an unknown email still runs a dummy bcrypt check, so response time doesn't reveal which emails are registered. Both failure cases return the same error message.
- **Statistics:** daily counts use UTC calendar days and are zero-filled. They come from a range scan on the composite index `(url_id, clicked_at)`. Because `url_id` is the leading column, the same index also serves lookups by `url_id`.

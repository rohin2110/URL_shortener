from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60, gt=0)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    # Links / analytics
    base_url: str = "http://localhost:8000"
    ip_hash_secret: str = Field(min_length=16)

    # Caching
    url_cache_ttl_seconds: int = Field(default=86_400, gt=0)
    not_found_cache_ttl_seconds: int = Field(default=60, gt=0)

    # Rate limiting (max requests per window)
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    rate_limit_auth: int = Field(default=10, gt=0)
    rate_limit_create_url: int = Field(default=30, gt=0)
    rate_limit_redirect: int = Field(default=300, gt=0)

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment

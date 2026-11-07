from datetime import datetime
from typing import Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, Field, TypeAdapter, ValidationError, field_validator

from app.models import Url
from app.models.url import MAX_URL_LENGTH

_HTTP_URL = TypeAdapter(AnyHttpUrl)
ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlCreate(BaseModel):
    url: str = Field(max_length=MAX_URL_LENGTH, examples=["https://example.com/some/long/path"])

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = value.strip()
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("URL must not contain whitespace or control characters")
        if urlsplit(value).scheme.lower() not in ALLOWED_SCHEMES:
            raise ValueError("only http and https URLs are allowed")
        try:
            _HTTP_URL.validate_python(value)  # host/port/IDN checks
        except ValidationError:
            raise ValueError("invalid URL") from None
        return value  # store exactly what the user gave us (no normalisation)


class UrlOut(BaseModel):
    code: str
    short_url: str
    original_url: str
    click_count: int
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, url: Url, base_url: str) -> Self:
        assert url.short_code is not None
        return cls(
            code=url.short_code,
            short_url=f"{base_url}/{url.short_code}",
            original_url=url.original_url,
            click_count=url.click_count,
            is_active=url.is_active,
            created_at=url.created_at,
        )


class UrlPage(BaseModel):
    items: list[UrlOut]
    total: int
    limit: int
    offset: int

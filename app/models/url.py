from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MAX_URL_LENGTH = 2048


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # NULL only inside the creating transaction (insert -> get id -> encode -> update).
    short_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    original_url: Mapped[str] = mapped_column(String(MAX_URL_LENGTH))
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    click_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

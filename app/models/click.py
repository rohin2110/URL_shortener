from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MAX_USER_AGENT_LENGTH = 512
MAX_REFERRER_LENGTH = 2048


class Click(Base):
    __tablename__ = "clicks"
    # (url_id, clicked_at) serves both "clicks for this URL" and the 30-day stats
    # range scan; url_id is its leading column, so it also acts as the url_id index.
    __table_args__ = (Index("ix_clicks_url_id_clicked_at", "url_id", "clicked_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    url_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("urls.id", ondelete="CASCADE")
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    ip_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256 hex, never the raw IP
    user_agent: Mapped[str | None] = mapped_column(String(MAX_USER_AGENT_LENGTH))
    referrer: Mapped[str | None] = mapped_column(String(MAX_REFERRER_LENGTH))

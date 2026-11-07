from datetime import date

from pydantic import BaseModel, Field


class DailyClicks(BaseModel):
    date: date
    clicks: int


class ReferrerCount(BaseModel):
    referrer: str
    clicks: int


class UserAgentCount(BaseModel):
    user_agent: str
    clicks: int


class UrlStats(BaseModel):
    code: str
    total_clicks: int
    clicks_per_day: list[DailyClicks] = Field(
        description="Last 30 days (UTC), oldest first, zero-filled; the last entry is today."
    )
    top_referrers: list[ReferrerCount] = Field(description="All-time top 10; direct visits excluded.")
    top_user_agents: list[UserAgentCount] = Field(description="All-time top 10.")

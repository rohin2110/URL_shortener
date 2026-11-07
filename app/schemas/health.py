from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "down"]
# "degraded" = Redis down: the app still serves (fail-open), just slower/unthrottled.
OverallStatus = Literal["ok", "degraded", "down"]


class HealthOut(BaseModel):
    status: OverallStatus
    database: CheckStatus
    redis: CheckStatus

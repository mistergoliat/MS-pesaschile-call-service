from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    ok: bool = Field(default=False, description="Always false for error responses.")
    error: str = Field(..., description="Stable application error code.")
    detail: str = Field(..., description="Human-readable description of the error.")
    payload: Any | None = Field(default=None, description="Optional debugging-safe payload.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ok": False,
                    "error": "LIVEKIT_NOT_CONFIGURED",
                    "detail": "Missing LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET or LIVEKIT_SIP_TRUNK_ID",
                }
            ]
        }
    }

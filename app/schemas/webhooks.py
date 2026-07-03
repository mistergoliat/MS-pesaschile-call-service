from typing import Any

from pydantic import BaseModel, Field


class LiveKitWebhookRequest(BaseModel):
    event: str | None = Field(default=None, description="Event name if provided by LiveKit.")
    room: dict[str, Any] | None = Field(default=None, description="Room details if provided.")
    participant: dict[str, Any] | None = Field(default=None, description="Participant details if provided.")
    call_session_id: str | None = Field(default=None, description="Optional direct correlation id.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Raw webhook payload fallback.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "event": "participant_joined",
                "room": {"name": "voice-room-123"},
                "participant": {"identity": "sip-abc"},
            }
        }
    }


class MetaWebhookRequest(BaseModel):
    object: str | None = Field(default=None, description="Meta webhook object type.")
    entry: list[dict[str, Any]] = Field(default_factory=list, description="Meta webhook entries.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Raw webhook payload fallback.")


class WebhookAckResponse(BaseModel):
    ok: bool = True
    message: str = "accepted"

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool = Field(..., description="Indicates whether the service is healthy.")
    service: str = Field(..., description="Service identifier.")
    status: str = Field(..., description="Current health status.")

    model_config = {
        "json_schema_extra": {
            "example": {"ok": True, "service": "voice-agent-service", "status": "healthy"}
        }
    }

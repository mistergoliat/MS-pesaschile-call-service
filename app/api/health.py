from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the basic health status for the voice agent service.",
)
async def health_check() -> HealthResponse:
    return HealthResponse(ok=True, service="voice-agent-service", status="healthy")

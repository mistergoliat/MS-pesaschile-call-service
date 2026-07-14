from fastapi import APIRouter

from app.api.calls import router as calls_router
from app.api.diagnostics import router as diagnostics_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.webhooks_livekit import router as livekit_router
from app.api.webhooks_meta import router as meta_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(diagnostics_router)
api_router.include_router(demo_router)
api_router.include_router(calls_router)
api_router.include_router(livekit_router)
api_router.include_router(meta_router)

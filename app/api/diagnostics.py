from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_settings_from_app
from app.config import Settings

router = APIRouter(tags=["Diagnostics"])


@router.get("/diagnostics/whatsapp-calling", summary="Inspect WhatsApp calling readiness")
async def whatsapp_calling_diagnostics(settings: Settings = Depends(get_settings_from_app)) -> dict[str, object]:
    return {
        "enabled": settings.whatsapp_calling_enabled,
        "test_mode": settings.whatsapp_calling_test_mode,
        "meta_configured": settings.meta_whatsapp_configured,
        "livekit_configured": settings.livekit_configured,
        "deepseek_configured": settings.deepseek_configured,
        "openai_speech_configured": settings.openai_speech_configured,
        "agent_name": settings.livekit_agent_name,
        "allowed_callers_count": len(settings.whatsapp_calling_allowed_callers_list),
        "webhook_url": settings.whatsapp_calling_webhook_url,
    }

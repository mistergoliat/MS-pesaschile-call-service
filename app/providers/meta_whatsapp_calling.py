from __future__ import annotations

from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.core.exceptions import AppError
from app.providers.base import VoiceProvider


class MetaWhatsAppCallingProvider(VoiceProvider):
    """
    Placeholder provider for future Meta WhatsApp Calling API support.

    Notes:
    - Business-initiated calling flows require explicit user permission and consent tracking.
    - This provider must never be used for cold calling or unauthorized outreach.
    - Future implementation will need webhook validation, permission workflows, and SIP/WebRTC signaling.
    """

    def __init__(self, settings: Settings, agent: RealtimeVoiceAgent) -> None:
        self.settings = settings
        self.agent = agent

    async def create_call(self, to: str | None, metadata: dict[str, object]) -> dict[str, object]:
        raise AppError(
            "META_WHATSAPP_CALLING_NOT_IMPLEMENTED",
            "Provider structure exists but real Meta WhatsApp Calling integration is not implemented yet.",
            status_code=501,
        )

    async def accept_call(self, call_id: str) -> dict[str, str]:
        raise AppError(
            "META_WHATSAPP_CALLING_NOT_IMPLEMENTED",
            "Provider structure exists but real Meta WhatsApp Calling integration is not implemented yet.",
            status_code=501,
        )

    async def end_call(self, call_id: str) -> None:
        return None

    async def get_call_status(self, call_id: str) -> dict[str, str]:
        return {"status": "not_implemented"}

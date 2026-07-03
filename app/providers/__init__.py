from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.providers.base import VoiceProvider
from app.providers.livekit_sip import LiveKitSIPProvider
from app.providers.local_webrtc import LocalWebRTCProvider
from app.providers.meta_whatsapp_calling import MetaWhatsAppCallingProvider


def build_provider_registry(settings: Settings, agent: RealtimeVoiceAgent) -> dict[str, VoiceProvider]:
    return {
        "local_webrtc": LocalWebRTCProvider(settings=settings, agent=agent),
        "livekit": LiveKitSIPProvider(settings=settings, agent=agent),
        "meta_whatsapp": MetaWhatsAppCallingProvider(settings=settings, agent=agent),
    }

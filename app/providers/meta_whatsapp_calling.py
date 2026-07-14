from __future__ import annotations

from typing import Any

from livekit import api as livekit_api
from livekit.protocol import rtc as livekit_rtc

from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.core.exceptions import AppError
from app.providers.base import VoiceProvider


class MetaWhatsAppCallingProvider(VoiceProvider):
    """
    LiveKit-backed WhatsApp calling provider for inbound calls.

    Outbound calling stays disabled in this iteration.
    """

    def __init__(self, settings: Settings, agent: RealtimeVoiceAgent) -> None:
        self.settings = settings
        self.agent = agent
        self._status_store: dict[str, dict[str, str]] = {}

    def _ensure_livekit_configured(self) -> None:
        if not self.settings.livekit_configured:
            raise AppError(
                "LIVEKIT_NOT_CONFIGURED",
                "Missing LIVEKIT_URL, LIVEKIT_API_KEY or LIVEKIT_API_SECRET.",
                status_code=503,
            )

    def _ensure_accept_configured(self) -> None:
        self._ensure_livekit_configured()
        if not self.settings.meta_whatsapp_access_token:
            raise AppError(
                "META_WHATSAPP_NOT_CONFIGURED",
                "Missing META_WHATSAPP_ACCESS_TOKEN.",
                status_code=503,
            )
        if not self.settings.meta_whatsapp_phone_number_id:
            raise AppError(
                "META_WHATSAPP_NOT_CONFIGURED",
                "Missing META_WHATSAPP_PHONE_NUMBER_ID.",
                status_code=503,
            )

    async def create_call(self, to: str | None, metadata: dict[str, object]) -> dict[str, object]:
        raise AppError(
            "WHATSAPP_CALLING_OUTBOUND_DISABLED",
            "Outbound WhatsApp calling is disabled in this iteration.",
            status_code=501,
        )

    async def accept_inbound_call(
        self,
        *,
        call_id: str,
        sdp: str,
        room_name: str,
        caller: str | None = None,
        phone_number_id: str | None = None,
        agents: list[livekit_api.RoomAgentDispatch] | None = None,
    ) -> dict[str, Any]:
        self._ensure_accept_configured()
        session_description = livekit_rtc.SessionDescription(type="offer", sdp=sdp)
        request = livekit_api.AcceptWhatsAppCallRequest(
            whatsapp_phone_number_id=phone_number_id or self.settings.meta_whatsapp_phone_number_id,
            whatsapp_api_key=self.settings.meta_whatsapp_access_token,
            whatsapp_cloud_api_version=self.settings.meta_whatsapp_cloud_api_version,
            whatsapp_call_id=call_id,
            sdp=session_description,
            room_name=room_name,
            agents=agents
            or [
                livekit_api.RoomAgentDispatch(
                    agent_name=self.settings.livekit_agent_name,
                )
            ],
        )

        try:
            async with livekit_api.LiveKitAPI(
                url=self.settings.livekit_url,
                api_key=self.settings.livekit_api_key,
                api_secret=self.settings.livekit_api_secret,
            ) as client:
                response = await client.connector.accept_whatsapp_call(request)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "LIVEKIT_CALL_ACCEPT_FAILED",
                "LiveKit failed while accepting the inbound WhatsApp call.",
                status_code=502,
                payload=str(exc),
            ) from exc

        accepted_room = getattr(response, "room_name", None) or room_name
        self._status_store[call_id] = {
            "status": "active",
            "room_id": accepted_room,
            "external_call_id": call_id,
        }
        if caller:
            self._status_store[call_id]["caller"] = caller
        if phone_number_id:
            self._status_store[call_id]["phone_number_id"] = phone_number_id
        return {
            "status": "active",
            "room_id": accepted_room,
            "external_call_id": call_id,
        }

    async def disconnect_call(self, call_id: str) -> dict[str, str]:
        self._ensure_livekit_configured()
        request = livekit_api.DisconnectWhatsAppCallRequest(
            whatsapp_call_id=call_id,
            disconnect_reason=livekit_api.DisconnectWhatsAppCallRequest.USER_INITIATED,
        )

        try:
            async with livekit_api.LiveKitAPI(
                url=self.settings.livekit_url,
                api_key=self.settings.livekit_api_key,
                api_secret=self.settings.livekit_api_secret,
            ) as client:
                await client.connector.disconnect_whatsapp_call(request)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "LIVEKIT_CALL_DISCONNECT_FAILED",
                "LiveKit failed while disconnecting the WhatsApp call.",
                status_code=502,
                payload=str(exc),
            ) from exc

        self._status_store[call_id] = {
            "status": "terminated",
            "external_call_id": call_id,
        }
        return {"status": "terminated"}

    async def accept_call(self, call_id: str) -> dict[str, Any]:
        return await self.get_call_status(call_id)

    async def end_call(self, call_id: str) -> None:
        await self.disconnect_call(call_id)

    async def get_call_status(self, call_id: str) -> dict[str, str]:
        return self._status_store.get(call_id, {"status": "unknown", "external_call_id": call_id})


LiveKitWhatsAppCallingProvider = MetaWhatsAppCallingProvider

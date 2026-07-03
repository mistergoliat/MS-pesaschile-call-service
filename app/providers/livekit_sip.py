from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.core.exceptions import AppError
from app.providers.base import VoiceProvider


class LiveKitSIPProvider(VoiceProvider):
    def __init__(self, settings: Settings, agent: RealtimeVoiceAgent) -> None:
        self.settings = settings
        self.agent = agent
        self._status_store: dict[str, dict[str, str]] = {}

    def _ensure_configured(self) -> None:
        required = [
            self.settings.livekit_url,
            self.settings.livekit_api_key,
            self.settings.livekit_api_secret,
            self.settings.livekit_sip_trunk_id,
        ]
        if not all(required):
            raise AppError(
                "LIVEKIT_NOT_CONFIGURED",
                "Missing LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET or LIVEKIT_SIP_TRUNK_ID",
                status_code=503,
            )
        if not self.settings.openai_api_key:
            raise AppError(
                "OPENAI_NOT_CONFIGURED",
                "Missing OPENAI_API_KEY. LiveKit voice agent requires OpenAI for realtime speech.",
                status_code=503,
            )

    async def create_call(self, to: str | None, metadata: dict[str, object]) -> dict[str, object]:
        self._ensure_configured()
        if not to:
            raise AppError(
                "MISSING_DESTINATION_NUMBER",
                "Field 'to' is required when provider=livekit.",
                status_code=422,
            )
        if to != self.settings.allowed_test_number:
            raise AppError(
                "OUTBOUND_CALL_BLOCKED",
                "MVP mode only allows calls to ALLOWED_TEST_NUMBER.",
                status_code=403,
            )

        room_name = f"voice-room-{uuid4().hex[:12]}"
        participant_identity = f"sip-{uuid4().hex[:10]}"
        room_metadata = json.dumps(
            {
                "provider": "livekit",
                "initial_message": metadata.get("initial_message", ""),
                "call_session_id": metadata.get("call_session_id"),
            },
            ensure_ascii=True,
        )

        try:
            from livekit import api as livekit_api
            from livekit.api.room_service import CreateRoomRequest
            from livekit.api.sip_service import CreateSIPParticipantRequest
        except ImportError as exc:
            raise AppError(
                "LIVEKIT_SDK_MISSING",
                "livekit-api dependency is required to place LiveKit SIP test calls.",
                status_code=503,
                payload=str(exc),
            ) from exc

        try:
            async with livekit_api.LiveKitAPI(
                url=self.settings.livekit_url,
                api_key=self.settings.livekit_api_key,
                api_secret=self.settings.livekit_api_secret,
            ) as client:
                room = await client.room.create_room(
                    CreateRoomRequest(
                        name=room_name,
                        empty_timeout=300,
                        max_participants=4,
                        metadata=room_metadata,
                    )
                )
                participant = await client.sip.create_sip_participant(
                    CreateSIPParticipantRequest(
                        sip_trunk_id=self.settings.livekit_sip_trunk_id,
                        sip_call_to=to,
                        room_name=room_name,
                        participant_identity=participant_identity,
                        participant_name="Authorized Test Call",
                        wait_until_answered=False,
                    )
                )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "LIVEKIT_CALL_FAILED",
                "LiveKit failed while creating the room or SIP participant.",
                status_code=502,
                payload=str(exc),
            ) from exc

        external_call_id = getattr(participant, "participant_identity", participant_identity)
        self._status_store[external_call_id] = {"status": "initiated", "room_id": room_name}
        return {
            "status": "initiated",
            "room_id": getattr(room, "name", room_name),
            "external_call_id": external_call_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    async def accept_call(self, call_id: str) -> dict[str, str]:
        self._status_store[call_id] = {"status": "active"}
        return {"status": "active"}

    async def end_call(self, call_id: str) -> None:
        self._status_store[call_id] = {"status": "ended"}

    async def get_call_status(self, call_id: str) -> dict[str, str]:
        return self._status_store.get(call_id, {"status": "unknown"})

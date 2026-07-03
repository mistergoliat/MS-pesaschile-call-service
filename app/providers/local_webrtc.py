from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.core.events import MEDIA_STARTED, SESSION_CREATED
from app.providers.base import VoiceProvider


class LocalWebRTCProvider(VoiceProvider):
    def __init__(self, settings: Settings, agent: RealtimeVoiceAgent) -> None:
        self.settings = settings
        self.agent = agent
        self._status_store: dict[str, dict[str, str]] = {}

    async def create_call(self, to: str | None, metadata: dict[str, object]) -> dict[str, object]:
        room_id = f"local-{uuid4().hex[:12]}"
        external_call_id = f"browser-{uuid4().hex[:12]}"
        self._status_store[external_call_id] = {"status": "initiated", "room_id": room_id}
        return {
            "status": "initiated",
            "room_id": room_id,
            "external_call_id": external_call_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "events": [
                {"event_type": SESSION_CREATED, "payload": {"provider": "local_webrtc", "room_id": room_id}},
                {"event_type": MEDIA_STARTED, "payload": {"mode": "browser_webrtc_ready"}},
            ],
        }

    async def accept_call(self, call_id: str) -> dict[str, str]:
        self._status_store[call_id] = {"status": "active"}
        return {"status": "active"}

    async def end_call(self, call_id: str) -> None:
        self._status_store[call_id] = {"status": "ended"}

    async def get_call_status(self, call_id: str) -> dict[str, str]:
        return self._status_store.get(call_id, {"status": "unknown"})

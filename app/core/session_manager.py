from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.call_event import VoiceCallEvent
from app.models.call_session import VoiceCallSession
from app.services.summary_service import SummaryService


class SessionManager:
    def __init__(self, db: Session, summary_service: SummaryService) -> None:
        self.db = db
        self.summary_service = summary_service

    def create_session(
        self,
        *,
        provider: str,
        to_number: str | None,
        direction: str = "outbound",
        status: str = "created",
    ) -> VoiceCallSession:
        session = VoiceCallSession(
            provider=provider,
            direction=direction,
            to_number=to_number,
            status=status,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def record_event(self, event_type: str, payload: dict[str, Any], call_session_id: str | None = None) -> None:
        event = VoiceCallEvent(
            call_session_id=call_session_id,
            event_type=event_type,
            payload_json=json.dumps(payload, ensure_ascii=True),
        )
        self.db.add(event)
        self.db.commit()

    def mark_initiated(self, session: VoiceCallSession, provider_payload: dict[str, Any]) -> VoiceCallSession:
        session.status = str(provider_payload.get("status", "initiated"))
        session.room_id = provider_payload.get("room_id")
        session.external_call_id = provider_payload.get("external_call_id")
        session.started_at = datetime.now(timezone.utc)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def mark_failed(self, session: VoiceCallSession, error_message: str) -> VoiceCallSession:
        session.status = "failed"
        session.error_message = error_message
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def end_session(self, session: VoiceCallSession, status: str = "ended") -> VoiceCallSession:
        ended_at = datetime.now(timezone.utc)
        session.ended_at = ended_at
        session.status = status
        if session.started_at:
            delta = ended_at - session.started_at
            session.duration_seconds = max(int(delta.total_seconds()), 0)
        summary = self.summary_service.build_summary(session.transcript_text, session.status)
        session.summary_json = self.summary_service.serialize(summary)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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
        from_number: str | None = None,
        external_call_id: str | None = None,
        room_id: str | None = None,
    ) -> VoiceCallSession:
        session = VoiceCallSession(
            provider=provider,
            direction=direction,
            to_number=to_number,
            from_number=from_number,
            external_call_id=external_call_id,
            room_id=room_id,
            status=status,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def find_by_external_call_id(self, provider: str, external_call_id: str) -> VoiceCallSession | None:
        return self.db.execute(
            select(VoiceCallSession).where(
                VoiceCallSession.provider == provider,
                VoiceCallSession.external_call_id == external_call_id,
            )
        ).scalar_one_or_none()

    def get_or_create_inbound_session(
        self,
        *,
        provider: str,
        from_number: str | None,
        to_number: str | None,
        external_call_id: str,
        room_id: str,
        status: str = "incoming",
    ) -> tuple[VoiceCallSession, bool]:
        session = self.find_by_external_call_id(provider, external_call_id)
        created = False
        if session is None:
            session = self.create_session(
                provider=provider,
                to_number=to_number,
                direction="inbound",
                status=status,
                from_number=from_number,
                external_call_id=external_call_id,
                room_id=room_id,
            )
            created = True
        else:
            updated = False
            if from_number and session.from_number != from_number:
                session.from_number = from_number
                updated = True
            if to_number and session.to_number != to_number:
                session.to_number = to_number
                updated = True
            if room_id and session.room_id != room_id:
                session.room_id = room_id
                updated = True
            if session.direction != "inbound":
                session.direction = "inbound"
                updated = True
            if session.status == "created":
                session.status = status
                updated = True
            if updated:
                self.db.add(session)
                self.db.commit()
                self.db.refresh(session)
        return session, created

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

    def mark_active(self, session: VoiceCallSession, provider_payload: dict[str, Any]) -> VoiceCallSession:
        session.status = str(provider_payload.get("status", "active"))
        session.room_id = provider_payload.get("room_id") or session.room_id
        session.external_call_id = provider_payload.get("external_call_id") or session.external_call_id
        if not session.started_at:
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
            started_at = session.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            delta = ended_at - started_at
            session.duration_seconds = max(int(delta.total_seconds()), 0)
        summary = self.summary_service.build_summary(session.transcript_text, session.status)
        session.summary_json = self.summary_service.serialize(summary)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

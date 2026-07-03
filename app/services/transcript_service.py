from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.call_session import VoiceCallSession


class TranscriptService:
    def append_text(self, db: Session, call_session_id: str, text: str) -> None:
        session = db.get(VoiceCallSession, call_session_id)
        if not session:
            raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

        existing = session.transcript_text or ""
        session.transcript_text = f"{existing}\n{text}".strip() if existing else text
        db.add(session)
        db.commit()

    def finalize(self, db: Session, call_session_id: str, text: str | None = None) -> str | None:
        if text:
            self.append_text(db, call_session_id, text)
        session = db.get(VoiceCallSession, call_session_id)
        return session.transcript_text if session else None

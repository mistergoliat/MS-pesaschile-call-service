from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.session_manager import SessionManager
from app.db.database import get_db
from app.models.call_session import VoiceCallSession
from app.schemas.webhooks import LiveKitWebhookRequest, WebhookAckResponse
from app.services.summary_service import SummaryService

router = APIRouter(prefix="/webhooks/livekit", tags=["LiveKit Webhooks"])


@router.post(
    "",
    response_model=WebhookAckResponse,
    summary="Receive LiveKit webhook events",
    description="Stores raw LiveKit webhook payloads and updates a correlated session when possible.",
)
async def livekit_webhook(payload: LiveKitWebhookRequest, db: Session = Depends(get_db)) -> WebhookAckResponse:
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)

    correlated_session_id = payload.call_session_id
    correlated_session = None
    if not correlated_session_id and payload.room and payload.room.get("name"):
        correlated_session = db.execute(
            select(VoiceCallSession).where(VoiceCallSession.room_id == payload.room["name"])
        ).scalar_one_or_none()
        correlated_session_id = correlated_session.id if correlated_session else None
    elif correlated_session_id:
        correlated_session = db.get(VoiceCallSession, correlated_session_id)

    raw_payload = payload.model_dump(mode="json")
    event_type = payload.event or "livekit_webhook_received"
    session_manager.record_event(event_type, raw_payload, call_session_id=correlated_session_id)

    status_map = {
        "participant_joined": "active",
        "sip_call_ringing": "ringing",
        "sip_call_started": "active",
        "participant_left": "completed",
        "sip_call_finished": "completed",
    }
    mapped_status = status_map.get(event_type)
    if correlated_session and mapped_status:
        if mapped_status == "completed":
            session_manager.end_session(correlated_session, status="completed")
        else:
            correlated_session.status = mapped_status
            db.add(correlated_session)
            db.commit()

    return WebhookAckResponse(ok=True, message="accepted")

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.session_manager import SessionManager
from app.db.database import get_db
from app.schemas.webhooks import MetaWebhookRequest, WebhookAckResponse
from app.services.summary_service import SummaryService

router = APIRouter(prefix="/webhooks/meta/whatsapp-calling", tags=["Meta WhatsApp Calling Webhooks"])


@router.post(
    "",
    response_model=WebhookAckResponse,
    summary="Receive Meta WhatsApp Calling placeholder webhooks",
    description=(
        "Stores raw Meta webhook payloads for future WhatsApp Calling API integration. "
        "Real calling behavior is intentionally not implemented yet."
    ),
)
async def meta_whatsapp_webhook(payload: MetaWebhookRequest, db: Session = Depends(get_db)) -> WebhookAckResponse:
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)
    session_manager.record_event("meta_whatsapp_webhook_received", payload.model_dump(mode="json"))
    return WebhookAckResponse(ok=True, message="accepted")

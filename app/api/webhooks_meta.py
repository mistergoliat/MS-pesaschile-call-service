from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from livekit import api as livekit_api

from app.api.deps import get_provider_registry, get_settings_from_app
from app.config import Settings
from app.core.exceptions import AppError
from app.core.session_manager import SessionManager
from app.core.whatsapp_calling import (
    MetaWhatsAppCallEvent,
    build_room_name,
    extract_meta_call_events,
    is_e164_number,
    normalize_phone_number,
    sanitize_meta_payload,
    verify_meta_signature,
)
from app.db.database import get_db
from app.providers.meta_whatsapp_calling import MetaWhatsAppCallingProvider
from app.schemas.webhooks import WebhookAckResponse
from app.services.summary_service import SummaryService

logger = logging.getLogger("voice-agent-service.whatsapp")
router = APIRouter(prefix="/webhooks/meta/whatsapp-calling", tags=["Meta WhatsApp Calling Webhooks"])
BUSINESS_WHATSAPP_NUMBER = "+56921757996"


def _record_event(
    session_manager: SessionManager,
    event_type: str,
    payload: dict[str, Any],
    *,
    call_session_id: str | None = None,
) -> None:
    session_manager.record_event(event_type, payload, call_session_id=call_session_id)


def _event_log_payload(event: MetaWhatsAppCallEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "call_id": event.call_id,
        "caller": event.caller,
        "phone_number_id": event.phone_number_id,
        "sdp_type": event.sdp_type,
        "raw_summary": event.raw_summary,
    }


def _reject(
    session_manager: SessionManager,
    *,
    reason: str,
    event: MetaWhatsAppCallEvent | None,
    session_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "reason": reason,
        "event": _event_log_payload(event) if event else None,
    }
    if extra:
        payload.update(extra)
    _record_event(session_manager, "inbound_call_rejected", payload, call_session_id=session_id)


def _validate_forward_auth(request: Request, raw_body: bytes, settings: Settings) -> None:
    signature = request.headers.get("x-hub-signature-256")
    internal_secret = request.headers.get("x-internal-webhook-secret")

    if signature:
        if not verify_meta_signature(raw_body, signature, settings.meta_whatsapp_app_secret):
            raise AppError(
                "META_WHATSAPP_SIGNATURE_INVALID",
                "Invalid X-Hub-Signature-256 for WhatsApp webhook request.",
                status_code=403,
            )
        return

    if not internal_secret:
        raise AppError(
            "WEBHOOK_AUTH_REQUIRED",
            "WhatsApp webhook requests must include a Meta signature or X-Internal-Webhook-Secret.",
            status_code=403,
        )
    if not settings.internal_webhook_secret or internal_secret != settings.internal_webhook_secret:
        raise AppError(
            "WEBHOOK_AUTH_REQUIRED",
            "Invalid X-Internal-Webhook-Secret for forwarded WhatsApp webhook request.",
            status_code=403,
        )


def _validate_verification_token(settings: Settings, verify_token: str | None) -> None:
    if verify_token != settings.meta_whatsapp_verify_token:
        raise AppError(
            "META_WHATSAPP_WEBHOOK_VERIFICATION_FAILED",
            "Webhook verification token did not match.",
            status_code=403,
        )


@router.get(
    "",
    summary="Verify Meta WhatsApp Calling webhook",
    description="Handles the standard Meta webhook verification handshake.",
)
async def verify_meta_whatsapp_webhook(
    request: Request,
    settings: Settings = Depends(get_settings_from_app),
) -> PlainTextResponse:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and challenge:
        _validate_verification_token(settings, verify_token)
        return PlainTextResponse(challenge)

    raise AppError(
        "META_WHATSAPP_WEBHOOK_VERIFICATION_FAILED",
        "Webhook verification failed.",
        status_code=403,
    )


async def _handle_connect_event(
    *,
    event: MetaWhatsAppCallEvent,
    session_manager: SessionManager,
    provider: MetaWhatsAppCallingProvider,
    settings: Settings,
) -> None:
    if not settings.whatsapp_calling_enabled:
        _reject(
            session_manager,
            reason="feature_flag_disabled",
            event=event,
            extra={"enabled": False},
        )
        raise AppError(
            "WHATSAPP_CALLING_DISABLED",
            "WhatsApp calling is disabled by feature flag.",
            status_code=403,
        )

    call_id = event.call_id
    if not call_id:
        _reject(session_manager, reason="missing_call_id", event=event)
        raise AppError(
            "META_WHATSAPP_CALL_ID_MISSING",
            "WhatsApp call_id is required.",
            status_code=422,
        )

    room_name = build_room_name(call_id)
    session, created = session_manager.get_or_create_inbound_session(
        provider="livekit_whatsapp",
        from_number=event.caller,
        to_number=BUSINESS_WHATSAPP_NUMBER,
        external_call_id=call_id,
        room_id=room_name,
        status="incoming",
    )

    if session.status in {"active", "connected"} and session.room_id:
        _record_event(
            session_manager,
            "inbound_call_validated",
            {
                "idempotent": True,
                "event": _event_log_payload(event),
                "room_name": session.room_id,
            },
            call_session_id=session.id,
        )
        return

    if event.phone_number_id != settings.meta_whatsapp_phone_number_id:
        _reject(
            session_manager,
            reason="phone_number_id_mismatch",
            event=event,
            session_id=session.id,
            extra={
                "expected": settings.meta_whatsapp_phone_number_id,
                "received": event.phone_number_id,
            },
        )
        session_manager.mark_failed(session, "Phone number ID did not match the configured WhatsApp business number.")
        raise AppError(
            "META_WHATSAPP_PHONE_NUMBER_ID_MISMATCH",
            "Unexpected WhatsApp phone number ID.",
            status_code=422,
        )

    if not event.sdp:
        _reject(session_manager, reason="missing_sdp", event=event, session_id=session.id)
        session_manager.mark_failed(session, "Missing SDP offer in WhatsApp call connect webhook.")
        raise AppError(
            "META_WHATSAPP_SDP_MISSING",
            "WhatsApp call connect webhook did not include an SDP offer.",
            status_code=422,
        )

    caller = normalize_phone_number(event.caller)
    if not is_e164_number(caller):
        _reject(session_manager, reason="invalid_caller", event=event, session_id=session.id)
        session_manager.mark_failed(session, "Caller did not use a valid E.164 phone number.")
        raise AppError(
            "META_WHATSAPP_CALLER_INVALID",
            "Caller must be a valid E.164 phone number.",
            status_code=422,
        )

    allowed_callers = settings.whatsapp_calling_allowed_callers_list
    if settings.whatsapp_calling_test_mode and caller not in allowed_callers:
        _reject(
            session_manager,
            reason="caller_blocked",
            event=event,
            session_id=session.id,
            extra={"allowed_callers_count": len(allowed_callers)},
        )
        session_manager.mark_failed(session, f"Caller {caller} is not in the allowlist for test mode.")
        raise AppError(
            "META_WHATSAPP_CALLER_BLOCKED",
            "Caller is not allowlisted for WhatsApp calling test mode.",
            status_code=403,
        )

    _record_event(
        session_manager,
        "inbound_call_validated",
        {
            "created": created,
            "event": _event_log_payload(event),
            "room_name": room_name,
            "caller": caller,
        },
        call_session_id=session.id,
    )
    _record_event(
        session_manager,
        "livekit_accept_requested",
        {
            "room_name": room_name,
            "call_id": call_id,
            "phone_number_id": event.phone_number_id,
            "agent_name": settings.livekit_agent_name,
        },
        call_session_id=session.id,
    )

    try:
        provider_result = await provider.accept_inbound_call(
            call_id=call_id,
            sdp=event.sdp,
            room_name=room_name,
            caller=caller,
            phone_number_id=event.phone_number_id,
            agents=[livekit_api.RoomAgentDispatch(agent_name=settings.livekit_agent_name)],
        )
    except AppError as exc:
        session_manager.mark_failed(session, exc.detail)
        _record_event(
            session_manager,
            "inbound_call_failed",
            {
                "event": _event_log_payload(event),
                "error": exc.error,
                "detail": exc.detail,
            },
            call_session_id=session.id,
        )
        raise

    session_manager.mark_active(session, provider_result)
    _record_event(
        session_manager,
        "livekit_call_accepted",
        {
            "room_name": provider_result.get("room_id"),
            "external_call_id": provider_result.get("external_call_id"),
        },
        call_session_id=session.id,
    )
    _record_event(
        session_manager,
        "agent_dispatched",
        {
            "room_name": provider_result.get("room_id"),
            "agent_name": settings.livekit_agent_name,
        },
        call_session_id=session.id,
    )


async def _handle_terminate_event(
    *,
    event: MetaWhatsAppCallEvent,
    session_manager: SessionManager,
    provider: MetaWhatsAppCallingProvider,
    settings: Settings,
) -> None:
    call_id = event.call_id
    if not call_id:
        _reject(session_manager, reason="missing_call_id", event=event)
        raise AppError(
            "META_WHATSAPP_CALL_ID_MISSING",
            "WhatsApp call_id is required.",
            status_code=422,
        )

    room_name = build_room_name(call_id)
    session, _ = session_manager.get_or_create_inbound_session(
        provider="livekit_whatsapp",
        from_number=event.caller,
        to_number=BUSINESS_WHATSAPP_NUMBER,
        external_call_id=call_id,
        room_id=room_name,
        status="incoming",
    )

    _record_event(
        session_manager,
        "inbound_call_validated",
        {
            "event": _event_log_payload(event),
            "room_name": room_name,
            "caller": event.caller,
            "terminate": True,
        },
        call_session_id=session.id,
    )

    if session.status in {"terminated", "ended"} and session.ended_at:
        _record_event(
            session_manager,
            "inbound_call_terminated",
            {
                "room_name": session.room_id,
                "call_id": call_id,
                "idempotent": True,
            },
            call_session_id=session.id,
        )
        return

    try:
        await provider.disconnect_call(call_id)
    except AppError as exc:
        session_manager.mark_failed(session, exc.detail)
        _record_event(
            session_manager,
            "inbound_call_failed",
            {
                "event": _event_log_payload(event),
                "error": exc.error,
                "detail": exc.detail,
            },
            call_session_id=session.id,
        )
        raise

    session_manager.end_session(session, status="terminated")
    _record_event(
        session_manager,
        "inbound_call_terminated",
        {
            "room_name": session.room_id,
            "call_id": call_id,
            "duration_seconds": session.duration_seconds,
        },
        call_session_id=session.id,
    )


@router.post(
    "",
    response_model=WebhookAckResponse,
    summary="Receive Meta WhatsApp Calling webhooks",
    description="Processes direct Meta webhooks and forwarded internal webhooks for inbound WhatsApp calls.",
)
async def meta_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    providers: dict[str, Any] = Depends(get_provider_registry),
) -> WebhookAckResponse:
    raw_body = await request.body()
    _validate_forward_auth(request, raw_body, settings)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AppError(
            "META_WHATSAPP_INVALID_JSON",
            "WhatsApp webhook body must be valid JSON.",
            status_code=422,
        ) from exc

    sanitized_payload = sanitize_meta_payload(payload if isinstance(payload, dict) else {"payload": payload})
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)
    _record_event(session_manager, "meta_call_webhook_received", {"payload": sanitized_payload})

    events = extract_meta_call_events(payload if isinstance(payload, dict) else {})
    if not events:
        logger.info(
            "meta_whatsapp_webhook_ignored",
            extra={"payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else []},
        )
        return WebhookAckResponse(ok=True, message="accepted")

    provider = providers.get("meta_whatsapp")
    if not isinstance(provider, MetaWhatsAppCallingProvider):
        raise AppError(
            "PROVIDER_NOT_FOUND",
            "Meta WhatsApp provider is not registered.",
            status_code=500,
        )

    for event in events:
        logger.info(
            "meta_whatsapp_call_event",
            extra={"event": event.raw_summary, "has_sdp": bool(event.sdp)},
        )
        if event.event_type == "connect":
            await _handle_connect_event(
                event=event,
                session_manager=session_manager,
                provider=provider,
                settings=settings,
            )
        elif event.event_type == "terminate":
            await _handle_terminate_event(
                event=event,
                session_manager=session_manager,
                provider=provider,
                settings=settings,
            )
        else:
            _reject(
                session_manager,
                reason=f"unsupported_event:{event.event_type or 'unknown'}",
                event=event,
            )

    return WebhookAckResponse(ok=True, message="accepted")

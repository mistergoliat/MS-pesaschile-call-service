from __future__ import annotations

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_compliance_service, get_provider_registry, get_rate_limit_service
from app.core.events import CALL_ENDED, CALL_FAILED, CALL_REQUESTED
from app.core.exceptions import AppError
from app.core.session_manager import SessionManager
from app.db.database import get_db
from app.models.call_session import VoiceCallSession
from app.providers.base import VoiceProvider
from app.schemas.calls import (
    CallEndRequest,
    CallEndResponse,
    CallEventIngestRequest,
    CallEventIngestResponse,
    CallStatusResponse,
    CallTestRequest,
    CallTestResponse,
)
from app.schemas.errors import ErrorResponse
from app.services.compliance_service import ComplianceService
from app.services.summary_service import SummaryService
from app.services.transcript_service import TranscriptService

router = APIRouter(prefix="/calls", tags=["Calls"])


def _status_datetime(value: object) -> str | None:
    return value.isoformat() if value else None


@router.post(
    "/test",
    response_model=CallTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an authorized test call",
    description=(
        "Creates a test voice session using the selected provider. "
        "The core flow uses the VoiceProvider abstraction and enforces MVP compliance guardrails."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Structured application error."},
        403: {"model": ErrorResponse, "description": "Blocked by compliance or suppression rules."},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded."},
        503: {"model": ErrorResponse, "description": "Provider or upstream configuration missing."},
    },
)
async def create_test_call(
    payload: CallTestRequest,
    db: Session = Depends(get_db),
    providers: dict[str, VoiceProvider] = Depends(get_provider_registry),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    rate_limit_service=Depends(get_rate_limit_service),
) -> CallTestResponse:
    provider = providers[payload.provider]
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)

    await rate_limit_service.check_call_allowed(bucket="calls:test")
    session = session_manager.create_session(
        provider=payload.provider,
        to_number=payload.to,
        status="created",
    )
    session_manager.record_event(
        CALL_REQUESTED,
        payload.model_dump(mode="json"),
        call_session_id=session.id,
    )

    try:
        if payload.provider == "livekit":
            if not payload.to:
                raise AppError(
                    "MISSING_DESTINATION_NUMBER",
                    "Field 'to' is required when provider=livekit.",
                    status_code=422,
                )
            await compliance_service.validate_outbound_test_call(db, payload.to)

        provider_result = await provider.create_call(
            payload.to,
            {
                "call_session_id": session.id,
                "initial_message": payload.initial_message,
            },
        )
        session = session_manager.mark_initiated(session, provider_result)
        for event in provider_result.get("events", []):
            session_manager.record_event(
                event_type=str(event.get("event_type", "provider_event")),
                payload=event.get("payload", {}),
                call_session_id=session.id,
            )
        return CallTestResponse(
            ok=True,
            call_session_id=session.id,
            provider=session.provider,
            status=session.status,
            room_id=session.room_id,
            external_call_id=session.external_call_id,
        )
    except AppError as exc:
        session_manager.mark_failed(session, exc.detail)
        session_manager.record_event(
            CALL_FAILED,
            {"error": exc.error, "detail": exc.detail, "payload": exc.payload},
            call_session_id=session.id,
        )
        raise


@router.post(
    "/end",
    response_model=CallEndResponse,
    summary="End an existing call session",
    description="Ends a session using its registered provider and stores a final summary.",
    responses={
        404: {"model": ErrorResponse, "description": "Call session not found."},
        400: {"model": ErrorResponse, "description": "Structured application error."},
    },
)
async def end_call(
    payload: CallEndRequest,
    db: Session = Depends(get_db),
    providers: dict[str, VoiceProvider] = Depends(get_provider_registry),
) -> CallEndResponse:
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)
    session = db.get(VoiceCallSession, payload.call_session_id)
    if not session:
        raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

    provider = providers.get(session.provider)
    if not provider:
        raise AppError("PROVIDER_NOT_FOUND", f"Provider '{session.provider}' is not registered.", status_code=500)

    await provider.end_call(session.external_call_id or session.id)
    session = session_manager.end_session(session, status="ended")
    session_manager.record_event(CALL_ENDED, {"status": session.status}, call_session_id=session.id)

    return CallEndResponse(
        ok=True,
        call_session_id=session.id,
        status=session.status,
        duration_seconds=session.duration_seconds,
    )


@router.get(
    "/{call_id}",
    response_model=CallStatusResponse,
    summary="Get call session status",
    description="Returns the stored status and metadata for a voice call session.",
    responses={404: {"model": ErrorResponse, "description": "Call session not found."}},
)
async def get_call_status(call_id: str, db: Session = Depends(get_db)) -> CallStatusResponse:
    session = db.get(VoiceCallSession, call_id)
    if not session:
        raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

    summary_json = None
    if session.summary_json:
        try:
            summary_json = json.loads(session.summary_json)
        except json.JSONDecodeError:
            summary_json = session.summary_json

    return CallStatusResponse(
        id=session.id,
        provider=session.provider,
        direction=session.direction,
        to_number=session.to_number,
        status=session.status,
        started_at=_status_datetime(session.started_at),
        ended_at=_status_datetime(session.ended_at),
        duration_seconds=session.duration_seconds,
        summary_json=summary_json,
        error_message=session.error_message,
    )


@router.post(
    "/{call_id}/events",
    response_model=CallEventIngestResponse,
    summary="Store internal provider or agent events",
    description=(
        "Internal ingestion endpoint used by local/browser or LiveKit-side workers to persist call events "
        "and transcript updates into the core service."
    ),
    responses={404: {"model": ErrorResponse, "description": "Call session not found."}},
)
async def ingest_call_event(
    call_id: str,
    payload: CallEventIngestRequest,
    db: Session = Depends(get_db),
) -> CallEventIngestResponse:
    summary_service = SummaryService()
    transcript_service = TranscriptService()
    session_manager = SessionManager(db, summary_service)
    session = db.get(VoiceCallSession, call_id)
    if not session:
        raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

    session_manager.record_event(payload.event_type, payload.payload, call_session_id=call_id)
    if payload.transcript_text:
        transcript_service.append_text(db, call_id, payload.transcript_text)
    if payload.status:
        session.status = payload.status
        db.add(session)
        db.commit()

    return CallEventIngestResponse(ok=True, stored=True)

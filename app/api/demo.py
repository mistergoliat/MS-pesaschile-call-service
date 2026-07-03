from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_agent, get_provider_registry, get_rate_limit_service, get_transcript_service
from app.core.agent import RealtimeVoiceAgent
from app.core.exceptions import AppError
from app.core.session_manager import SessionManager
from app.db.database import get_db
from app.models.call_session import VoiceCallSession
from app.providers.base import VoiceProvider
from app.schemas.calls import (
    DemoConnectRequest,
    DemoConnectResponse,
    DemoEventRequest,
    DemoEventResponse,
    DemoSessionRequest,
    DemoSessionResponse,
)
from app.schemas.errors import ErrorResponse
from app.services.summary_service import SummaryService
from app.services.transcript_service import TranscriptService

router = APIRouter(tags=["Demo"])
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@router.get(
    "/demo",
    summary="Open the local browser demo",
    description="Serves a minimal browser UI for local WebRTC testing without a telephony carrier.",
    response_class=FileResponse,
)
async def demo_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "demo.html")


@router.post(
    "/demo/session",
    response_model=DemoSessionResponse,
    summary="Create a local browser voice session",
    description=(
        "Creates a local session record and initializes the LocalWebRTCProvider. "
        "The browser later negotiates SDP through /demo/connect."
    ),
    responses={
        503: {"model": ErrorResponse, "description": "OpenAI or provider configuration missing."},
        400: {"model": ErrorResponse, "description": "Structured application error."},
    },
)
async def create_demo_session(
    payload: DemoSessionRequest,
    db: Session = Depends(get_db),
    providers: dict[str, VoiceProvider] = Depends(get_provider_registry),
    rate_limit_service=Depends(get_rate_limit_service),
) -> DemoSessionResponse:
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)
    provider = providers["local_webrtc"]
    await rate_limit_service.check_call_allowed(bucket="demo:session")

    session = session_manager.create_session(provider="local_webrtc", to_number=None, status="created")
    provider_result = await provider.create_call(
        None,
        {"call_session_id": session.id, "initial_message": payload.initial_message},
    )
    session = session_manager.mark_initiated(session, provider_result)
    for event in provider_result.get("events", []):
        session_manager.record_event(
            event_type=str(event.get("event_type", "provider_event")),
            payload=event.get("payload", {}),
            call_session_id=session.id,
        )

    return DemoSessionResponse(
        ok=True,
        call_session_id=session.id,
        provider=session.provider,
        status=session.status,
        room_id=session.room_id,
        realtime=None,
        connection_mode="server_sdp_proxy",
        warnings=[],
    )


@router.post(
    "/demo/connect",
    response_model=DemoConnectResponse,
    summary="Negotiate browser WebRTC SDP with OpenAI Realtime",
    description=(
        "Accepts a browser SDP offer and proxies the negotiation to OpenAI Realtime using the server API key. "
        "This avoids exposing standard API credentials in the browser."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Call session not found."},
        503: {"model": ErrorResponse, "description": "OpenAI Realtime is not configured."},
        502: {"model": ErrorResponse, "description": "Realtime SDP negotiation failed."},
    },
)
async def connect_demo_session(
    payload: DemoConnectRequest,
    db: Session = Depends(get_db),
    agent: RealtimeVoiceAgent = Depends(get_agent),
) -> DemoConnectResponse:
    session = db.get(VoiceCallSession, payload.call_session_id)
    if not session:
        raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

    answer_sdp = await agent.create_realtime_sdp_answer(payload.offer_sdp, payload.initial_message)
    return DemoConnectResponse(ok=True, answer_sdp=answer_sdp)


@router.post(
    "/demo/events",
    response_model=DemoEventResponse,
    summary="Store demo/browser events",
    description="Accepts browser-side local demo events and optional transcript chunks for persistence.",
    responses={404: {"model": ErrorResponse, "description": "Call session not found."}},
)
async def store_demo_event(
    payload: DemoEventRequest,
    db: Session = Depends(get_db),
    transcript_service: TranscriptService = Depends(get_transcript_service),
) -> DemoEventResponse:
    summary_service = SummaryService()
    session_manager = SessionManager(db, summary_service)
    session = db.get(VoiceCallSession, payload.call_session_id)
    if not session:
        raise AppError("CALL_NOT_FOUND", "Call session not found.", status_code=404)

    session_manager.record_event(payload.event_type, payload.payload, call_session_id=payload.call_session_id)
    if payload.transcript_text:
        transcript_service.append_text(db, payload.call_session_id, payload.transcript_text)
    return DemoEventResponse(ok=True, stored=True)

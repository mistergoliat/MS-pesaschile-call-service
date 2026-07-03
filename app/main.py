from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import Settings, get_settings
from app.core.agent import RealtimeVoiceAgent
from app.core.exceptions import AppError
from app.db.database import build_engine, build_session_factory
from app.db.migrations import run_mvp_migrations
from app.providers import build_provider_registry
from app.schemas.errors import ErrorResponse
from app.services.compliance_service import ComplianceService
from app.services.rate_limit_service import RateLimitService
from app.services.summary_service import SummaryService
from app.services.transcript_service import TranscriptService


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(app_settings.database_url)
        session_factory = build_session_factory(engine)
        run_mvp_migrations(engine)

        agent = RealtimeVoiceAgent(app_settings)
        summary_service = SummaryService()
        app.state.settings = app_settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.agent = agent
        app.state.summary_service = summary_service
        app.state.transcript_service = TranscriptService()
        app.state.compliance_service = ComplianceService(app_settings)
        app.state.rate_limit_service = RateLimitService(app_settings.max_calls_per_minute)
        app.state.providers = build_provider_registry(app_settings, agent)
        yield
        engine.dispose()

    app = FastAPI(
        title="Voice Agent Service",
        description=(
            "Microservicio modular para agentes de voz con provider abstraction, "
            "LiveKit SIP readiness, OpenAI Realtime y Meta WhatsApp Calling placeholder."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logging.getLogger("voice-agent-service").warning(
            "application_error",
            extra={"path": request.url.path, "error": exc.error, "detail": exc.detail},
        )
        payload = ErrorResponse(error=exc.error, detail=exc.detail, payload=exc.payload)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("voice-agent-service").exception("unhandled_exception")
        payload = ErrorResponse(
            error="INTERNAL_SERVER_ERROR",
            detail="The service encountered an unexpected error.",
        )
        return JSONResponse(status_code=500, content=payload.model_dump(mode="json"))

    app.include_router(api_router)
    return app


app = create_app()

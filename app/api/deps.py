from fastapi import Request

from app.config import Settings
from app.core.agent import RealtimeVoiceAgent
from app.providers.base import VoiceProvider
from app.services.deepseek_service import DeepSeekService
from app.services.compliance_service import ComplianceService
from app.services.rate_limit_service import RateLimitService
from app.services.summary_service import SummaryService
from app.services.transcript_service import TranscriptService


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_agent(request: Request) -> RealtimeVoiceAgent:
    return request.app.state.agent


def get_deepseek_service(request: Request) -> DeepSeekService:
    return request.app.state.deepseek_service


def get_provider_registry(request: Request) -> dict[str, VoiceProvider]:
    return request.app.state.providers


def get_compliance_service(request: Request) -> ComplianceService:
    return request.app.state.compliance_service


def get_rate_limit_service(request: Request) -> RateLimitService:
    return request.app.state.rate_limit_service


def get_transcript_service(request: Request) -> TranscriptService:
    return request.app.state.transcript_service


def get_summary_service(request: Request) -> SummaryService:
    return request.app.state.summary_service

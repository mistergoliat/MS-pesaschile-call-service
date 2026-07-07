from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="voice-agent-service", alias="APP_NAME")
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", alias="ENVIRONMENT"
    )
    port: int = Field(default=8000, alias="PORT")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")

    database_url: str = Field(default="sqlite:///./voice_agent.db", alias="DATABASE_URL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_realtime_model: str = Field(default="gpt-realtime", alias="OPENAI_REALTIME_MODEL")
    openai_input_transcription_model: str = Field(
        default="gpt-4o-mini-transcribe", alias="OPENAI_INPUT_TRANSCRIPTION_MODEL"
    )
    openai_tts_model: str = Field(default="gpt-4o-mini-tts", alias="OPENAI_TTS_MODEL")
    openai_tts_voice: str = Field(default="ash", alias="OPENAI_TTS_VOICE")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    agent_system_prompt: str = Field(
        default=(
            "Eres un agente de voz de prueba. "
            "Se breve, claro y confirma que esta llamada es una prueba tecnica autorizada."
        ),
        alias="AGENT_SYSTEM_PROMPT",
    )

    allowed_test_number: str = Field(default="+569XXXXXXXX", alias="ALLOWED_TEST_NUMBER")
    max_calls_per_minute: int = Field(default=3, alias="MAX_CALLS_PER_MINUTE")

    livekit_url: str = Field(default="", alias="LIVEKIT_URL")
    livekit_api_key: str = Field(default="", alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", alias="LIVEKIT_API_SECRET")
    livekit_sip_trunk_id: str = Field(default="", alias="LIVEKIT_SIP_TRUNK_ID")
    livekit_agent_name: str = Field(default="voice-agent-service", alias="LIVEKIT_AGENT_NAME")
    voice_agent_api_base_url: str = Field(default="http://localhost:8000", alias="VOICE_AGENT_API_BASE_URL")
    cors_allowed_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )

    meta_whatsapp_access_token: str = Field(default="", alias="META_WHATSAPP_ACCESS_TOKEN")
    meta_whatsapp_phone_number_id: str = Field(default="", alias="META_WHATSAPP_PHONE_NUMBER_ID")
    meta_whatsapp_app_secret: str = Field(default="", alias="META_WHATSAPP_APP_SECRET")
    meta_whatsapp_verify_token: str = Field(default="", alias="META_WHATSAPP_VERIFY_TOKEN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        origins = {origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()}
        origins.add(self.public_base_url.rstrip("/"))
        parsed = urlparse(self.public_base_url)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()

from __future__ import annotations

from livekit.plugins import openai

from app.config import Settings
from app.core.exceptions import AppError


class LiveKitVoiceModelFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_llm(self):
        if not self.settings.deepseek_api_key:
            raise AppError(
                "DEEPSEEK_NOT_CONFIGURED",
                "Missing DEEPSEEK_API_KEY. Configure it to use DeepSeek as the LiveKit agent LLM.",
                status_code=503,
            )

        return openai.LLM.with_deepseek(model=self.settings.deepseek_model)

    def build_stt(self):
        if not self.settings.openai_api_key:
            raise AppError(
                "OPENAI_NOT_CONFIGURED",
                "Missing OPENAI_API_KEY. Configure it to enable OpenAI STT for the LiveKit voice pipeline.",
                status_code=503,
            )

        return openai.STT(
            model=self.settings.openai_input_transcription_model,
            language="es",
        )

    def build_tts(self):
        if not self.settings.openai_api_key:
            raise AppError(
                "OPENAI_NOT_CONFIGURED",
                "Missing OPENAI_API_KEY. Configure it to enable OpenAI TTS for the LiveKit voice pipeline.",
                status_code=503,
            )

        return openai.TTS(
            model=self.settings.openai_tts_model,
            voice=self.settings.openai_tts_voice,
            instructions="Habla en espanol de Chile, de forma breve, natural y clara.",
        )

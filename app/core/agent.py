from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.exceptions import AppError
from app.core.prompts import BASE_AGENT_PROMPT


class RealtimeVoiceAgent:
    TERMINATION_PHRASES = {
        "cortar",
        "terminar",
        "no quiero seguir",
        "finalizar",
        "cuelga",
        "cuelgue",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def system_prompt(self) -> str:
        return f"{BASE_AGENT_PROMPT}\n\n{self.settings.agent_system_prompt}".strip()

    def should_terminate(self, text: str | None) -> bool:
        if not text:
            return False
        lowered = text.strip().lower()
        return any(phrase in lowered for phrase in self.TERMINATION_PHRASES)

    def ensure_configured(self) -> None:
        if not self.settings.openai_api_key:
            raise AppError(
                "OPENAI_NOT_CONFIGURED",
                "Missing OPENAI_API_KEY. Configure it to enable OpenAI Realtime voice sessions.",
                status_code=503,
            )

    def build_realtime_session_payload(self, initial_message: str | None = None) -> dict[str, Any]:
        instructions = self.system_prompt
        if initial_message:
            instructions = f"{instructions}\n\nMensaje inicial sugerido: {initial_message}"

        return {
            "session": {
                "type": "realtime",
                "model": self.settings.openai_realtime_model,
                "instructions": instructions,
                "audio": {
                    "input": {
                        "turn_detection": {
                            "type": "server_vad",
                            "interrupt_response": True,
                            "create_response": True,
                        },
                        "transcription": {
                            "model": self.settings.openai_input_transcription_model,
                            "language": "es",
                        },
                    },
                    "output": {"voice": "marin"},
                },
            }
        }

    async def create_client_secret(self, initial_message: str | None = None) -> dict[str, Any]:
        self.ensure_configured()

        payload = self.build_realtime_session_payload(initial_message)
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise AppError(
                "OPENAI_REALTIME_SESSION_ERROR",
                "OpenAI Realtime client secret request failed.",
                status_code=502,
                payload=response.text,
            )

        return response.json()

    async def create_realtime_sdp_answer(self, offer_sdp: str, initial_message: str | None = None) -> str:
        self.ensure_configured()
        client_secret_payload = await self.create_client_secret(initial_message)
        ephemeral_key = (
            client_secret_payload.get("client_secret", {}).get("value")
            or client_secret_payload.get("value")
        )
        if not ephemeral_key:
            raise AppError(
                "OPENAI_REALTIME_SESSION_ERROR",
                "OpenAI Realtime client secret response did not include a usable ephemeral key.",
                status_code=502,
                payload=client_secret_payload,
            )
        headers = {
            "Authorization": f"Bearer {ephemeral_key}",
            "Content-Type": "application/sdp",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/calls",
                headers=headers,
                content=offer_sdp,
            )

        if response.status_code >= 400:
            raise AppError(
                "OPENAI_REALTIME_CONNECT_ERROR",
                "OpenAI Realtime SDP negotiation failed.",
                status_code=502,
                payload=response.text,
            )
        return response.text

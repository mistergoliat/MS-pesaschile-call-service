from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.exceptions import AppError
from app.schemas.chat import ChatMessage


class DeepSeekService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _ensure_configured(self) -> None:
        if not self.settings.deepseek_api_key:
            raise AppError(
                "DEEPSEEK_NOT_CONFIGURED",
                "Missing DEEPSEEK_API_KEY. Configure it to test a conversation with DeepSeek.",
                status_code=503,
            )

    async def chat(self, message: str, history: list[ChatMessage] | None = None, system_prompt: str | None = None) -> dict[str, Any]:
        self._ensure_configured()
        messages: list[dict[str, str]] = []
        effective_system_prompt = system_prompt or self.settings.agent_system_prompt
        if effective_system_prompt:
            messages.append({"role": "system", "content": effective_system_prompt})
        for turn in history or []:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise AppError(
                "DEEPSEEK_CHAT_ERROR",
                "DeepSeek chat completion request failed.",
                status_code=502,
                payload=response.text,
            )

        data = response.json()
        try:
            reply = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                "DEEPSEEK_CHAT_ERROR",
                "DeepSeek response did not include a usable assistant message.",
                status_code=502,
                payload=data,
            ) from exc

        return {
            "model": data.get("model", self.settings.deepseek_model),
            "reply": reply,
            "raw": data,
        }

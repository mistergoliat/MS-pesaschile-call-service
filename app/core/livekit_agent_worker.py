from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.core.livekit_voice_models import LiveKitVoiceModelFactory

logger = logging.getLogger("voice-agent-service.livekit-agent")
WHATSAPP_AGENT_PROMPT = (
    "Eres el asistente virtual de Pesas Chile. Esta es una prueba técnica autorizada de llamadas por WhatsApp. "
    "Debes indicar claramente que eres un asistente virtual. Habla en español de Chile, de forma breve, clara y natural. "
    "No inventes precios, stock, condiciones de despacho ni políticas comerciales. No realices ventas. "
    "Si el usuario pide terminar, despídete y finaliza la llamada."
)
WHATSAPP_AGENT_GREETING = (
    "Hola, soy el asistente virtual de Pesas Chile. Esta es una prueba técnica de llamadas por WhatsApp. "
    "¿Me escuchas bien?"
)


def _parse_room_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid_room_metadata", extra={"raw": "<redacted>"})
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_text_from_item(item: Any) -> str | None:
    text = getattr(item, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    content = getattr(item, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            candidate = getattr(part, "text", None) or getattr(part, "transcript", None)
            if isinstance(candidate, str) and candidate.strip():
                parts.append(candidate.strip())
        if parts:
            return " ".join(parts)
    return None


async def _post_call_event(settings, call_session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    url = f"{settings.voice_agent_api_base_url.rstrip('/')}/calls/{call_session_id}/events"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"event_type": event_type, **payload})
        response.raise_for_status()


async def _end_call_after_timeout(settings, call_session_id: str, timeout_seconds: int) -> None:
    if timeout_seconds <= 0:
        return

    try:
        await asyncio.sleep(timeout_seconds)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.voice_agent_api_base_url.rstrip('/')}/calls/end",
                json={"call_session_id": call_session_id},
            )
            response.raise_for_status()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning(
            "auto_disconnect_failed",
            extra={"call_session_id": call_session_id, "error": str(exc)},
        )


def build_server():
    from livekit import agents
    from livekit.agents import Agent, AgentServer, AgentSession, ConversationItemAddedEvent, UserInputTranscribedEvent

    settings = get_settings()
    server = AgentServer()
    model_factory = LiveKitVoiceModelFactory(settings)

    class WhatsAppAssistant(Agent):
        def __init__(self) -> None:
            super().__init__(instructions=WHATSAPP_AGENT_PROMPT)

    @server.rtc_session(agent_name=settings.livekit_agent_name)
    async def voice_agent_entrypoint(ctx: agents.JobContext) -> None:
        room_metadata = _parse_room_metadata(getattr(ctx.room, "metadata", None))
        call_session_id = room_metadata.get("call_session_id")
        initial_message = room_metadata.get("initial_message") or WHATSAPP_AGENT_GREETING
        max_duration_seconds = int(
            room_metadata.get("max_duration_seconds") or settings.whatsapp_calling_max_duration_seconds
        )

        session = AgentSession(
            llm=model_factory.build_llm(),
            stt=model_factory.build_stt(),
            tts=model_factory.build_tts(),
        )

        @session.on("user_input_transcribed")
        def on_user_input_transcribed(event: UserInputTranscribedEvent) -> None:
            if call_session_id and event.transcript:
                asyncio.create_task(
                    _post_call_event(
                        settings,
                        call_session_id,
                        "user_input_transcribed",
                        {
                            "payload": {
                                "language": event.language,
                                "is_final": event.is_final,
                            },
                            "transcript_text": f"Usuario: {event.transcript}",
                            "final": event.is_final,
                        },
                    )
                )

        @session.on("conversation_item_added")
        def on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
            role = getattr(event.item, "role", None)
            text = _extract_text_from_item(event.item)
            if call_session_id and role == "assistant" and text:
                asyncio.create_task(
                    _post_call_event(
                        settings,
                        call_session_id,
                        "agent_response_completed",
                        {
                            "payload": {"role": role},
                            "transcript_text": f"Agente: {text}",
                            "final": True,
                        },
                    )
                )

        @session.on("close")
        def on_close(_: Any) -> None:
            if call_session_id:
                asyncio.create_task(
                    _post_call_event(
                        settings,
                        call_session_id,
                        "agent_session_closed",
                        {"payload": {"room": getattr(ctx.room, "name", None)}},
                    )
                )

        await ctx.connect()
        await session.start(room=ctx.room, agent=WhatsAppAssistant())

        if call_session_id:
            asyncio.create_task(_end_call_after_timeout(settings, call_session_id, max_duration_seconds))
            await _post_call_event(
                settings,
                call_session_id,
                "agent_joined_room",
                {"payload": {"room_name": getattr(ctx.room, "name", None)}},
            )

        await session.generate_reply(instructions=initial_message)

    return server


def main() -> None:
    from livekit import agents

    server = build_server()
    agents.cli.run_app(server)


if __name__ == "__main__":
    main()

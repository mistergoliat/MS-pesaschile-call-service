from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, ConversationItemAddedEvent, UserInputTranscribedEvent
from livekit.plugins import openai

from app.config import get_settings

logger = logging.getLogger("voice-agent-service.livekit-agent")
settings = get_settings()
server = AgentServer()


class VoiceTestAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=settings.agent_system_prompt)


def _parse_room_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid_room_metadata", extra={"raw": raw})
        return {}


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


async def _post_call_event(call_session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    url = f"{settings.voice_agent_api_base_url.rstrip('/')}/calls/{call_session_id}/events"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"event_type": event_type, **payload})
        response.raise_for_status()


@server.rtc_session()
async def voice_agent_entrypoint(ctx: agents.JobContext) -> None:
    room_metadata = _parse_room_metadata(getattr(ctx.room, "metadata", None))
    call_session_id = room_metadata.get("call_session_id")
    initial_message = room_metadata.get("initial_message") or (
        "Hola, esta es una prueba tecnica autorizada. En que te puedo ayudar?"
    )

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=settings.openai_realtime_model,
            voice="marin",
        )
    )

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event: UserInputTranscribedEvent) -> None:
        if call_session_id and event.transcript:
            asyncio.create_task(
                _post_call_event(
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
                    call_session_id,
                    "agent_session_closed",
                    {"payload": {"room": getattr(ctx.room, "name", None)}},
                )
            )

    await ctx.connect()
    await session.start(room=ctx.room, agent=VoiceTestAssistant())

    if call_session_id:
        await _post_call_event(
            call_session_id,
            "agent_joined_room",
            {"payload": {"room_name": getattr(ctx.room, "name", None)}},
        )

    await session.generate_reply(instructions=initial_message)


if __name__ == "__main__":
    agents.cli.run_app(server)

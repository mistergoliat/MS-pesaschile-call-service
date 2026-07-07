from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = Field(..., description="Chat role.")
    content: str = Field(..., description="Message content.")


class DemoChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to DeepSeek.")
    history: list[ChatMessage] = Field(default_factory=list, description="Optional prior conversation history.")
    system_prompt: str | None = Field(
        default=None,
        description="Optional system prompt override for the test conversation.",
    )


class DemoChatResponse(BaseModel):
    ok: bool = True
    model: str
    reply: str

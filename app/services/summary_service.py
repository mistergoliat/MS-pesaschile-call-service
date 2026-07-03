from __future__ import annotations

import json
from typing import Any


class SummaryService:
    def build_summary(self, transcript_text: str | None, status: str) -> dict[str, Any]:
        if transcript_text:
            preview = transcript_text.strip().splitlines()[:3]
            user_intent = preview[-1] if preview else "prueba tecnica"
        else:
            user_intent = "prueba tecnica sin transcript"

        call_outcome = "completed" if status in {"completed", "ended"} else "failed"
        return {
            "call_outcome": call_outcome,
            "user_intent": user_intent,
            "key_points": ["Sesion de prueba autorizada del agente de voz."],
            "next_action": "Revisar transcript y ajustar configuracion del provider si hace falta.",
            "requires_human": False,
            "risk_flags": [] if call_outcome == "completed" else ["provider_or_flow_review"],
        }

    def serialize(self, summary: dict[str, Any]) -> str:
        return json.dumps(summary, ensure_ascii=True)

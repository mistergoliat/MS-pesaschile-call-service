from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
REDACT_KEYS = {
    "access_token",
    "app_secret",
    "authorization",
    "challenge",
    "secret",
    "signature",
    "sdp",
    "token",
    "verify_token",
    "whatsapp_api_key",
}


def normalize_phone_number(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.lower().startswith("whatsapp:"):
        normalized = normalized.split(":", 1)[1]
    if normalized.lower().startswith("tel:"):
        normalized = normalized.split(":", 1)[1]
    normalized = re.sub(r"[()\s-]+", "", normalized)
    return normalized or None


def is_e164_number(value: str | None) -> bool:
    normalized = normalize_phone_number(value)
    return bool(normalized and E164_PATTERN.match(normalized))


def build_room_name(call_id: str) -> str:
    digest = hashlib.sha256(call_id.encode("utf-8")).hexdigest()[:24]
    return f"wa-call-{digest}"


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header or not app_secret:
        return False

    try:
        signature_version, signature_hex = signature_header.split("=", 1)
    except ValueError:
        return False

    if signature_version.lower() != "sha256":
        return False

    expected_signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature_hex.strip())


def _sanitize_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in REDACT_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {child_key: _sanitize_value(child_key, child_value) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]
    if isinstance(value, str) and len(value) > 160:
        return f"{value[:80]}...<trimmed>"
    return value


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: _sanitize_value(key, value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


@dataclass(slots=True)
class MetaWhatsAppCallEvent:
    event_type: str
    call_id: str | None
    caller: str | None
    phone_number_id: str | None
    sdp: str | None
    sdp_type: str | None
    raw_summary: dict[str, Any]


def extract_meta_call_events(payload: dict[str, Any]) -> list[MetaWhatsAppCallEvent]:
    events: list[MetaWhatsAppCallEvent] = []
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return events

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue

            call_items: list[dict[str, Any]] = []
            calls = value.get("calls")
            if isinstance(calls, list):
                call_items.extend([call for call in calls if isinstance(call, dict)])
            single_call = value.get("call")
            if isinstance(single_call, dict):
                call_items.append(single_call)

            for call in call_items:
                session = call.get("session", {})
                if not isinstance(session, dict):
                    session = {}

                event_type = str(
                    call.get("event")
                    or call.get("action")
                    or change.get("field")
                    or value.get("event")
                    or ""
                ).strip().lower()
                call_id = call.get("call_id") or call.get("id") or value.get("call_id")
                caller = normalize_phone_number(
                    call.get("from")
                    or call.get("caller")
                    or value.get("from")
                    or value.get("caller")
                )
                phone_number_id = str(
                    call.get("phone_number_id") or value.get("phone_number_id") or ""
                ).strip() or None
                sdp_type = str(session.get("sdp_type") or call.get("sdp_type") or "").strip() or None
                sdp = session.get("sdp") or call.get("sdp")
                raw_summary = redact_payload(
                    {
                        "object": payload.get("object"),
                        "entry_id": entry.get("id"),
                        "field": change.get("field"),
                        "event": event_type,
                        "call_id": call_id,
                        "caller": caller,
                        "phone_number_id": phone_number_id,
                        "sdp_type": sdp_type,
                        "session_present": bool(session),
                        "has_sdp": bool(sdp),
                    }
                )
                events.append(
                    MetaWhatsAppCallEvent(
                        event_type=event_type,
                        call_id=str(call_id).strip() if call_id else None,
                        caller=caller,
                        phone_number_id=phone_number_id,
                        sdp=str(sdp).strip() if isinstance(sdp, str) and sdp.strip() else None,
                        sdp_type=sdp_type,
                        raw_summary=raw_summary,
                    )
                )

    return events


def sanitize_meta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_payload(payload)
    if isinstance(sanitized, dict):
        return sanitized
    return {"payload": sanitized}

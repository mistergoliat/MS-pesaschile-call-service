from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from livekit import api as livekit_api

from app.config import get_settings
from app.core.exceptions import AppError
from app.core.whatsapp_calling import build_room_name
from app.main import create_app
from app.models.call_event import VoiceCallEvent
from app.models.call_session import VoiceCallSession


@pytest.fixture()
def whatsapp_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'whatsapp.db'}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("LIVEKIT_URL", "https://livekit.example")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "lk-secret")
    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "whatsapp-agent")
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "meta-token")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "1030337916832905")
    monkeypatch.setenv("META_WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setenv("META_WHATSAPP_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("META_WHATSAPP_CLOUD_API_VERSION", "v24.0")
    monkeypatch.setenv("WHATSAPP_CALLING_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_CALLING_TEST_MODE", "true")
    monkeypatch.setenv("WHATSAPP_CALLING_ALLOWED_CALLERS", "+56911111111")
    monkeypatch.setenv("WHATSAPP_CALLING_MAX_DURATION_SECONDS", "120")
    monkeypatch.setenv("INTERNAL_WEBHOOK_SECRET", "internal-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.com")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _make_payload(
    *,
    call_id: str = "wacid.12345",
    caller: str = "+56911111111",
    phone_number_id: str = "1030337916832905",
    event: str = "connect",
    sdp: str | None = "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n",
) -> dict[str, object]:
    call_item: dict[str, object] = {
        "event": event,
        "from": caller,
        "call_id": call_id,
        "phone_number_id": phone_number_id,
        "session": {"sdp_type": "offer"},
    }
    if sdp is not None:
        call_item["session"]["sdp"] = sdp

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "calls",
                        "value": {
                            "phone_number_id": phone_number_id,
                            "display_phone_number": "+56 9 2175 7996",
                            "calls": [call_item],
                        },
                    }
                ],
            }
        ],
    }


def _sign_payload(secret: str, body: bytes) -> str:
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def _dump_body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _events_for_session(test_client: TestClient, call_session_id: str) -> list[VoiceCallEvent]:
    session_factory = test_client.app.state.session_factory
    with session_factory() as db:
        return (
            db.execute(
                select(VoiceCallEvent).where(VoiceCallEvent.call_session_id == call_session_id).order_by(VoiceCallEvent.created_at)
            )
            .scalars()
            .all()
        )


def _get_session(test_client: TestClient, call_id: str) -> VoiceCallSession:
    session_factory = test_client.app.state.session_factory
    with session_factory() as db:
        return db.execute(select(VoiceCallSession).where(VoiceCallSession.external_call_id == call_id)).scalar_one()


def test_meta_webhook_verification_succeeds(whatsapp_client: TestClient) -> None:
    response = whatsapp_client.get(
        "/webhooks/meta/whatsapp-calling",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_meta_webhook_verification_rejects_wrong_token(whatsapp_client: TestClient) -> None:
    response = whatsapp_client.get(
        "/webhooks/meta/whatsapp-calling",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == "META_WHATSAPP_WEBHOOK_VERIFICATION_FAILED"


def test_meta_signature_valid_connect_event_dispatches_agent(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    captured: dict[str, object] = {}

    async def fake_accept_inbound_call(
        *,
        call_id: str,
        sdp: str,
        room_name: str,
        caller: str | None = None,
        phone_number_id: str | None = None,
        agents: list[object] | None = None,
    ) -> dict[str, object]:
        captured.update(
            {
                "call_id": call_id,
                "sdp": sdp,
                "room_name": room_name,
                "caller": caller,
                "phone_number_id": phone_number_id,
                "agents": agents or [],
            }
        )
        return {
            "status": "active",
            "room_id": room_name,
            "external_call_id": call_id,
        }

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)

    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "accepted"}
    assert captured["call_id"] == "wacid.12345"
    assert captured["caller"] == "+56911111111"
    assert captured["phone_number_id"] == "1030337916832905"
    assert captured["room_name"] == build_room_name("wacid.12345")
    assert captured["sdp"].startswith("v=0")
    assert len(captured["agents"]) == 1
    assert getattr(captured["agents"][0], "agent_name") == "whatsapp-agent"

    session = _get_session(whatsapp_client, "wacid.12345")
    assert session.provider == "livekit_whatsapp"
    assert session.direction == "inbound"
    assert session.from_number == "+56911111111"
    assert session.to_number == "+56921757996"
    assert session.room_id == build_room_name("wacid.12345")
    assert session.status == "active"

    event_types = [event.event_type for event in _events_for_session(whatsapp_client, session.id)]
    assert "inbound_call_validated" in event_types
    assert "livekit_accept_requested" in event_types
    assert "livekit_call_accepted" in event_types
    assert "agent_dispatched" in event_types

    session_factory = whatsapp_client.app.state.session_factory
    with session_factory() as db:
        global_event_types = [row.event_type for row in db.execute(select(VoiceCallEvent)).scalars().all()]
    assert "meta_call_webhook_received" in global_event_types


def test_meta_signature_invalid_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("wrong-secret", body)},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "META_WHATSAPP_SIGNATURE_INVALID"


def test_internal_secret_valid_routes_event(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    captured: dict[str, object] = {}

    async def fake_accept_inbound_call(
        *,
        call_id: str,
        sdp: str,
        room_name: str,
        caller: str | None = None,
        phone_number_id: str | None = None,
        agents: list[object] | None = None,
    ) -> dict[str, object]:
        captured["call_id"] = call_id
        captured["room_name"] = room_name
        return {"status": "active", "room_id": room_name, "external_call_id": call_id}

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)

    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Internal-Webhook-Secret": "internal-secret"},
    )

    assert response.status_code == 200
    assert captured["call_id"] == "wacid.12345"


def test_internal_secret_invalid_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Internal-Webhook-Secret": "wrong-secret"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "WEBHOOK_AUTH_REQUIRED"


def test_allowlisted_caller_is_accepted(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]

    async def fake_accept_inbound_call(**kwargs: object) -> dict[str, object]:
        call_id = kwargs["call_id"]
        room_name = kwargs["room_name"]
        return {"status": "active", "room_id": room_name, "external_call_id": call_id}

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)

    payload = _make_payload(caller="+56911111111")
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 200


def test_blocked_caller_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload(caller="+56922222222")
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "META_WHATSAPP_CALLER_BLOCKED"


def test_feature_flag_off_rejects_webhook(
    whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(whatsapp_client.app.state.settings, "whatsapp_calling_enabled", False)
    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "WHATSAPP_CALLING_DISABLED"


def test_wrong_phone_number_id_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload(phone_number_id="999999999999999")
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "META_WHATSAPP_PHONE_NUMBER_ID_MISMATCH"


def test_missing_call_id_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload()
    payload["entry"][0]["changes"][0]["value"]["calls"][0].pop("call_id")
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "META_WHATSAPP_CALL_ID_MISSING"


def test_missing_sdp_is_rejected(whatsapp_client: TestClient) -> None:
    payload = _make_payload(sdp=None)
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "META_WHATSAPP_SDP_MISSING"


def test_duplicate_connect_event_is_idempotent(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    calls: list[str] = []

    async def fake_accept_inbound_call(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["call_id"]))
        room_name = str(kwargs["room_name"])
        return {"status": "active", "room_id": room_name, "external_call_id": str(kwargs["call_id"])}

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)

    payload = _make_payload()
    body = _dump_body(payload)
    headers = {"X-Hub-Signature-256": _sign_payload("app-secret", body)}

    first = whatsapp_client.post("/webhooks/meta/whatsapp-calling", content=body, headers=headers)
    second = whatsapp_client.post("/webhooks/meta/whatsapp-calling", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["wacid.12345"]

    session = _get_session(whatsapp_client, "wacid.12345")
    assert session.status == "active"


def test_livekit_error_is_recorded(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]

    async def fake_accept_inbound_call(**kwargs: object) -> dict[str, object]:
        raise AppError("LIVEKIT_CALL_ACCEPT_FAILED", "boom", status_code=502)

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)

    payload = _make_payload()
    body = _dump_body(payload)
    response = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", body)},
    )

    assert response.status_code == 502
    assert response.json()["error"] == "LIVEKIT_CALL_ACCEPT_FAILED"

    session = _get_session(whatsapp_client, "wacid.12345")
    assert session.status == "failed"
    event_types = [event.event_type for event in _events_for_session(whatsapp_client, session.id)]
    assert "inbound_call_failed" in event_types


def test_terminate_event_disconnects_whatsapp_call(
    whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    disconnected: list[str] = []

    async def fake_accept_inbound_call(**kwargs: object) -> dict[str, object]:
        room_name = str(kwargs["room_name"])
        return {"status": "active", "room_id": room_name, "external_call_id": str(kwargs["call_id"])}

    async def fake_disconnect_call(call_id: str) -> dict[str, str]:
        disconnected.append(call_id)
        return {"status": "terminated"}

    monkeypatch.setattr(provider, "accept_inbound_call", fake_accept_inbound_call)
    monkeypatch.setattr(provider, "disconnect_call", fake_disconnect_call)

    payload = _make_payload()
    body = _dump_body(payload)
    headers = {"X-Hub-Signature-256": _sign_payload("app-secret", body)}
    first = whatsapp_client.post("/webhooks/meta/whatsapp-calling", content=body, headers=headers)
    assert first.status_code == 200

    terminate_payload = _make_payload(event="terminate", sdp=None)
    terminate_body = _dump_body(terminate_payload)
    terminate = whatsapp_client.post(
        "/webhooks/meta/whatsapp-calling",
        content=terminate_body,
        headers={"X-Hub-Signature-256": _sign_payload("app-secret", terminate_body)},
    )

    assert terminate.status_code == 200
    assert disconnected == ["wacid.12345"]

    session = _get_session(whatsapp_client, "wacid.12345")
    assert session.status == "terminated"
    assert session.ended_at is not None
    assert session.duration_seconds is not None

    event_types = [event.event_type for event in _events_for_session(whatsapp_client, session.id)]
    assert "inbound_call_terminated" in event_types


def test_diagnostics_do_not_expose_secrets(whatsapp_client: TestClient) -> None:
    response = whatsapp_client.get("/diagnostics/whatsapp-calling")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "enabled": True,
        "test_mode": True,
        "meta_configured": True,
        "livekit_configured": True,
        "deepseek_configured": True,
        "openai_speech_configured": True,
        "agent_name": "whatsapp-agent",
        "allowed_callers_count": 1,
        "webhook_url": "https://voice.example.com/webhooks/meta/whatsapp-calling",
    }
    assert "meta-token" not in response.text
    assert "app-secret" not in response.text


@pytest.mark.anyio
async def test_accept_whatsapp_call_invoked_correctly(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    captured: dict[str, object] = {}

    class FakeConnector:
        async def accept_whatsapp_call(self, request: object) -> object:
            captured["request"] = request
            return type("Response", (), {"room_name": "room-accepted"})()

    class FakeLiveKitClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.connector = FakeConnector()

        async def __aenter__(self) -> "FakeLiveKitClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "app.providers.meta_whatsapp_calling.livekit_api.LiveKitAPI",
        FakeLiveKitClient,
    )

    result = await provider.accept_inbound_call(
        call_id="wacid.12345",
        sdp="v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n",
        room_name="wa-call-room",
        caller="+56911111111",
        phone_number_id="1030337916832905",
        agents=[livekit_api.RoomAgentDispatch(agent_name="whatsapp-agent")],
    )

    request = captured["request"]
    assert getattr(request, "whatsapp_phone_number_id") == "1030337916832905"
    assert getattr(request, "whatsapp_api_key") == "meta-token"
    assert getattr(request, "whatsapp_cloud_api_version") == "v24.0"
    assert getattr(request, "whatsapp_call_id") == "wacid.12345"
    assert getattr(request, "sdp").sdp.startswith("v=0")
    assert getattr(request, "sdp").type == "offer"
    assert getattr(request, "room_name") == "wa-call-room"
    assert getattr(request.agents[0], "agent_name") == "whatsapp-agent"
    assert result["room_id"] == "room-accepted"


@pytest.mark.anyio
async def test_disconnect_whatsapp_call_invoked_correctly(
    whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]
    captured: dict[str, object] = {}

    class FakeConnector:
        async def disconnect_whatsapp_call(self, request: object) -> object:
            captured["request"] = request
            return object()

    class FakeLiveKitClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.connector = FakeConnector()

        async def __aenter__(self) -> "FakeLiveKitClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "app.providers.meta_whatsapp_calling.livekit_api.LiveKitAPI",
        FakeLiveKitClient,
    )

    result = await provider.disconnect_call("wacid.12345")

    request = captured["request"]
    assert getattr(request, "whatsapp_call_id") == "wacid.12345"
    assert getattr(request, "disconnect_reason") == livekit_api.DisconnectWhatsAppCallRequest.USER_INITIATED
    assert result == {"status": "terminated"}


@pytest.mark.anyio
async def test_livekit_error_is_wrapped(whatsapp_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = whatsapp_client.app.state.providers["meta_whatsapp"]

    class FakeConnector:
        async def accept_whatsapp_call(self, request: object) -> object:
            raise RuntimeError("upstream failed")

    class FakeLiveKitClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.connector = FakeConnector()

        async def __aenter__(self) -> "FakeLiveKitClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "app.providers.meta_whatsapp_calling.livekit_api.LiveKitAPI",
        FakeLiveKitClient,
    )

    with pytest.raises(AppError) as exc_info:
        await provider.accept_inbound_call(
            call_id="wacid.12345",
            sdp="v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n",
            room_name="wa-call-room",
            caller="+56911111111",
            phone_number_id="1030337916832905",
        )

    assert exc_info.value.error == "LIVEKIT_CALL_ACCEPT_FAILED"

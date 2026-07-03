from sqlalchemy import select

from app.models.call_event import VoiceCallEvent


def test_demo_page_loads(client):
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Demo local de voz sin carrier" in response.text


def test_demo_session_works_without_openai_key(client):
    response = client.post("/demo/session", json={"initial_message": "Hola demo."})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "local_webrtc"
    assert payload["call_session_id"]
    assert payload["connection_mode"] == "server_sdp_proxy"
    assert payload["warnings"] == []


def test_demo_connect_fails_cleanly_without_openai_key(client):
    session_response = client.post("/demo/session", json={"initial_message": "Hola demo."})
    call_session_id = session_response.json()["call_session_id"]

    response = client.post(
        "/demo/connect",
        json={
            "call_session_id": call_session_id,
            "offer_sdp": "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\n",
            "initial_message": "Hola demo.",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"] == "OPENAI_NOT_CONFIGURED"


def test_events_are_registered_for_local_call(client):
    response = client.post("/calls/test", json={"provider": "local_webrtc"})
    call_session_id = response.json()["call_session_id"]

    session_factory = client.app.state.session_factory
    with session_factory() as db:
        event_rows = db.execute(
            select(VoiceCallEvent).where(VoiceCallEvent.call_session_id == call_session_id)
        ).scalars().all()

    event_types = {row.event_type for row in event_rows}
    assert "call_requested" in event_types
    assert "session_created" in event_types
    assert "media_started" in event_types


def test_internal_call_event_ingestion_appends_transcript(client):
    response = client.post("/calls/test", json={"provider": "local_webrtc"})
    call_session_id = response.json()["call_session_id"]

    ingest = client.post(
        f"/calls/{call_session_id}/events",
        json={
            "event_type": "agent_response_completed",
            "payload": {"source": "test"},
            "transcript_text": "Agente: hola desde test",
            "final": True,
            "status": "active",
        },
    )

    assert ingest.status_code == 200

    status_response = client.get(f"/calls/{call_session_id}")
    payload = status_response.json()
    assert payload["status"] == "active"

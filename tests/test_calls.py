def test_local_webrtc_creates_session(client):
    response = client.post(
        "/calls/test",
        json={"provider": "local_webrtc", "initial_message": "Hola desde test local."},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "local_webrtc"
    assert payload["status"] == "initiated"
    assert payload["room_id"].startswith("local-")


def test_provider_unknown_is_rejected(client):
    response = client.post("/calls/test", json={"provider": "carrier_x"})

    assert response.status_code == 422


def test_livekit_fails_cleanly_if_missing_config(client):
    response = client.post(
        "/calls/test",
        json={"provider": "livekit", "to": "+56911111111"},
    )

    assert response.status_code == 503
    assert response.json()["error"] == "LIVEKIT_NOT_CONFIGURED"


def test_meta_whatsapp_not_implemented(client):
    response = client.post("/calls/test", json={"provider": "meta_whatsapp"})

    assert response.status_code == 501
    assert response.json()["error"] == "WHATSAPP_CALLING_OUTBOUND_DISABLED"


def test_call_status_returns_session(client):
    create_response = client.post("/calls/test", json={"provider": "local_webrtc"})
    call_session_id = create_response.json()["call_session_id"]

    status_response = client.get(f"/calls/{call_session_id}")

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["id"] == call_session_id
    assert payload["provider"] == "local_webrtc"


def test_call_end_updates_status(client):
    create_response = client.post("/calls/test", json={"provider": "local_webrtc"})
    call_session_id = create_response.json()["call_session_id"]

    end_response = client.post("/calls/end", json={"call_session_id": call_session_id})

    assert end_response.status_code == 200
    payload = end_response.json()
    assert payload["status"] == "ended"

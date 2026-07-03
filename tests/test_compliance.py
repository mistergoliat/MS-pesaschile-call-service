from app.models.suppression import VoiceSuppressionList


def test_disallow_non_authorized_number(client):
    response = client.post(
        "/calls/test",
        json={"provider": "livekit", "to": "+56922222222"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "OUTBOUND_CALL_BLOCKED"


def test_disallow_malformed_number(client):
    response = client.post(
        "/calls/test",
        json={"provider": "livekit", "to": "56922222222"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_PHONE_NUMBER"


def test_suppression_list_blocks_number(client):
    session_factory = client.app.state.session_factory
    with session_factory() as db:
        db.add(VoiceSuppressionList(phone_normalized="+56911111111", reason="test"))
        db.commit()

    response = client.post(
        "/calls/test",
        json={"provider": "livekit", "to": "+56911111111"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "NUMBER_SUPPRESSED"


def test_rate_limit_blocks_after_maximum(client):
    for _ in range(3):
        response = client.post("/calls/test", json={"provider": "local_webrtc"})
        assert response.status_code == 201

    blocked = client.post("/calls/test", json={"provider": "local_webrtc"})
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "RATE_LIMIT_EXCEEDED"

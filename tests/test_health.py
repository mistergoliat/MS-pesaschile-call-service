def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "voice-agent-service",
        "status": "healthy",
    }


def test_docs_returns_swagger_ui_html(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text


def test_openapi_schema_available(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "Voice Agent Service"
    assert "/calls/test" in payload["paths"]

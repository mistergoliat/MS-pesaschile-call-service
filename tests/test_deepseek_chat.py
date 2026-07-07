from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture()
def deepseek_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ALLOWED_TEST_NUMBER", "+56941386038")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.delenv("LIVEKIT_SIP_TRUNK_ID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_demo_chat_requires_deepseek_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.delenv("LIVEKIT_SIP_TRUNK_ID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/demo/chat", json={"message": "Hola"})

    get_settings.cache_clear()

    assert response.status_code == 503
    assert response.json()["error"] == "DEEPSEEK_NOT_CONFIGURED"


def test_demo_chat_uses_deepseek_model(deepseek_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": "Hola, esta es una prueba tecnica autorizada.",
                        }
                    }
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["init_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, headers: dict[str, str] | None = None, json: dict[str, object] | None = None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["json"] = json or {}
            return FakeResponse()

    monkeypatch.setattr("app.services.deepseek_service.httpx.AsyncClient", FakeAsyncClient)

    response = deepseek_client.post(
        "/demo/chat",
        json={
            "message": "Hola DeepSeek",
            "system_prompt": "Responde corto.",
            "history": [{"role": "assistant", "content": "Mensaje previo"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["reply"] == "Hola, esta es una prueba tecnica autorizada."
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert captured["json"]["messages"][0]["content"] == "Responde corto."
    assert captured["json"]["messages"][1]["role"] == "assistant"
    assert captured["json"]["messages"][2]["role"] == "user"

"""Regression coverage for specialist selection and exhausted greeting retries."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orion.server.app import create_app
from orion.server.chat_models import model_purpose


def engine_for(content="Hello! How can I help?"):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.list_models.return_value = ["moondream:latest", "qwen3.5:4b"]
    engine.generate.return_value = {"content": content, "usage": {}, "finish_reason": "stop"}

    async def stream(*args, **kwargs):
        yield content

    engine.stream = stream
    return engine


@pytest.mark.parametrize("stream", [False, True])
def test_specialist_uses_configured_chat_model(stream):
    engine = engine_for()
    app = create_app(engine, "qwen3.5:4b")
    response = TestClient(app).post("/v1/chat/completions", json={
        "model": "moondream:latest", "messages": [{"role": "user", "content": "Hey Orion"}], "stream": stream,
    })
    assert response.status_code == 200
    assert '"model":"qwen3.5:4b"' in response.text or '"model": "qwen3.5:4b"' in response.text
    assert "Hello! How can I help?" in response.text


@pytest.mark.parametrize("stream", [False, True])
def test_repeated_echo_never_reaches_user_even_with_agent(stream):
    engine = engine_for("Hey Orion")
    agent = MagicMock()
    agent.accepts_tools = True
    app = create_app(engine, "qwen3.5:4b", agent=agent)
    response = TestClient(app).post("/v1/chat/completions", json={
        "model": "qwen3.5:4b", "messages": [{"role": "user", "content": "Hey Orion"}], "stream": stream,
    })
    assert response.status_code == 502
    assert "select another chat model" in response.json()["detail"]
    assert "Hey Orion" not in response.text
    agent.run.assert_not_called()


def test_no_chat_model_does_not_silently_select_another_specialist():
    engine = engine_for()
    engine.list_models.return_value = ["moondream:latest"]
    client = TestClient(create_app(engine, "moondream:latest"))
    response = client.post("/v1/chat/completions", json={
        "model": "moondream:latest", "messages": [{"role": "user", "content": "Hello"}],
    })
    assert response.status_code == 400
    engine.generate.assert_not_called()


def test_models_label_specialists_without_excluding_multimodal_chat():
    client = TestClient(create_app(engine_for(), "qwen3.5:4b"))
    models = client.get("/v1/models").json()["data"]
    assert [(m["id"], m["purpose"]) for m in models] == [("moondream:latest", "vision"), ("qwen3.5:4b", "chat")]
    assert model_purpose("llama3.2-vision:latest") == "chat"
    assert model_purpose("nomic-embed-text:latest") == "embedding"


def test_specialist_cannot_be_saved_as_default():
    client = TestClient(create_app(engine_for(), "qwen3.5:4b"))
    assert client.post("/v1/config", json={"model": "moondream:latest"}).status_code == 400

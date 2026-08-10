import sys
from types import SimpleNamespace

import pytest

from engine.contracts import CompletionRequest
from engine.models import ModelConfig
from engine.provider import OpenAIProvider, _normalize_openai_base_url


def _request(
    model: str, base_url: str, openai_api: str = "chat_completions"
) -> CompletionRequest:
    return CompletionRequest(
        system="Return JSON only.",
        messages=[{"role": "user", "content": "Return an object."}],
        model=ModelConfig(
            provider="openai",
            model=model,
            base_url=base_url,
            openai_api=openai_api,
            temperature=0.2,
            top_p=0.9,
            max_tokens=123,
        ),
        metadata={"node_id": "intake"},
    )


def _install_fake_openai(monkeypatch):
    calls = {"clients": [], "chat": [], "responses": []}

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls["chat"].append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
            )

    class FakeResponses:
        def create(self, **kwargs):
            calls["responses"].append(kwargs)
            return iter(
                [
                    SimpleNamespace(
                        type="response.output_text.delta", delta='{"ok":'
                    ),
                    SimpleNamespace(type="response.output_text.delta", delta="true}"),
                    SimpleNamespace(
                        type="response.completed",
                        response=SimpleNamespace(
                            output_text='{"ok":true}',
                            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
                        ),
                    ),
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["clients"].append(kwargs)
            self.chat = SimpleNamespace(completions=FakeChatCompletions())
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    return calls


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1"),
        ("https://gateway.example/openai/v1/responses/", "https://gateway.example/openai/v1"),
        ("https://gateway.example/openai/v1", "https://gateway.example/openai/v1"),
        (None, None),
    ],
)
def test_openai_base_url_accepts_api_root_or_full_endpoint(value, expected):
    assert _normalize_openai_base_url(value) == expected


def test_official_reasoning_model_uses_supported_chat_parameters(monkeypatch):
    calls = _install_fake_openai(monkeypatch)

    OpenAIProvider("secret").complete(
        _request("gpt-5.6-luna", "https://api.openai.com/v1/chat/completions")
    )

    assert calls["clients"][0]["base_url"] == "https://api.openai.com/v1"
    assert "default_headers" not in calls["clients"][0]
    assert "max_retries" not in calls["clients"][0]
    request = calls["chat"][0]
    assert request["model"] == "gpt-5.6-luna"
    assert request["max_completion_tokens"] == 123
    assert "max_tokens" not in request
    assert "temperature" not in request
    assert "top_p" not in request


def test_compatible_gateway_uses_root_user_agent_and_legacy_parameters(
    monkeypatch,
):
    calls = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("FOUNDRY_OPENAI_COMPAT_USER_AGENT", "curl/8.0")

    OpenAIProvider("secret").complete(
        _request("gpt-5.6-sol", "https://fishappedu.online/v1/chat/completions")
    )

    client = calls["clients"][0]
    assert client["base_url"] == "https://fishappedu.online/v1"
    assert client["default_headers"] == {"User-Agent": "curl/8.0"}
    assert client["max_retries"] == 0
    request = calls["chat"][0]
    assert request["model"] == "gpt-5.6-sol"
    assert request["max_tokens"] == 123
    assert request["temperature"] == 0.2
    assert request["top_p"] == 0.9
    assert "max_completion_tokens" not in request


def test_compatible_gateway_can_stream_responses_api(monkeypatch):
    calls = _install_fake_openai(monkeypatch)

    result = OpenAIProvider("secret").complete(
        _request(
            "gpt-5.6-sol",
            "https://fishappedu.online/v1/responses",
            openai_api="responses",
        )
    )

    assert calls["chat"] == []
    request = calls["responses"][0]
    assert request == {
        "model": "gpt-5.6-sol",
        "instructions": "Return JSON only.",
        "input": [{"role": "user", "content": "Return an object."}],
        "stream": True,
        "max_output_tokens": 123,
    }
    assert result.text == '{"ok":true}'
    assert result.usage == {"input_tokens": 5, "output_tokens": 3}
    assert result.provider_metadata == {
        "requested_model": "gpt-5.6-sol",
        "openai_api": "responses",
        "streamed": True,
    }


def test_official_responses_api_requests_json_object_format(monkeypatch):
    calls = _install_fake_openai(monkeypatch)

    OpenAIProvider("secret").complete(
        _request(
            "gpt-5.6-sol",
            "https://api.openai.com/v1",
            openai_api="responses",
        )
    )

    assert calls["responses"][0]["text"] == {
        "format": {"type": "json_object"}
    }


@pytest.mark.parametrize("value", ["", " ", "bad\nagent", "bad\ragent"])
def test_compatible_gateway_rejects_invalid_user_agent(monkeypatch, value):
    _install_fake_openai(monkeypatch)
    monkeypatch.setenv("FOUNDRY_OPENAI_COMPAT_USER_AGENT", value)

    with pytest.raises(RuntimeError, match="non-empty single-line"):
        OpenAIProvider("secret").complete(
            _request("custom-model", "https://gateway.example/v1")
        )

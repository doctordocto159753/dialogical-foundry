import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from engine.contracts import CompletionRequest
from engine.models import ModelConfig
from engine.provider import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderHTTPError,
)

RESEARCH_JSON = json.dumps(
    {"delta_only": False, "findings": [], "overall_notes": "normalized"}
)


def request(provider, model, **model_overrides):
    return CompletionRequest(
        system="Research carefully and cite sources.",
        messages=[{"role": "user", "content": "Research exact model routing."}],
        model=ModelConfig(
            provider=provider,
            model=model,
            mode=model_overrides.pop("mode", "standard"),
            **model_overrides,
        ),
        metadata={"node_id": "researcher", "iteration": 0},
    )


def install_http_transport(monkeypatch, handler):
    original_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "engine.provider.httpx.Client",
        lambda *args, **kwargs: original_client(*args, transport=transport, **kwargs),
    )


def test_gemini_standard_sends_exact_model_and_node_base_url(monkeypatch):
    seen = {}

    def handler(outbound):
        seen["request"] = outbound
        seen["payload"] = json.loads(outbound.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": RESEARCH_JSON}]}}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3},
            },
        )

    install_http_transport(monkeypatch, handler)
    model_id = "gemini-custom-preview-007"
    result = GeminiProvider("gemini-secret").complete(
        request(
            "gemini",
            model_id,
            base_url="https://gemini-gateway.example/v1beta",
            top_k=17,
            top_p=0.42,
        )
    )

    assert seen["request"].url.path == f"/v1beta/models/{model_id}:generateContent"
    assert seen["request"].headers["x-goog-api-key"] == "gemini-secret"
    assert seen["payload"]["generationConfig"]["topK"] == 17
    assert seen["payload"]["generationConfig"]["responseJsonSchema"]["required"] == [
        "delta_only",
        "findings",
        "overall_notes",
    ]
    assert "$schema" not in seen["payload"]["generationConfig"]["responseJsonSchema"]
    assert result.provider_metadata["requested_model"] == model_id


def test_gemini_deep_research_uses_exact_agent_persists_and_normalizes(monkeypatch):
    requests = []

    def handler(outbound):
        payload = json.loads(outbound.content) if outbound.content else None
        requests.append((outbound.method, outbound.url.path, payload))
        if outbound.method == "POST" and outbound.url.path.endswith("/interactions"):
            return httpx.Response(200, json={"id": "interaction-1", "status": "in_progress"})
        if outbound.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "interaction-1",
                    "status": "completed",
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [{"type": "text", "text": "raw cited report"}],
                        }
                    ],
                    "usage": {"total_input_tokens": 100, "total_output_tokens": 20},
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": RESEARCH_JSON}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            },
        )

    install_http_transport(monkeypatch, handler)
    checkpoints = []
    agent_id = "deep-research-custom-agent-42"
    completion_request = request(
        "gemini",
        agent_id,
        mode="deep_research",
        normalization_model="gemini-normalizer-exact",
        base_url="https://gemini-gateway.example/v1beta",
        research_poll_interval_seconds=0,
        research_visualization=True,
    )
    completion_request.operation_checkpoint = lambda value: checkpoints.append(value)

    result = GeminiProvider("secret").complete(completion_request)

    assert requests[0][2]["agent"] == agent_id
    assert requests[0][2]["store"] is True
    assert "system_instruction" not in requests[0][2]
    assert requests[0][2]["input"].startswith(
        "SYSTEM INSTRUCTIONS:\nResearch carefully and cite sources."
    )
    assert requests[0][2]["agent_config"]["visualization"] == "auto"
    assert checkpoints[0]["remote_id"] == "interaction-1"
    assert checkpoints[-1]["raw_report"] == "raw cited report"
    assert requests[-1][1].endswith(
        "/models/gemini-normalizer-exact:generateContent"
    )
    assert result.usage == {"input_tokens": 110, "output_tokens": 25}


def test_gemini_http_error_includes_provider_response_body(monkeypatch):
    def handler(_outbound):
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "store=true is required for background interactions.",
                    "code": "invalid_request",
                }
            },
        )

    install_http_transport(monkeypatch, handler)
    completion_request = request(
        "gemini",
        "deep-research-preview-04-2026",
        mode="deep_research",
        normalization_model="gemini-2.5-flash",
        research_poll_interval_seconds=0,
    )

    with pytest.raises(ProviderHTTPError, match="store=true is required") as caught:
        GeminiProvider("secret").complete(completion_request)

    assert caught.value.status_code == 400
    assert caught.value.retryable is False


def test_gemini_resume_polls_existing_interaction_without_creating_another(monkeypatch):
    methods_and_paths = []

    def handler(outbound):
        methods_and_paths.append((outbound.method, outbound.url.path))
        if outbound.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "saved-id",
                    "status": "completed",
                    "steps": [{"type": "model_output", "content": [{"type": "text", "text": "saved report"}]}],
                },
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": RESEARCH_JSON}]}}]},
        )

    install_http_transport(monkeypatch, handler)
    completion_request = request(
        "gemini",
        "deep-agent-exact",
        mode="deep_research",
        normalization_model="normalizer-exact",
        base_url="https://gemini.example/v1beta",
        research_poll_interval_seconds=0,
    )
    completion_request.operation_state = {
        "provider": "gemini",
        "node_id": "researcher",
        "iteration": 0,
        "model": "deep-agent-exact",
        "base_url": "https://gemini.example/v1beta",
        "remote_id": "saved-id",
        "status": "in_progress",
    }

    GeminiProvider("secret").complete(completion_request)

    assert methods_and_paths[0] == (
        "GET",
        "/v1beta/interactions/saved-id",
    )
    assert not any(
        method == "POST" and path.endswith("/interactions")
        for method, path in methods_and_paths
    )


def test_openai_deep_research_uses_responses_and_exact_models(monkeypatch):
    calls = {"create": [], "retrieve": [], "chat": [], "clients": []}

    class FakeResponses:
        def create(self, **kwargs):
            calls["create"].append(kwargs)
            return SimpleNamespace(id="resp-1", status="in_progress")

        def retrieve(self, response_id):
            calls["retrieve"].append(response_id)
            return SimpleNamespace(
                id=response_id,
                status="completed",
                output_text="raw OpenAI report",
                usage=SimpleNamespace(input_tokens=80, output_tokens=30),
            )

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls["chat"].append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=RESEARCH_JSON))],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["clients"].append(kwargs)
            self.responses = FakeResponses()
            self.chat = SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    checkpoints = []
    completion_request = request(
        "openai",
        "o3-deep-research-exact",
        mode="deep_research",
        normalization_model="gpt-normalizer-exact",
        base_url="https://openai-gateway.example/v1",
        research_poll_interval_seconds=0,
        research_max_tool_calls=13,
    )
    completion_request.operation_checkpoint = lambda value: checkpoints.append(value)

    result = OpenAIProvider("secret").complete(completion_request)

    assert calls["create"][0]["model"] == "o3-deep-research-exact"
    assert calls["create"][0]["max_tool_calls"] == 13
    assert calls["create"][0]["tools"] == [{"type": "web_search_preview"}]
    assert calls["chat"][0]["model"] == "gpt-normalizer-exact"
    assert all(client["base_url"] == "https://openai-gateway.example/v1" for client in calls["clients"])
    assert checkpoints[0]["remote_id"] == "resp-1"
    assert result.provider_metadata["requested_model"] == "o3-deep-research-exact"


def test_anthropic_deep_research_uses_server_web_search_and_exact_models(monkeypatch):
    calls = {"messages": [], "clients": []}

    class FakeMessages:
        def create(self, **kwargs):
            calls["messages"].append(kwargs)
            call_number = len(calls["messages"])
            if call_number == 1:
                block = SimpleNamespace(type="text", text="partial", citations=[])
                stop_reason = "pause_turn"
            elif call_number == 2:
                citation = SimpleNamespace(
                    title="Primary source",
                    url="https://source.example/report",
                    cited_text="supporting excerpt",
                )
                block = SimpleNamespace(
                    type="text", text="raw Anthropic report", citations=[citation]
                )
                stop_reason = "end_turn"
            else:
                block = SimpleNamespace(type="text", text=RESEARCH_JSON, citations=[])
                stop_reason = "end_turn"
            return SimpleNamespace(
                content=[block],
                usage=SimpleNamespace(input_tokens=6, output_tokens=3),
                stop_reason=stop_reason,
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls["clients"].append(kwargs)
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))
    completion_request = request(
        "anthropic",
        "claude-research-exact",
        mode="deep_research",
        normalization_model="claude-normalizer-exact",
        base_url="https://claude-gateway.example",
        research_max_tool_calls=11,
    )

    result = AnthropicProvider("secret").complete(completion_request)

    assert calls["messages"][0]["model"] == "claude-research-exact"
    assert calls["messages"][0]["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 11}
    ]
    assert calls["messages"][1]["messages"][-1]["role"] == "assistant"
    assert calls["messages"][2]["model"] == "claude-normalizer-exact"
    assert "https://source.example/report" in result.provider_metadata["raw_report"]
    assert all(client["base_url"] == "https://claude-gateway.example" for client in calls["clients"])

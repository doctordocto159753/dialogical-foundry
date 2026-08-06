"""Provider adapters. Secrets are injected at call time and never persisted."""
from __future__ import annotations

import json
import math
import os
import time
from abc import ABC, abstractmethod
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv

from .contracts import CompletionRequest, CompletionResult, schema_for

DEFAULT_LLM_TIMEOUT_SECONDS = 30 * 60

# A root .env is convenient for native runs. Existing process variables always
# win, and Docker Compose passes the same values into the container explicitly.
load_dotenv(Path.cwd() / ".env", override=False)
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _timeout_seconds() -> float:
    raw_timeout = os.environ.get(
        "FOUNDRY_LLM_TIMEOUT_SECONDS", str(DEFAULT_LLM_TIMEOUT_SECONDS)
    )
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise RuntimeError("FOUNDRY_LLM_TIMEOUT_SECONDS must be a positive number") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RuntimeError("FOUNDRY_LLM_TIMEOUT_SECONDS must be a positive number")
    return timeout_seconds


def _resolve_base_url(
    explicit_base_url: str | None, base_url_env: str, default: str | None = None
) -> str | None:
    explicit = (explicit_base_url or "").strip()
    if explicit:
        return explicit.rstrip("/")
    configured = os.environ.get(base_url_env, "").strip()
    if configured:
        return configured.rstrip("/")
    return default.rstrip("/") if default else None


def _client_options(
    base_url_env: str,
    explicit_base_url: str | None = None,
    timeout_seconds_override: float | None = None,
) -> dict[str, Any]:
    timeout_seconds = (
        float(timeout_seconds_override)
        if timeout_seconds_override is not None
        else _timeout_seconds()
    )
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RuntimeError("request timeout must be a positive number")

    options: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout_seconds, connect=min(30.0, timeout_seconds))
    }
    base_url = _resolve_base_url(explicit_base_url, base_url_env)
    if base_url:
        options["base_url"] = base_url
    return options


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    """Turn a pasted OpenAI endpoint URL into the API root expected by the SDK."""
    if not base_url:
        return None
    normalized = base_url.rstrip("/")
    for endpoint_suffix in ("/chat/completions", "/responses"):
        if normalized.lower().endswith(endpoint_suffix):
            normalized = normalized[: -len(endpoint_suffix)].rstrip("/")
            break
    return normalized


def _openai_base_url(explicit_base_url: str | None) -> str | None:
    return _normalize_openai_base_url(
        _resolve_base_url(explicit_base_url, "OPENAI_BASE_URL")
    )


def _is_official_openai_base_url(base_url: str | None) -> bool:
    if base_url is None:
        return True
    return (urlsplit(base_url).hostname or "").lower() == "api.openai.com"


def _openai_compat_user_agent() -> str:
    value = os.environ.get("FOUNDRY_OPENAI_COMPAT_USER_AGENT", "curl/8.0").strip()
    if not value or "\r" in value or "\n" in value:
        raise RuntimeError(
            "FOUNDRY_OPENAI_COMPAT_USER_AGENT must be a non-empty single-line value"
        )
    return value


def _openai_reasoning_chat_parameters(model: str, base_url: str | None) -> bool:
    """Official reasoning-family Chat Completions use a reduced parameter set."""
    if not _is_official_openai_base_url(base_url):
        return False
    normalized_model = model.lower()
    return normalized_model.startswith(("gpt-5", "o1", "o3", "o4"))


def _openai_reasoning_model(model: str) -> bool:
    normalized_model = model.lower()
    return normalized_model.startswith(("gpt-5", "o1", "o3", "o4"))


def _research_prompt(request: CompletionRequest) -> str:
    return "\n\n".join(
        f"{message['role'].upper()}:\n{message['content']}" for message in request.messages
    )


def _operation_identity(
    request: CompletionRequest, provider: str, base_url: str | None
) -> dict[str, Any]:
    return {
        "provider": provider,
        "node_id": request.metadata.get("node_id"),
        "iteration": request.metadata.get("iteration"),
        "model": request.model.model,
        "base_url": base_url,
    }


def _matching_operation(
    request: CompletionRequest, provider: str, base_url: str | None
) -> dict[str, Any] | None:
    state = request.operation_state
    identity = _operation_identity(request, provider, base_url)
    if state and all(state.get(key) == value for key, value in identity.items()):
        return dict(state)
    return None


def _save_operation(request: CompletionRequest, state: dict[str, Any]) -> None:
    if request.operation_checkpoint:
        request.operation_checkpoint(state)


def _report_progress(request: CompletionRequest, status: str, **payload: Any) -> None:
    if request.progress:
        request.progress(status, payload)


def _research_deadline(request: CompletionRequest) -> float:
    timeout = float(request.model.research_timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError("research_timeout_seconds must be a positive number")
    return time.monotonic() + timeout


def _poll_delay(request: CompletionRequest) -> float:
    delay = float(request.model.research_poll_interval_seconds)
    if not math.isfinite(delay) or delay < 0:
        raise RuntimeError("research_poll_interval_seconds must be zero or greater")
    return delay


def _normalization_request(request: CompletionRequest, report: str) -> CompletionRequest:
    model_name = request.model.normalization_model or ""
    if not model_name or model_name != model_name.strip():
        raise RuntimeError("a normalization model is required for deep research mode")
    model = replace(request.model, model=model_name, mode="standard")
    return CompletionRequest(
        system=(
            "You are a strict research-output normalizer. Convert the supplied report "
            "into the requested node JSON contract. Preserve source URLs and uncertainty. "
            "Do not invent evidence. Return JSON only."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"TARGET NODE: {request.metadata.get('node_id', 'researcher')}\n\n"
                    f"ORIGINAL CONTRACT AND INSTRUCTIONS:\n{request.system}\n\n"
                    f"RAW DEEP RESEARCH REPORT:\n{report}"
                ),
            }
        ],
        model=model,
        metadata=request.metadata,
    )


def _combined_result(
    normalized: CompletionResult,
    report: str,
    research_usage: dict[str, int],
    operation: dict[str, Any],
) -> CompletionResult:
    return CompletionResult(
        text=normalized.text,
        usage={
            "input_tokens": int(research_usage.get("input_tokens", 0))
            + int(normalized.usage.get("input_tokens", 0)),
            "output_tokens": int(research_usage.get("output_tokens", 0))
            + int(normalized.usage.get("output_tokens", 0)),
        },
        provider_metadata={
            "mode": "deep_research",
            "requested_model": operation["model"],
            "normalization_model": normalized.provider_metadata.get(
                "requested_model"
            ),
            "remote_id": operation.get("remote_id"),
            "raw_report": report,
        },
    )


_GEMINI_SCHEMA_KEYS = {
    "$id",
    "$defs",
    "$ref",
    "$anchor",
    "type",
    "format",
    "title",
    "description",
    "enum",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "anyOf",
    "oneOf",
    "properties",
    "additionalProperties",
    "required",
}


def _gemini_schema(node_id: str) -> dict[str, Any]:
    def clean(value: Any, parent_key: str | None = None) -> Any:
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        if parent_key == "properties":
            return {key: clean(item) for key, item in value.items()}
        return {
            key: clean(item, key)
            for key, item in value.items()
            if key in _GEMINI_SCHEMA_KEYS
        }

    return clean(schema_for(node_id))


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMProvider(ABC):
    supports_top_k: bool = True

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult: ...


def _mock_payload(node_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    iteration = (meta.get("iteration") or 0) + 1
    payloads: dict[str, dict[str, Any]] = {
        "intake": {"domain": "software", "goal": "Turn the submitted idea into a development-ready work package.", "context": "Normalized from the local intake.", "explicit_asks": ["Produce a complete plan"], "constraints": ["Local-first", "Planning only"], "artifacts_summary": [], "assumptions": [], "open_questions": []},
        "idea_generator": {"reframings": [{"lens": "job-to-be-done", "statement": "Help a builder turn ambiguity into executable scope."}], "directions": [{"id": "D-1", "name": "Guided foundry", "mechanism": "Specialized model dialogue", "user_value": "A reviewed plan", "key_bet": "Critique improves completeness", "must_be_true": ["Outputs remain traceable"], "boldness": "core"}], "adjacent_features": [], "open_questions": [], "shortlist": ["D-1"], "recommended_primary": "D-1", "reasoning": "It directly serves the brief.", "changes_from_last_pass": [f"Completed ideation pass {iteration}"]},
        "researcher": {"delta_only": iteration > 1, "findings": [{"direction_id": "D-1", "claim": "Structured review can expose gaps.", "evidence": [{"point": "Mock mode provides deterministic offline evidence.", "source_type": "inference", "source_ref": "mock://offline", "confidence": "med"}], "prior_art": [], "risks": ["Real research requires a configured search provider."], "feasibility_signal": "Feasible", "gaps": []}], "overall_notes": "Deterministic mock research; configure Tavily for live sources."},
        "judge": {"assessment_summary": "The direction is coherent and should retain explicit traceability.", "issues": [], "research_quality_notes": "Live evidence is required outside mock mode.", "keep_these_strengths": ["Clear pipeline boundary"], "verdict": "continue"},
        "judge_finalize": {"title": "Development-ready product definition", "problem": "The original idea needs a precise, reviewed definition.", "goals": ["Produce an executable work package"], "non_goals": ["Implement the target product"], "target_users": ["Product builders"], "user_needs": ["Clear scope and acceptance criteria"], "scope_mvp": [{"feature": "Structured planning pipeline", "priority": "P0", "rationale": "Core value"}], "out_of_scope": ["Target-product implementation"], "key_flows": [{"name": "Plan", "steps": ["Submit brief", "Review outputs", "Download work package"]}], "functional_requirements": [{"id": "FR-1", "requirement": "Produce a reviewed work package."}], "non_functional_requirements": [{"id": "NFR-1", "requirement": "Keep data local by default."}], "constraints": ["Local-first"], "assumptions": [], "risks": [{"risk": "Weak model output", "mitigation": "Validation and critique loops"}], "success_metrics": ["All four layers complete"], "open_questions": []},
        "architect": {"overview": "A local web app around a resumable orchestration engine.", "components": [{"name": "Engine", "responsibility": "Execute the pipeline", "depends_on": []}], "data_model": [{"entity": "Run", "fields": ["id", "status", "tokens"], "relations": []}], "interfaces": [{"name": "Run API", "kind": "api", "contract": "Create and observe runs"}], "tech_choices": [{"area": "Runtime", "choice": "Python and React", "rationale": "Matches constraints", "alternatives": []}], "cross_cutting": [{"concern": "Reliability", "approach": "Atomic checkpoints"}], "deployment": "Single local service", "key_decisions": [{"decision": "Structured artifacts", "tradeoffs": "More validation for predictable output"}], "local_first_to_server_path": "Add auth and tenant scopes.", "changes_from_last_pass": [f"Completed architecture pass {iteration}"]},
        "matcher": {"conformance": [{"prd_ref": "FR-1", "status": "covered", "evidence": "Run API and Engine", "required_fix": ""}], "over_engineering": [], "summary": "Architecture covers the mock PRD.", "verdict": "pass"},
        "task_writer": {"work_package_meta": {"title": "Implementation work package", "execution_note": "Execute in order."}, "tasks": [{"id": "T-001", "title": "Implement the core flow", "user_story": "As a builder I want the planned flow so that the product meets its definition.", "scope_note": "One reviewable vertical slice.", "acceptance_criteria": ["The documented flow succeeds"], "priority": "P0", "stack": "dev", "depends_on": [], "technical_notes": "Follow the architecture interfaces."}], "ordering_rationale": "Foundation first.", "coverage_note": "FR-1 is covered.", "changes_from_last_pass": [f"Completed work-package pass {iteration}"]},
        "wp_reviewer": {"issues": [], "coverage_gaps": [], "summary": "The mock work package is executable.", "verdict": "pass"},
    }
    return payloads.get(node_id, {"result": "ok"})


class MockProvider(LLMProvider):
    def __init__(self, supports_top_k: bool = True):
        super().__init__()
        self.supports_top_k = supports_top_k

    def complete(self, request: CompletionRequest) -> CompletionResult:
        node_id = request.metadata.get("node_id", "unknown")
        text = json.dumps(_mock_payload(node_id, request.metadata), ensure_ascii=False)
        source = request.system + "".join(item["content"] for item in request.messages)
        return CompletionResult(text=text, usage={"input_tokens": _est_tokens(source), "output_tokens": _est_tokens(text)})


class AnthropicProvider(LLMProvider):
    supports_top_k = True

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if request.model.mode == "deep_research":
            return self._complete_deep_research(request)
        return self._complete_standard(request)

    def _client(self, request: CompletionRequest):
        if not self.api_key:
            raise RuntimeError("Anthropic API key is not configured")
        import anthropic

        return anthropic.Anthropic(
            api_key=self.api_key,
            **_client_options(
                "ANTHROPIC_BASE_URL",
                request.model.base_url,
                request.model.research_timeout_seconds
                if request.model.mode == "deep_research"
                else None,
            ),
        )

    def _complete_standard(self, request: CompletionRequest) -> CompletionResult:
        client = self._client(request)
        kwargs: dict[str, Any] = {"model": request.model.model, "max_tokens": request.model.max_tokens, "temperature": request.model.temperature, "system": request.system, "messages": request.messages}
        if request.model.top_k is not None:
            kwargs["top_k"] = request.model.top_k
        if request.model.top_p is not None:
            kwargs["top_p"] = request.model.top_p
        response = client.messages.create(**kwargs)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return CompletionResult(
            text=text,
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            provider_metadata={"requested_model": request.model.model},
        )

    def _complete_deep_research(self, request: CompletionRequest) -> CompletionResult:
        base_url = _resolve_base_url(request.model.base_url, "ANTHROPIC_BASE_URL")
        operation = _matching_operation(request, "anthropic", base_url)
        if operation and operation.get("status") == "completed" and "raw_report" in operation:
            report = str(operation["raw_report"])
            research_usage = operation.get("usage", {})
        else:
            client = self._client(request)
            messages: list[Any] = list(request.messages)
            kwargs: dict[str, Any] = {
                "model": request.model.model,
                "max_tokens": request.model.max_tokens,
                "temperature": request.model.temperature,
                "system": request.system,
                "messages": messages,
                "tools": [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": request.model.research_max_tool_calls,
                    }
                ],
            }
            if request.model.top_k is not None:
                kwargs["top_k"] = request.model.top_k
            if request.model.top_p is not None:
                kwargs["top_p"] = request.model.top_p
            _report_progress(request, "started", provider="anthropic")
            total_input = 0
            total_output = 0
            for continuation in range(10):
                response = client.messages.create(**kwargs)
                total_input += int(response.usage.input_tokens)
                total_output += int(response.usage.output_tokens)
                if getattr(response, "stop_reason", None) != "pause_turn":
                    break
                _report_progress(
                    request,
                    "poll",
                    provider="anthropic",
                    continuation=continuation + 1,
                    remote_status="pause_turn",
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": response.content},
                ]
                kwargs["messages"] = messages
            else:
                raise RuntimeError("Anthropic web search exceeded 10 pause_turn continuations")
            report_parts: list[str] = []
            for block in response.content:
                if getattr(block, "type", "") != "text":
                    continue
                report_parts.append(block.text)
                for citation in getattr(block, "citations", None) or []:
                    title = getattr(citation, "title", "Source")
                    url = getattr(citation, "url", "")
                    cited_text = getattr(citation, "cited_text", "")
                    report_parts.append(f"\n[Source: {title} — {url}] {cited_text}")
            report = "".join(report_parts)
            research_usage = {
                "input_tokens": total_input,
                "output_tokens": total_output,
            }
            operation = {
                **_operation_identity(request, "anthropic", base_url),
                "status": "completed",
                "raw_report": report,
                "usage": research_usage,
            }
            _save_operation(request, operation)
            _report_progress(request, "completed", provider="anthropic")
        normalized = self._complete_standard(_normalization_request(request, report))
        return _combined_result(normalized, report, research_usage, operation)


class OpenAIProvider(LLMProvider):
    supports_top_k = False

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if request.model.mode == "deep_research":
            return self._complete_deep_research(request)
        return self._complete_standard(request)

    def _client(self, request: CompletionRequest):
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured")
        from openai import OpenAI

        base_url = _openai_base_url(request.model.base_url)
        options = _client_options(
            "",
            base_url,
            request.model.research_timeout_seconds
            if request.model.mode == "deep_research"
            else None,
        )
        if not _is_official_openai_base_url(base_url):
            options["default_headers"] = {
                "User-Agent": _openai_compat_user_agent()
            }
            # Foundry owns the visible node retry loop. Disabling the SDK's hidden
            # retries avoids multiplying a gateway timeout into nine HTTP attempts.
            options["max_retries"] = 0
        return OpenAI(api_key=self.api_key, **options)

    def _complete_standard(self, request: CompletionRequest) -> CompletionResult:
        if request.model.openai_api == "responses":
            return self._complete_responses_stream(request)
        if request.model.openai_api != "chat_completions":
            raise RuntimeError(f"unsupported OpenAI API transport: {request.model.openai_api}")
        return self._complete_chat_completions(request)

    def _complete_chat_completions(self, request: CompletionRequest) -> CompletionResult:
        base_url = _openai_base_url(request.model.base_url)
        kwargs: dict[str, Any] = {
            "model": request.model.model,
            "messages": [
                {"role": "system", "content": request.system},
                *request.messages,
            ],
            "response_format": {"type": "json_object"},
        }
        if _openai_reasoning_chat_parameters(request.model.model, base_url):
            kwargs["max_completion_tokens"] = request.model.max_tokens
        else:
            kwargs.update(
                temperature=request.model.temperature,
                top_p=request.model.top_p if request.model.top_p is not None else 1,
                max_tokens=request.model.max_tokens,
            )
        response = self._client(request).chat.completions.create(**kwargs)
        text = response.choices[0].message.content or "{}"
        usage = response.usage
        return CompletionResult(
            text=text,
            usage={"input_tokens": usage.prompt_tokens if usage else 0, "output_tokens": usage.completion_tokens if usage else 0},
            provider_metadata={
                "requested_model": request.model.model,
                "openai_api": "chat_completions",
            },
        )

    def _complete_responses_stream(self, request: CompletionRequest) -> CompletionResult:
        base_url = _openai_base_url(request.model.base_url)
        kwargs: dict[str, Any] = {
            "model": request.model.model,
            "instructions": request.system,
            "input": request.messages,
            "stream": True,
        }
        if _is_official_openai_base_url(base_url):
            kwargs["text"] = {"format": {"type": "json_object"}}
        if request.model.max_tokens is not None:
            kwargs["max_output_tokens"] = request.model.max_tokens
        if not _openai_reasoning_model(request.model.model):
            kwargs["temperature"] = request.model.temperature
            if request.model.top_p is not None:
                kwargs["top_p"] = request.model.top_p

        chunks: list[str] = []
        finalized_text = ""
        final_response = None
        stream = self._client(request).responses.create(**kwargs)
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                chunks.append(str(getattr(event, "delta", "")))
            elif event_type == "response.output_text.done":
                finalized_text = str(getattr(event, "text", ""))
            elif event_type == "response.completed":
                final_response = getattr(event, "response", None)
            elif event_type in {"response.failed", "response.incomplete"}:
                response = getattr(event, "response", None)
                detail = getattr(response, "error", None) or getattr(
                    response, "incomplete_details", None
                )
                raise RuntimeError(f"OpenAI Responses stream ended with {event_type}: {detail}")
            elif event_type == "error":
                raise RuntimeError(
                    f"OpenAI Responses stream error: {getattr(event, 'message', 'unknown error')}"
                )

        text = "".join(chunks)
        if not text:
            text = finalized_text or str(getattr(final_response, "output_text", "") or "")
        if not text:
            raise RuntimeError("OpenAI Responses stream completed without text output")
        usage = getattr(final_response, "usage", None)
        return CompletionResult(
            text=text,
            usage={
                "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            },
            provider_metadata={
                "requested_model": request.model.model,
                "openai_api": "responses",
                "streamed": True,
            },
        )

    def _complete_deep_research(self, request: CompletionRequest) -> CompletionResult:
        base_url = _openai_base_url(request.model.base_url)
        operation = _matching_operation(request, "openai", base_url)
        client = self._client(request)
        deadline = _research_deadline(request)
        if operation and operation.get("status") == "completed" and "raw_report" in operation:
            report = str(operation["raw_report"])
            research_usage = operation.get("usage", {})
        else:
            if not operation:
                response = client.responses.create(
                    model=request.model.model,
                    instructions=request.system,
                    input=_research_prompt(request),
                    background=True,
                    tools=[{"type": "web_search_preview"}],
                    max_tool_calls=request.model.research_max_tool_calls,
                )
                operation = {
                    **_operation_identity(request, "openai", base_url),
                    "remote_id": response.id,
                    "status": response.status,
                }
                _save_operation(request, operation)
                _report_progress(
                    request,
                    "started",
                    provider="openai",
                    remote_id=response.id,
                    remote_status=response.status,
                )
            else:
                response = client.responses.retrieve(operation["remote_id"])
            while response.status in {"queued", "in_progress"}:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "OpenAI deep research exceeded research_timeout_seconds"
                    )
                _report_progress(
                    request,
                    "poll",
                    provider="openai",
                    remote_id=response.id,
                    remote_status=response.status,
                )
                delay = _poll_delay(request)
                if delay:
                    time.sleep(delay)
                response = client.responses.retrieve(response.id)
            if response.status != "completed":
                operation = {**operation, "status": response.status}
                _save_operation(request, operation)
                raise RuntimeError(
                    f"OpenAI deep research ended with status {response.status!r}"
                )
            report = response.output_text or ""
            usage = response.usage
            research_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            }
            operation = {
                **operation,
                "status": "completed",
                "raw_report": report,
                "usage": research_usage,
            }
            _save_operation(request, operation)
            _report_progress(
                request,
                "completed",
                provider="openai",
                remote_id=response.id,
            )
        normalized = self._complete_standard(_normalization_request(request, report))
        return _combined_result(normalized, report, research_usage, operation)


class GeminiProvider(LLMProvider):
    supports_top_k = True

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if request.model.mode == "deep_research":
            return self._complete_deep_research(request)
        return self._complete_standard(request)

    def _base_url(self, request: CompletionRequest) -> str:
        return _resolve_base_url(
            request.model.base_url,
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ) or ""

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts if "text" in part)

    @staticmethod
    def _interaction_text(payload: dict[str, Any]) -> str:
        for step in reversed(payload.get("steps", [])):
            if step.get("type") != "model_output":
                continue
            chunks = [
                str(item.get("text", ""))
                for item in step.get("content", [])
                if item.get("type") == "text"
            ]
            if any(chunks):
                return "\n\n".join(chunk for chunk in chunks if chunk)
        raise RuntimeError("Gemini interaction returned no text output")

    def _complete_standard(self, request: CompletionRequest) -> CompletionResult:
        base_url = self._base_url(request)
        model_segment = quote(request.model.model, safe="")
        url = f"{base_url}/models/{model_segment}:generateContent"
        generation: dict[str, Any] = {
            "temperature": request.model.temperature,
            "maxOutputTokens": request.model.max_tokens,
            "responseMimeType": "application/json",
            "responseJsonSchema": _gemini_schema(
                str(request.metadata.get("node_id", "researcher"))
            ),
        }
        if request.model.top_k is not None:
            generation["topK"] = request.model.top_k
        if request.model.top_p is not None:
            generation["topP"] = request.model.top_p
        contents = [
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in request.messages
        ]
        with httpx.Client(timeout=_client_options("GEMINI_BASE_URL")["timeout"]) as client:
            response = client.post(
                url,
                headers=self._headers(),
                json={
                    "systemInstruction": {"parts": [{"text": request.system}]},
                    "contents": contents,
                    "generationConfig": generation,
                },
            )
            response.raise_for_status()
            payload = response.json()
        usage = payload.get("usageMetadata", {})
        return CompletionResult(
            text=self._response_text(payload),
            usage={
                "input_tokens": int(usage.get("promptTokenCount", 0)),
                "output_tokens": int(usage.get("candidatesTokenCount", 0)),
            },
            provider_metadata={"requested_model": request.model.model},
        )

    def _complete_deep_research(self, request: CompletionRequest) -> CompletionResult:
        base_url = self._base_url(request)
        operation = _matching_operation(request, "gemini", base_url)
        deadline = _research_deadline(request)
        interactions_url = f"{base_url}/interactions"
        with httpx.Client(
            timeout=_client_options(
                "GEMINI_BASE_URL",
                timeout_seconds_override=request.model.research_timeout_seconds,
            )["timeout"]
        ) as client:
            if operation and operation.get("status") == "completed" and "raw_report" in operation:
                report = str(operation["raw_report"])
                research_usage = operation.get("usage", {})
            else:
                if not operation:
                    response = client.post(
                        interactions_url,
                        headers=self._headers(),
                        json={
                            "input": _research_prompt(request),
                            "system_instruction": request.system,
                            "agent": request.model.model,
                            "agent_config": {
                                "type": "deep-research",
                                "thinking_summaries": "auto"
                                if request.model.research_thinking_summaries
                                else "none",
                                "visualization": "auto"
                                if request.model.research_visualization
                                else "off",
                                "collaborative_planning": False,
                            },
                            "background": True,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    operation = {
                        **_operation_identity(request, "gemini", base_url),
                        "remote_id": payload["id"],
                        "status": payload.get("status", "in_progress"),
                    }
                    _save_operation(request, operation)
                    _report_progress(
                        request,
                        "started",
                        provider="gemini",
                        remote_id=payload["id"],
                        remote_status=operation["status"],
                    )
                else:
                    poll = client.get(
                        f"{interactions_url}/{quote(str(operation['remote_id']), safe='')}",
                        headers=self._headers(),
                    )
                    poll.raise_for_status()
                    payload = poll.json()
                while payload.get("status") in {"queued", "in_progress"}:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Gemini deep research exceeded research_timeout_seconds"
                        )
                    _report_progress(
                        request,
                        "poll",
                        provider="gemini",
                        remote_id=operation["remote_id"],
                        remote_status=payload.get("status"),
                    )
                    delay = _poll_delay(request)
                    if delay:
                        time.sleep(delay)
                    poll = client.get(
                        f"{interactions_url}/{quote(str(operation['remote_id']), safe='')}",
                        headers=self._headers(),
                    )
                    poll.raise_for_status()
                    payload = poll.json()
                if payload.get("status") != "completed":
                    operation = {**operation, "status": payload.get("status", "unknown")}
                    _save_operation(request, operation)
                    raise RuntimeError(
                        f"Gemini deep research ended with status {payload.get('status')!r}"
                    )
                report = self._interaction_text(payload)
                usage = payload.get("usage", {})
                research_usage = {
                    "input_tokens": int(usage.get("total_input_tokens", 0)),
                    "output_tokens": int(usage.get("total_output_tokens", 0)),
                }
                operation = {
                    **operation,
                    "status": "completed",
                    "raw_report": report,
                    "usage": research_usage,
                }
                _save_operation(request, operation)
                _report_progress(
                    request,
                    "completed",
                    provider="gemini",
                    remote_id=operation["remote_id"],
                )
        normalized = self._complete_standard(_normalization_request(request, report))
        return _combined_result(normalized, report, research_usage, operation)


def get_provider(name: str, api_key: str | None = None) -> LLMProvider:
    if name == "mock":
        return MockProvider(True)
    if name == "mock_notopk":
        return MockProvider(False)
    if name == "anthropic":
        return AnthropicProvider(api_key)
    if name == "openai":
        return OpenAIProvider(api_key)
    if name == "gemini":
        return GeminiProvider(api_key)
    raise ValueError(f"unknown provider {name!r}; expected mock, mock_notopk, anthropic, openai, or gemini")

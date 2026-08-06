"""Provider adapters. Secrets are injected at call time and never persisted."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from .contracts import CompletionRequest, CompletionResult


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
        if not self.api_key:
            raise RuntimeError("Anthropic API key is not configured")
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs: dict[str, Any] = {"model": request.model.model, "max_tokens": request.model.max_tokens, "temperature": request.model.temperature, "system": request.system, "messages": request.messages}
        if request.model.top_k is not None:
            kwargs["top_k"] = request.model.top_k
        if request.model.top_p is not None:
            kwargs["top_p"] = request.model.top_p
        response = client.messages.create(**kwargs)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return CompletionResult(text=text, usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens})


class OpenAIProvider(LLMProvider):
    supports_top_k = False

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured")
        from openai import OpenAI

        response = OpenAI(api_key=self.api_key).chat.completions.create(model=request.model.model, messages=[{"role": "system", "content": request.system}, *request.messages], temperature=request.model.temperature, top_p=request.model.top_p or 1, max_tokens=request.model.max_tokens, response_format={"type": "json_object"})
        text = response.choices[0].message.content or "{}"
        usage = response.usage
        return CompletionResult(text=text, usage={"input_tokens": usage.prompt_tokens if usage else 0, "output_tokens": usage.completion_tokens if usage else 0})


def get_provider(name: str, api_key: str | None = None) -> LLMProvider:
    if name == "mock":
        return MockProvider(True)
    if name == "mock_notopk":
        return MockProvider(False)
    if name == "anthropic":
        return AnthropicProvider(api_key)
    if name == "openai":
        return OpenAIProvider(api_key)
    raise ValueError(f"unknown provider {name!r}; expected mock, mock_notopk, anthropic, or openai")

"""Typed completion contracts and node-output validation."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from .models import ModelConfig

Usage = dict[str, int]


@dataclass
class CompletionRequest:
    system: str
    messages: list[dict[str, str]]
    model: ModelConfig
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    operation_state: dict[str, Any] | None = None
    operation_checkpoint: Callable[[dict[str, Any]], None] | None = None
    progress: Callable[[str, dict[str, Any]], None] | None = None


@dataclass
class CompletionResult:
    text: str
    usage: Usage
    provider_metadata: dict[str, Any] = field(default_factory=dict)


NODE_REQUIRED: dict[str, list[str]] = {
    "intake": ["domain", "goal", "context", "explicit_asks", "constraints", "artifacts_summary", "assumptions", "open_questions"],
    "idea_generator": ["reframings", "directions", "adjacent_features", "open_questions", "shortlist", "recommended_primary", "reasoning", "changes_from_last_pass"],
    "researcher": ["delta_only", "findings", "overall_notes"],
    "judge": ["assessment_summary", "issues", "research_quality_notes", "keep_these_strengths", "verdict"],
    "judge_finalize": ["title", "problem", "goals", "non_goals", "target_users", "user_needs", "scope_mvp", "out_of_scope", "key_flows", "functional_requirements", "non_functional_requirements", "constraints", "assumptions", "risks", "success_metrics", "open_questions"],
    "architect": ["overview", "components", "data_model", "interfaces", "tech_choices", "cross_cutting", "deployment", "key_decisions", "local_first_to_server_path", "changes_from_last_pass"],
    "matcher": ["conformance", "over_engineering", "summary", "verdict"],
    "task_writer": ["work_package_meta", "tasks", "ordering_rationale", "coverage_note", "changes_from_last_pass"],
    "wp_reviewer": ["issues", "coverage_gaps", "summary", "verdict"],
}


def schema_for(node_id: str) -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[1] / "pipelines" / "schemas" / f"{node_id}.schema.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text(encoding="utf-8"))
    required = NODE_REQUIRED.get(node_id, [])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": required, "properties": {key: {} for key in required}, "additionalProperties": True}


def validate_node_output(node_id: str, value: Any) -> None:
    try:
        validate(instance=value, schema=schema_for(node_id))
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ValueError(f"{node_id} output failed validation at {path}: {exc.message}") from exc

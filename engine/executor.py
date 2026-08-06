"""Resumable data-defined pipeline executor."""
from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import CompletionRequest, validate_node_output
from .io_formats import write_layer_output
from .models import Layer, Node, Pipeline
from .provider import get_provider
from .search import SearchProvider
from .state import STATE_VERSION, atomic_write_json, load_state

EventCallback = Callable[[str, dict[str, Any]], None]
KeyResolver = Callable[[str], str | None]


class PipelineExecutor:
    def __init__(
        self,
        pipeline: Pipeline,
        runs_root: str | Path = "runs",
        fmt: str | None = None,
        run_id: str | None = None,
        log=print,
        event_callback: EventCallback | None = None,
        key_resolver: KeyResolver | None = None,
        search_provider: SearchProvider | None = None,
        max_retries: int = 2,
        loop_overrides: dict[str, int] | None = None,
    ):
        self.p = copy.deepcopy(pipeline)
        self.fmt = fmt or pipeline.default_format
        if self.fmt not in {"json", "md", "both"}:
            raise ValueError("format must be json, md, or both")
        self.run_id = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.run_dir = Path(runs_root) / self.run_id
        self.outputs_dir = self.run_dir / "outputs"
        self.log = log
        self.event_callback = event_callback
        self.key_resolver = key_resolver or (lambda _ref: None)
        self.search_provider = search_provider
        self.max_retries = max_retries
        self.blackboard: dict[str, Any] = {}
        self.artifact_history: dict[str, list[dict[str, Any]]] = {}
        self.sessions: dict[str, list[dict[str, str]]] = {}
        self.history: list[dict[str, Any]] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.next_action_index = 0
        self.completed_layers: list[str] = []
        self.pending_operation: dict[str, Any] | None = None
        self.status = "pending"
        self.error: str | None = None
        self._home = self.p.home_layer_of()
        self._apply_loop_overrides(loop_overrides or {})
        self.actions = self._flatten_actions()
        self.pipeline_fingerprint = hashlib.sha256(json.dumps(asdict(self.p), ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _apply_loop_overrides(self, overrides: dict[str, int]) -> None:
        aliases = {"ideation": "L1_ideation", "architecture": "L2_architecture", "workpackage": "L3_workpackage"}
        normalized = {aliases.get(key, key): value for key, value in overrides.items()}
        for layer in self.p.layers:
            if layer.id in normalized:
                value = int(normalized[layer.id])
                if value < 1 or value > 10:
                    raise ValueError("loop counts must be between 1 and 10")
                for step in layer.steps:
                    if step.kind == "loop":
                        step.iterations = value

    def _flatten_actions(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for layer_index, layer in enumerate(self.p.layers):
            for step_index, step in enumerate(layer.steps):
                if step.kind == "node" and step.node:
                    actions.append({"layer_index": layer_index, "step_index": step_index, "iteration": None, "iterations": None, "node_id": step.node})
                elif step.kind == "loop":
                    for iteration in range(step.iterations):
                        for node_id in step.nodes:
                            actions.append({"layer_index": layer_index, "step_index": step_index, "iteration": iteration, "iterations": step.iterations, "node_id": node_id})
                else:
                    raise ValueError(f"invalid step in layer {layer.id}")
        return actions

    def token_box(self) -> dict[str, int]:
        return {"input": self.tokens_in, "output": self.tokens_out, "total": self.tokens_in + self.tokens_out}

    def _emit(self, event_type: str, **payload: Any) -> None:
        if self.event_callback:
            self.event_callback(event_type, {"run_id": self.run_id, **payload})

    @staticmethod
    def _input_spec(item: Any) -> tuple[str, str]:
        if isinstance(item, str):
            return item, "latest"
        return str(item["ref"]), str(item.get("select", "latest"))

    def _render_inputs(self, node: Node) -> tuple[str, list[str]]:
        parts: list[str] = []
        refs: list[str] = []
        for item in node.inputs:
            key, select = self._input_spec(item)
            if key == "user":
                value = self.blackboard.get("__user__")
            elif select == "all":
                value = self.artifact_history.get(key, [])
            else:
                value = self.blackboard.get(key)
            if value is not None:
                label = "USER INTAKE" if key == "user" else f"INPUT FROM `{key}` ({select})"
                rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
                parts.append(f"### {label}\n{rendered}")
                refs.append(key)
        return "\n\n".join(parts) if parts else "(no upstream inputs yet)", refs

    def _system_prompt(self, node: Node, provider: Any) -> tuple[str, str]:
        if node.model.top_k is not None and not provider.supports_top_k and node.system_prompt_fallback:
            prompt, variant = node.system_prompt_fallback, "fallback"
        else:
            prompt, variant = node.system_prompt, "primary"
        return (f"{self.p.system_preamble}\n\n---\n\n{prompt}" if self.p.system_preamble else prompt), variant

    @staticmethod
    def _parse_json(text: str) -> Any:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
            if stripped.lstrip().startswith("json"):
                stripped = stripped.lstrip()[4:].lstrip()
        return json.loads(stripped)

    def _run_node(self, node: Node, layer_id: str, iteration: int | None, iterations: int | None) -> None:
        api_key = self.key_resolver(node.model.api_key_ref) if node.model.api_key_ref else None
        provider = get_provider(node.model.provider, api_key)
        system, variant = self._system_prompt(node, provider)
        rendered, refs = self._render_inputs(node)
        if (
            "web_search" in node.tools
            and self.search_provider
            and node.model.mode != "deep_research"
        ):
            results = self.search_provider.search(rendered[:1200], 5)
            rendered += "\n\n### WEB SEARCH RESULTS (untrusted references)\n" + json.dumps(results, ensure_ascii=False, indent=2)
        user_message = f"OUTPUT_FORMAT = json\n\n# TASK: {node.role}\n\n{rendered}\n\nReturn only valid JSON matching the output contract."
        session = self.sessions.setdefault(node.id, [])
        if not (
            self.pending_operation
            and session
            and session[-1] == {"role": "user", "content": user_message}
        ):
            session.append({"role": "user", "content": user_message})
        self._emit("node.started", node_id=node.id, layer_id=layer_id, iteration=iteration)
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                result = provider.complete(
                    CompletionRequest(
                        system=system,
                        messages=session,
                        model=node.model,
                        tools=node.tools,
                        metadata={"role": node.role, "node_id": node.id, "iteration": iteration, "iterations": iterations, "input_refs": refs, "prompt_variant": variant},
                        operation_state=self.pending_operation,
                        operation_checkpoint=self._checkpoint_operation,
                        progress=lambda status, payload: self._emit(
                            f"node.research.{status}",
                            node_id=node.id,
                            layer_id=layer_id,
                            iteration=iteration,
                            **payload,
                        ),
                    )
                )
                value = self._parse_json(result.text)
                validate_node_output(node.id, value)
                break
            except Exception as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"{node.id} failed after {attempt + 1} attempts: {exc}") from exc
                self._emit("node.retry", node_id=node.id, attempt=attempt + 1, error=str(exc))
                if "result" in locals():
                    session.append({"role": "assistant", "content": result.text})
                session.append({"role": "user", "content": f"Your prior response was invalid: {exc}. Return corrected JSON only."})
        session.append({"role": "assistant", "content": json.dumps(value, ensure_ascii=False)})
        self.pending_operation = None
        self.blackboard[node.id] = value
        artifact = {"node": node.id, "iteration": iteration, "value": value, "created_at": datetime.now(UTC).isoformat()}
        if result.provider_metadata:
            artifact["provider_metadata"] = result.provider_metadata
        self.artifact_history.setdefault(node.id, []).append(artifact)
        self.tokens_in += int(result.usage.get("input_tokens", 0))
        self.tokens_out += int(result.usage.get("output_tokens", 0))
        item = {"node": node.id, "role": node.role, "iteration": iteration, "ms": int((time.perf_counter() - started) * 1000), "input_refs": refs, "prompt_variant": variant, "tokens_in": int(result.usage.get("input_tokens", 0)), "tokens_out": int(result.usage.get("output_tokens", 0))}
        self.history.append(item)
        self._emit("node.completed", **item, tokens=self.token_box())
        self._emit("tokens.updated", tokens=self.token_box())

    def _finish_layer(self, layer: Layer) -> None:
        outputs = {node_id: self.blackboard.get(node_id) for node_id in layer.node_ids()}
        paths = write_layer_output(self.outputs_dir, layer.id, layer.name, outputs, layer.output_from, self.fmt)
        for node_id in layer.node_ids():
            if self._home.get(node_id) == layer.id:
                self.sessions.pop(node_id, None)
        if layer.id not in self.completed_layers:
            self.completed_layers.append(layer.id)
        self._emit("layer.completed", layer_id=layer.id, outputs=[path.name for path in paths], canonical=layer.output_from)

    def _state(self) -> dict[str, Any]:
        return {"state_version": STATE_VERSION, "run_id": self.run_id, "pipeline": self.p.name, "pipeline_fingerprint": self.pipeline_fingerprint, "format": self.fmt, "status": self.status, "error": self.error, "updated_at": datetime.now(UTC).isoformat(), "next_action_index": self.next_action_index, "tokens": self.token_box(), "blackboard": self.blackboard, "artifact_history": self.artifact_history, "sessions": self.sessions, "history": self.history, "completed_layers": self.completed_layers, "pending_operation": self.pending_operation}

    def _checkpoint(self) -> None:
        atomic_write_json(self.run_dir / "state.json", self._state())

    def _checkpoint_operation(self, state: dict[str, Any]) -> None:
        self.pending_operation = copy.deepcopy(state)
        self._checkpoint()

    def restore(self) -> None:
        state = load_state(self.run_dir / "state.json")
        if state["pipeline"] != self.p.name or state["format"] != self.fmt or state.get("pipeline_fingerprint") != self.pipeline_fingerprint:
            raise ValueError("checkpoint pipeline or format does not match")
        self.status = state["status"]
        self.error = state.get("error")
        self.next_action_index = int(state["next_action_index"])
        self.tokens_in = int(state["tokens"]["input"])
        self.tokens_out = int(state["tokens"]["output"])
        self.blackboard = state["blackboard"]
        self.artifact_history = state["artifact_history"]
        self.sessions = state["sessions"]
        self.history = state["history"]
        self.completed_layers = state["completed_layers"]
        self.pending_operation = state.get("pending_operation")

    def run(self, user_brief: str, artifacts: list[str] | None = None, resume: bool = False) -> Path:
        if resume:
            self.restore()
            if self.status == "completed":
                return self.outputs_dir
        else:
            self.blackboard["__user__"] = user_brief + (("\n\n### ATTACHED ARTIFACTS\n" + "\n---\n".join(artifacts)) if artifacts else "")
            self.next_action_index = 0
        self.status = "running"
        self.error = None
        self._emit("run.started", resumed=resume, tokens=self.token_box())
        self._checkpoint()
        try:
            while self.next_action_index < len(self.actions):
                action = self.actions[self.next_action_index]
                layer = self.p.layers[action["layer_index"]]
                if self.next_action_index == 0 or self.actions[self.next_action_index - 1]["layer_index"] != action["layer_index"]:
                    self._emit("layer.started", layer_id=layer.id, name=layer.name)
                snapshot = (
                    copy.deepcopy(self.blackboard),
                    copy.deepcopy(self.artifact_history),
                    copy.deepcopy(self.sessions),
                    copy.deepcopy(self.history),
                    self.tokens_in,
                    self.tokens_out,
                )
                try:
                    self._run_node(self.p.nodes[action["node_id"]], layer.id, action["iteration"], action["iterations"])
                except Exception:
                    self.blackboard, self.artifact_history, self.sessions, self.history, self.tokens_in, self.tokens_out = snapshot
                    raise
                self.next_action_index += 1
                is_last = self.next_action_index == len(self.actions) or self.actions[self.next_action_index]["layer_index"] != action["layer_index"]
                if is_last:
                    self._finish_layer(layer)
                self._checkpoint()
            self.status = "completed"
            self._checkpoint()
            self._emit("run.completed", tokens=self.token_box(), outputs=str(self.outputs_dir))
            return self.outputs_dir
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self._checkpoint()
            self._emit("run.failed", error=str(exc), tokens=self.token_box())
            raise

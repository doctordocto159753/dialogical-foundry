"""
Core data model for the orchestration engine.

A Pipeline is *data*: a list of Layers, each Layer is a list of Steps,
a Step is either a single Node run or a Loop (a group of nodes repeated N times).
Nodes are LLM calls with a system prompt, a provider-aware model config, declared
inputs (read from a shared blackboard), and optional tools.

The engine that runs this model is domain-agnostic: the same engine runs a
"software" pipeline, a "research paper" pipeline, a "campaign" pipeline, etc.
Only the pipeline definition (this data) changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelConfig:
    provider: str = "mock"          # mock | anthropic | openai | ...
    model: str = "mock-1"
    temperature: float = 0.7
    top_k: int | None = None     # only some providers (e.g. Anthropic) honor this
    top_p: float | None = None
    max_tokens: int = 4096
    api_key_ref: str | None = None
    base_url: str | None = None
    openai_api: str = "chat_completions"  # chat_completions | responses
    mode: str = "standard"          # standard | deep_research (Researcher only)
    normalization_model: str | None = None
    research_timeout_seconds: int = 1800
    research_poll_interval_seconds: float = 5.0
    research_max_tool_calls: int = 20
    research_thinking_summaries: bool = True
    research_visualization: bool = False

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ModelConfig:
        return ModelConfig(**{k: d[k] for k in d if k in ModelConfig.__annotations__})


@dataclass
class Node:
    id: str
    role: str                       # human-readable role, e.g. "Idea Generator"
    system_prompt: str
    model: ModelConfig = field(default_factory=ModelConfig)
    inputs: list[Any] = field(default_factory=list)  # strings or {ref, select=latest|all}
    tools: list[str] = field(default_factory=list)    # e.g. ["web_search"], ["terminal"]
    # Creativity fallback: used when the node relies on top_k for entropy but the
    # configured provider does not support top_k. Instead of param-level entropy,
    # we swap to a prompt that loosens the model's creative constraints.
    system_prompt_fallback: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Node:
        return Node(
            id=d["id"],
            role=d["role"],
            system_prompt=d.get("system_prompt", ""),
            model=ModelConfig.from_dict(d.get("model", {})),
            inputs=list(d.get("inputs", [])),
            tools=list(d.get("tools", [])),
            system_prompt_fallback=d.get("system_prompt_fallback"),
        )


@dataclass
class Step:
    kind: str                       # "node" | "loop"
    node: str | None = None      # for kind == "node"
    nodes: list[str] = field(default_factory=list)    # for kind == "loop"
    iterations: int = 1             # for kind == "loop"

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Step:
        return Step(
            kind=d["kind"],
            node=d.get("node"),
            nodes=list(d.get("nodes", [])),
            iterations=int(d.get("iterations", 1)),
        )


@dataclass
class Layer:
    id: str
    name: str
    steps: list[Step]
    output_from: str | None = None   # canonical highlight; full layer output = all its nodes

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Layer:
        return Layer(
            id=d["id"],
            name=d["name"],
            steps=[Step.from_dict(s) for s in d["steps"]],
            output_from=d.get("output_from"),
        )

    def node_ids(self) -> list[str]:
        ids: list[str] = []
        for s in self.steps:
            if s.kind == "node" and s.node:
                ids.append(s.node)
            elif s.kind == "loop":
                ids.extend(s.nodes)
        # de-dup, preserve order
        seen, out = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out


@dataclass
class Pipeline:
    name: str
    nodes: dict[str, Node]
    layers: list[Layer]
    default_format: str = "json"    # json | md | both
    system_preamble: str = ""       # shared "house rules" prepended to every node's system prompt

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Pipeline:
        return Pipeline(
            name=d["name"],
            nodes={n["id"]: Node.from_dict(n) for n in d["nodes"]},
            layers=[Layer.from_dict(layer) for layer in d["layers"]],
            default_format=d.get("default_format", "json"),
            system_preamble=d.get("system_preamble", ""),
        )

    def home_layer_of(self) -> dict[str, str]:
        """Map each node -> the id of the FIRST layer it appears in (its 'home').
        Used to close (clear) a node's session when its home layer finishes."""
        home: dict[str, str] = {}
        for layer in self.layers:
            for nid in layer.node_ids():
                home.setdefault(nid, layer.id)
        return home

import json
from pathlib import Path

import pytest

import engine.executor as executor_module
from engine import Pipeline, PipelineExecutor
from engine.contracts import CompletionRequest, CompletionResult
from engine.models import Layer, ModelConfig, Node, Step
from engine.provider import LLMProvider, MockProvider
from pipelines.build_v1 import PIPELINE

ROOT = Path(__file__).resolve().parents[1]


def pipeline() -> Pipeline:
    return Pipeline.from_dict(json.loads((ROOT / "pipelines" / "foundry_v1.json").read_text(encoding="utf-8")))


def test_generated_pipeline_is_in_sync():
    stored = json.loads((ROOT / "pipelines" / "foundry_v1.json").read_text(encoding="utf-8"))
    assert stored == PIPELINE


def test_structured_outputs_and_iteration_history(tmp_path):
    events = []
    executor = PipelineExecutor(pipeline(), runs_root=tmp_path, fmt="both", event_callback=lambda kind, payload: events.append((kind, payload)))
    executor.run("A local studio for turning rough ideas into reviewed plans")

    assert executor.status == "completed"
    assert len(executor.history) == 22
    assert len(executor.artifact_history["idea_generator"]) == 4
    assert len(executor.artifact_history["architect"]) == 2
    assert len(executor.artifact_history["task_writer"]) == 2
    assert executor.sessions == {}
    assert executor.token_box()["total"] > 0
    assert sorted(path.name for path in executor.outputs_dir.glob("*.json")) == [
        "L0_intake.json", "L1_ideation.json", "L2_architecture.json", "L3_workpackage.json"
    ]
    work_package = json.loads((executor.outputs_dir / "L3_workpackage.json").read_text(encoding="utf-8"))
    assert isinstance(work_package["canonical_output"], dict)
    assert work_package["canonical_output"]["tasks"][0]["id"] == "T-001"
    assert (executor.outputs_dir / "L3_workpackage.md").read_text(encoding="utf-8").startswith("# Layer 3")
    assert events[-1][0] == "run.completed"


class InvalidThenValid(LLMProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        text = "{}" if self.calls == 1 else json.dumps({"domain": "software", "goal": "g", "context": "c", "explicit_asks": [], "constraints": [], "artifacts_summary": [], "assumptions": [], "open_questions": []})
        return CompletionResult(text=text, usage={"input_tokens": 1, "output_tokens": 1})


def test_validation_retries(monkeypatch, tmp_path):
    provider = InvalidThenValid()
    monkeypatch.setattr(executor_module, "get_provider", lambda *_: provider)
    p = pipeline()
    p.layers = p.layers[:1]
    p.nodes = {"intake": p.nodes["intake"]}
    executor = PipelineExecutor(p, runs_root=tmp_path, max_retries=1)
    executor.run("brief")
    assert provider.calls == 2
    assert executor.blackboard["intake"]["goal"] == "g"


class FailAfter(LLMProvider):
    def __init__(self, fail_on: int):
        super().__init__()
        self.delegate = MockProvider()
        self.calls = 0
        self.fail_on = fail_on

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("injected crash")
        return self.delegate.complete(request)


def test_resume_starts_at_exact_checkpoint(monkeypatch, tmp_path):
    failing = FailAfter(3)
    monkeypatch.setattr(executor_module, "get_provider", lambda *_: failing)
    run_id = "resume-proof"
    first = PipelineExecutor(pipeline(), runs_root=tmp_path, run_id=run_id, max_retries=0)
    with pytest.raises(RuntimeError, match="injected crash"):
        first.run("brief")
    assert first.next_action_index == 2
    assert [item["node"] for item in first.history] == ["intake", "idea_generator"]

    monkeypatch.setattr(executor_module, "get_provider", lambda *_: MockProvider())
    resumed = PipelineExecutor(pipeline(), runs_root=tmp_path, run_id=run_id, max_retries=0)
    resumed.run("ignored", resume=True)
    assert resumed.status == "completed"
    assert len(resumed.history) == 22
    assert [item["node"] for item in resumed.history].count("intake") == 1
    assert [item["node"] for item in resumed.history].count("idea_generator") == 4


class CheckpointThenCrash(LLMProvider):
    def complete(self, request: CompletionRequest) -> CompletionResult:
        request.operation_checkpoint(
            {
                "provider": "gemini",
                "node_id": "researcher",
                "iteration": None,
                "model": "deep-agent-exact",
                "base_url": "https://gemini.example/v1beta",
                "remote_id": "remote-job-1",
                "status": "in_progress",
            }
        )
        raise RuntimeError("crash after remote job creation")


class ResumePendingResearch(LLMProvider):
    def __init__(self):
        super().__init__()
        self.received_state = None

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.received_state = request.operation_state
        return CompletionResult(
            text=json.dumps(
                {"delta_only": False, "findings": [], "overall_notes": "resumed"}
            ),
            usage={"input_tokens": 1, "output_tokens": 1},
        )


def test_remote_research_operation_is_checkpointed_and_reused(monkeypatch, tmp_path):
    research_pipeline = Pipeline(
        name="resume-remote-research",
        nodes={
            "researcher": Node(
                id="researcher",
                role="Researcher",
                system_prompt="research",
                model=ModelConfig(
                    provider="gemini",
                    model="deep-agent-exact",
                    base_url="https://gemini.example/v1beta",
                    mode="deep_research",
                ),
            )
        },
        layers=[
            Layer(
                id="research",
                name="Research",
                steps=[Step(kind="node", node="researcher")],
                output_from="researcher",
            )
        ],
    )
    monkeypatch.setattr(executor_module, "get_provider", lambda *_: CheckpointThenCrash())
    first = PipelineExecutor(
        research_pipeline,
        runs_root=tmp_path,
        run_id="remote-resume",
        max_retries=0,
    )
    with pytest.raises(RuntimeError, match="crash after remote job creation"):
        first.run("brief")
    saved = json.loads((first.run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved["pending_operation"]["remote_id"] == "remote-job-1"

    resumed_provider = ResumePendingResearch()
    monkeypatch.setattr(executor_module, "get_provider", lambda *_: resumed_provider)
    resumed = PipelineExecutor(
        research_pipeline,
        runs_root=tmp_path,
        run_id="remote-resume",
        max_retries=0,
    )
    resumed.run("ignored", resume=True)
    assert resumed_provider.received_state["remote_id"] == "remote-job-1"
    assert resumed.pending_operation is None

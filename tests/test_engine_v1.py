"""Evidence tests for v1: pipeline shape, token box, creativity fallback."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Pipeline, PipelineExecutor  # noqa
from engine.models import Node, ModelConfig, Layer, Step  # noqa


def _silent(*a, **k): pass


def test_v1_shape_and_tokens():
    data = json.loads((Path(__file__).resolve().parents[1] / "pipelines" / "foundry_v1.json").read_text())
    p = Pipeline.from_dict(data)
    ex = PipelineExecutor(p, runs_root="runs_test", fmt="json", log=_silent)
    ex.run("A local-first dialogical factory that matures an idea into a dev-ready work package.")
    # 4 layers each produced a JSON output
    outs = sorted(x.name for x in ex.outputs_dir.glob("*.json"))
    assert outs == ["L0_intake.json", "L1_ideation.json", "L2_architecture.json", "L3_workpackage.json"], outs
    # token box populated and consistent
    tb = ex.token_box()
    assert tb["input"] > 0 and tb["output"] > 0
    assert tb["total"] == tb["input"] + tb["output"]
    assert tb["input"] == sum(h["tokens_in"] for h in ex.history)
    assert tb["output"] == sum(h["tokens_out"] for h in ex.history)
    # sessions closed at layer end
    assert ex.sessions == {}
    print(f"OK shape+tokens: layers={len(outs)} tokens={tb}")


def test_creativity_fallback():
    # idea_generator wants top_k; provider mock_notopk lacks it -> fallback prompt
    node = Node(
        id="idea_generator", role="Idea Generator",
        system_prompt="PRIMARY",
        system_prompt_fallback="FALLBACK",
        model=ModelConfig(provider="mock_notopk", model="m", temperature=1.0, top_k=80),
        inputs=["user"],
    )
    p = Pipeline(
        name="fallback_probe", nodes={node.id: node},
        layers=[Layer(id="L", name="L", steps=[Step(kind="node", node="idea_generator")],
                      output_from="idea_generator")],
    )
    ex = PipelineExecutor(p, runs_root="runs_test", fmt="json", log=_silent)
    ex.run("probe")
    variant = ex.history[0]["prompt_variant"]
    assert variant == "fallback", variant
    print("OK fallback: provider without top_k -> creativity-fallback prompt selected")

    # control: with a top_k-supporting provider it stays primary
    node2 = Node(id="idea_generator", role="Idea Generator", system_prompt="PRIMARY",
                 system_prompt_fallback="FALLBACK",
                 model=ModelConfig(provider="mock", model="m", temperature=1.0, top_k=80),
                 inputs=["user"])
    p2 = Pipeline(name="ctrl", nodes={node2.id: node2},
                  layers=[Layer(id="L", name="L", steps=[Step(kind="node", node="idea_generator")],
                                output_from="idea_generator")])
    ex2 = PipelineExecutor(p2, runs_root="runs_test", fmt="json", log=_silent)
    ex2.run("probe")
    assert ex2.history[0]["prompt_variant"] == "primary"
    print("OK control: provider with top_k -> primary prompt kept")


if __name__ == "__main__":
    test_v1_shape_and_tokens()
    test_creativity_fallback()
    print("\nALL TESTS PASSED")

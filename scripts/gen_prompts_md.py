#!/usr/bin/env python3
"""Generate or verify the readable prompt reference from the pipeline SSOT."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render() -> str:
    pipeline = json.loads((ROOT / "pipelines" / "foundry_v1.json").read_text(encoding="utf-8"))
    lines = [
        "# Dialogical Foundry — v1 Node System Prompts",
        "",
        "Generated from `pipelines/foundry_v1.json`. The engine prepends the shared",
        "House Rules to every node's system prompt at runtime.",
        "",
        "## Shared House Rules (prepended to every node)",
        "",
        "```",
        pipeline["system_preamble"],
        "```",
        "",
    ]
    for node in pipeline["nodes"]:
        model = node.get("model", {})
        entropy = f"temp={model.get('temperature')}"
        if model.get("top_k") is not None:
            entropy += f", top_k={model.get('top_k')}, top_p={model.get('top_p')}"
        tools = f" · tools={node['tools']}" if node.get("tools") else ""
        lines.extend([
            f"## `{node['id']}` — {node['role']}",
            "",
            f"_model: {model.get('model')} ({entropy}){tools} · inputs: {node.get('inputs', [])}_",
            "",
            "```",
            node["system_prompt"],
            "```",
            "",
        ])
        if node.get("system_prompt_fallback"):
            lines.extend(["**Creativity-fallback variant (provider without top_k):**", "", "```", node["system_prompt_fallback"], "```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "PROMPTS.md"
    expected = render()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit("PROMPTS.md is out of date; run scripts/gen_prompts_md.py")
        print("PROMPTS.md is in sync")
    else:
        output.write_text(expected, encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()

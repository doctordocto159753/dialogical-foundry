"""Deterministic per-layer JSON and Markdown output writers."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .state import atomic_write_json


def _markdown(value: Any, depth: int = 2) -> list[str]:
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lines.extend([f"{'#' * min(depth, 6)} {key.replace('_', ' ').title()}", ""])
            lines.extend(_markdown(item, depth + 1))
    elif isinstance(value, list):
        if not value:
            lines.extend(["_None._", ""])
        for index, item in enumerate(value, 1):
            if isinstance(item, (dict, list)):
                lines.extend([f"{'#' * min(depth, 6)} Item {index}", ""])
                lines.extend(_markdown(item, depth + 1))
            else:
                lines.append(f"- {item}")
        if value:
            lines.append("")
    else:
        lines.extend([str(value), ""])
    return lines


def write_layer_output(outputs_dir: Path, layer_id: str, layer_name: str, node_outputs: dict[str, Any], canonical: str | None, fmt: str) -> list[Path]:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    payload = {"layer_id": layer_id, "layer_name": layer_name, "generated_at": datetime.now(UTC).isoformat(), "canonical_output_node": canonical, "canonical_output": node_outputs.get(canonical) if canonical else None, "nodes": node_outputs}
    written: list[Path] = []
    if fmt in ("json", "both"):
        path = outputs_dir / f"{layer_id}.json"
        atomic_write_json(path, payload)
        written.append(path)
    if fmt in ("md", "both"):
        path = outputs_dir / f"{layer_id}.md"
        lines = [f"# {layer_name}", "", f"Layer id: `{layer_id}`", "", *_markdown(payload["canonical_output"] if canonical else node_outputs)]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written

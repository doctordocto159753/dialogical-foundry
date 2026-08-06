from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from engine import Pipeline, PipelineExecutor
from engine.search import MockSearchProvider, TavilySearchProvider
from engine.state import atomic_write_json

from .database import Database
from .keystore import KeyStore
from .settings import ROOT, Settings


class RunManager:
    def __init__(self, db: Database, keys: KeyStore, settings: Settings):
        self.db = db
        self.keys = keys
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="foundry-run")
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def _pipeline_data(self) -> dict[str, Any]:
        data = json.loads((ROOT / "pipelines" / "foundry_v1.json").read_text(encoding="utf-8"))
        for node_id, config in self.db.node_configs().items():
            node = next((item for item in data["nodes"] if item["id"] == node_id), None)
            if node:
                node["model"].update({key: config[key] for key in ("provider", "model", "api_key_ref", "temperature", "top_k", "top_p", "max_tokens") if key in config})
                if "tools" in config:
                    node["tools"] = list(config["tools"])
        return data

    def _search(self, current: dict[str, Any] | None = None):
        current = current or self.db.get_settings()
        if current.get("search_provider") == "tavily":
            key = self.keys.get(current.get("search_key_ref", ""))
            if not key:
                raise RuntimeError("Tavily search is selected but no key is configured")
            return TavilySearchProvider(key)
        return MockSearchProvider()

    def create(self, brief: str, artifacts: list[str], artifact_manifest: list[dict[str, Any]], fmt: str, loops: dict[str, int], run_id: str | None = None) -> str:
        run_id = run_id or uuid.uuid4().hex
        run_dir = self.settings.runs_dir / run_id
        runtime_settings = self.db.get_settings()
        atomic_write_json(run_dir / "input" / "manifest.json", {"brief": brief, "artifacts": artifact_manifest, "format": fmt, "loops": loops, "search": {"search_provider": runtime_settings.get("search_provider", "mock"), "search_key_ref": runtime_settings.get("search_key_ref")}})
        atomic_write_json(run_dir / "input" / "pipeline.json", self._pipeline_data())
        self.db.create_run(run_id, brief, artifacts, fmt, loops)
        self.start(run_id, resume=False)
        return run_id

    def start(self, run_id: str, resume: bool) -> None:
        with self._lock:
            if run_id in self._active:
                raise ValueError("run is already active")
            self._active.add(run_id)
        self.pool.submit(self._execute, run_id, resume)

    def _event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.db.append_event(run_id, event_type, payload)
        updates: dict[str, Any] = {}
        if event_type == "run.started":
            updates["status"] = "running"
        elif event_type == "run.completed":
            updates["status"] = "completed"
        elif event_type == "run.failed":
            updates.update(status="failed", error=payload.get("error"))
        if "tokens" in payload:
            updates["tokens_json"] = json.dumps(payload["tokens"])
        if event_type == "layer.completed":
            run = self.db.get_run(run_id)
            completed = [*run["completed_layers"], payload["layer_id"]]
            updates["completed_layers_json"] = json.dumps(list(dict.fromkeys(completed)))
        self.db.update_run(run_id, **updates)

    def _execute(self, run_id: str, resume: bool) -> None:
        try:
            run = self.db.get_run(run_id)
            if not run:
                return
            run_dir = self.settings.runs_dir / run_id
            pipeline_data = json.loads((run_dir / "input" / "pipeline.json").read_text(encoding="utf-8"))
            manifest = json.loads((run_dir / "input" / "manifest.json").read_text(encoding="utf-8"))
            executor = PipelineExecutor(Pipeline.from_dict(pipeline_data), runs_root=self.settings.runs_dir, fmt=run["format"], run_id=run_id, log=lambda *_: None, event_callback=lambda event, payload: self._event(run_id, event, payload), key_resolver=self.keys.get, search_provider=self._search(manifest.get("search")), loop_overrides=run["loops"])
            executor.run(run["brief"], run["artifacts"], resume=resume)
        except Exception as exc:
            self.db.update_run(run_id, status="failed", error=str(exc))
            if not self.db.events_after(run_id, 0) or self.db.events_after(run_id, 0)[-1]["type"] != "run.failed":
                self.db.append_event(run_id, "run.failed", {"run_id": run_id, "error": str(exc), "tokens": self.db.get_run(run_id)["tokens"]})
        finally:
            with self._lock:
                self._active.discard(run_id)

    def resume(self, run_id: str) -> None:
        run = self.db.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        if run["status"] == "completed":
            raise ValueError("completed runs do not need resume")
        if not (self.settings.runs_dir / run_id / "state.json").exists():
            raise ValueError("run has no checkpoint")
        self.start(run_id, resume=True)

    def output_manifest(self, run_id: str) -> list[dict[str, Any]]:
        output_dir = self.settings.runs_dir / run_id / "outputs"
        if not output_dir.exists():
            return []
        return [{"name": path.name, "layer": path.stem, "format": path.suffix[1:], "bytes": path.stat().st_size, "url": f"/api/runs/{run_id}/outputs/{path.stem}?format={path.suffix[1:]}"} for path in sorted(output_dir.iterdir()) if path.is_file() and path.suffix in {".json", ".md"}]

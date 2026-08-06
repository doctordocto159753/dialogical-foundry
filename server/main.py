from __future__ import annotations

import asyncio
import json
import math
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any
from urllib.parse import urlsplit

import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.models import ModelConfig

from .database import Database
from .ingest import extract_uploads, fetch_public_github, word_count
from .keystore import KeyStore
from .run_manager import RunManager
from .settings import ROOT, settings


class KeyInput(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=10_000)


def services(request: Request) -> tuple[Database, KeyStore, RunManager]:
    return request.app.state.db, request.app.state.keys, request.app.state.manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    db.initialize()
    for orphan_id in db.interrupt_orphans():
        db.append_event(orphan_id, "run.interrupted", {"run_id": orphan_id, "reason": "service restarted while the run was active"})
    keys = KeyStore(db, settings.data_dir)
    app.state.db = db
    app.state.keys = keys
    app.state.manager = RunManager(db, keys, settings)
    yield
    app.state.manager.pool.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="Dialogical Foundry", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key != "artifacts"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, "data_dir": str(settings.data_dir)}


@app.get("/api/runs")
def list_runs(request: Request) -> list[dict[str, Any]]:
    db, _, manager = services(request)
    return [{**public_run(run), "outputs": manager.output_manifest(run["id"])} for run in db.list_runs()]


@app.post("/api/runs", status_code=202)
async def create_run(
    request: Request,
    brief: str = Form(...),
    pasted_text: str = Form(""),
    github_url: str = Form(""),
    output_format: str = Form("json"),
    loop_counts: str = Form('{"ideation":4,"architecture":2,"workpackage":2}'),
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, Any]:
    if not brief.strip():
        raise HTTPException(422, "brief is required")
    if word_count(brief) > 2000:
        raise HTTPException(422, "brief must contain at most 2,000 words")
    if len(pasted_text) > settings.max_pasted_chars:
        raise HTTPException(422, "pasted text is too long")
    if output_format not in {"json", "md", "both"}:
        raise HTTPException(422, "output format must be json, md, or both")
    try:
        loops = json.loads(loop_counts)
        if set(loops) != {"ideation", "architecture", "workpackage"} or any(not isinstance(value, int) or value < 1 or value > 10 for value in loops.values()):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(422, "loop counts must contain ideation, architecture, and workpackage values from 1 to 10") from None
    run_id = uuid.uuid4().hex
    input_dir = settings.runs_dir / run_id / "input" / "files"
    try:
        artifacts, manifest = await extract_uploads(files or [], input_dir, settings)
        if pasted_text.strip():
            artifacts.append(f"PASTED TEXT\n{pasted_text}")
            manifest.append({"name": "pasted-text", "characters": len(pasted_text), "kind": "pasted_text"})
        if github_url.strip():
            repo_text, repo_manifest = await fetch_public_github(github_url, settings)
            artifacts.append(repo_text)
            manifest.append({**repo_manifest, "name": "public-github-repository", "kind": "github"})
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    _, _, manager = services(request)
    manager.create(brief.strip(), artifacts, manifest, output_format, loops, run_id=run_id)
    return {"id": run_id, "status": "pending", "events_url": f"/api/runs/{run_id}/events"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, Any]:
    db, _, manager = services(request)
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return {**public_run(run), "outputs": manager.output_manifest(run_id)}


@app.post("/api/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str, request: Request) -> dict[str, str]:
    _, _, manager = services(request)
    try:
        manager.resume(run_id)
    except KeyError:
        raise HTTPException(404, "run not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": run_id, "status": "pending"}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    db, _, _ = services(request)
    if not db.get_run(run_id):
        raise HTTPException(404, "run not found")
    try:
        cursor = int(request.headers.get("last-event-id", request.query_params.get("after", "0")))
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        idle = 0
        while not await request.is_disconnected():
            events = await asyncio.to_thread(db.events_after, run_id, cursor)
            for event in events:
                cursor = event["seq"]
                yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            run = await asyncio.to_thread(db.get_run, run_id)
            if run and run["status"] in {"completed", "failed", "interrupted"} and not events:
                break
            idle += 1
            if idle % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/outputs")
def output_manifest(run_id: str, request: Request) -> list[dict[str, Any]]:
    db, _, manager = services(request)
    if not db.get_run(run_id):
        raise HTTPException(404, "run not found")
    return manager.output_manifest(run_id)


@app.get("/api/runs/{run_id}/outputs/{layer_id}")
def output_file(run_id: str, layer_id: str, request: Request, format: str = "json"):
    db, _, _ = services(request)
    if not db.get_run(run_id):
        raise HTTPException(404, "run not found")
    allowed_layers = {"L0_intake", "L1_ideation", "L2_architecture", "L3_workpackage"}
    if layer_id not in allowed_layers or format not in {"json", "md"}:
        raise HTTPException(404, "output not found")
    path = settings.runs_dir / run_id / "outputs" / f"{layer_id}.{format}"
    if not path.is_file():
        raise HTTPException(404, "output not ready")
    media = "application/json" if format == "json" else "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/settings")
def get_settings(request: Request) -> dict[str, Any]:
    db, _, _ = services(request)
    return db.get_settings()


@app.put("/api/settings")
def put_settings(request: Request, value: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    current = services(request)[0].get_settings()
    merged = {**current, **value}
    if merged.get("default_format") not in {"json", "md", "both"}:
        raise HTTPException(422, "invalid default format")
    if merged.get("search_provider") not in {"mock", "tavily"}:
        raise HTTPException(422, "invalid search provider")
    loops = merged.get("loops", {})
    if set(loops) != {"ideation", "architecture", "workpackage"} or any(not isinstance(number, int) or number < 1 or number > 10 for number in loops.values()):
        raise HTTPException(422, "invalid loop defaults")
    services(request)[0].set_settings(merged)
    return merged


@app.get("/api/settings/nodes")
def node_settings(request: Request) -> list[dict[str, Any]]:
    db, _, _ = services(request)
    pipeline = json.loads((ROOT / "pipelines" / "foundry_v1.json").read_text(encoding="utf-8"))
    overrides = db.node_configs()
    return [{"id": node["id"], "role": node["role"], **asdict(ModelConfig.from_dict(node["model"])), "tools": node.get("tools", []), **overrides.get(node["id"], {})} for node in pipeline["nodes"]]


def _validate_base_url(value: Any) -> None:
    if value in {None, ""}:
        return
    if not isinstance(value, str) or len(value) > 2_000 or value != value.strip():
        raise HTTPException(422, "base URL must be a trimmed string")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(422, "base URL must be an absolute HTTP(S) URL without credentials, query, or fragment")


def _validated_node_config(node_id: str, value: dict[str, Any]) -> dict[str, Any]:
    provider = value.get("provider", "mock")
    if provider not in {"mock", "mock_notopk", "anthropic", "openai", "gemini"}:
        raise HTTPException(422, "unsupported provider")
    mode = value.get("mode", "standard")
    if mode not in {"standard", "deep_research"}:
        raise HTTPException(422, "unsupported model mode")
    if mode == "deep_research" and node_id != "researcher":
        raise HTTPException(422, "deep research mode is only available for the researcher node")
    if mode == "deep_research" and provider not in {"anthropic", "openai", "gemini"}:
        raise HTTPException(422, "deep research mode requires Anthropic, OpenAI, or Gemini")
    for field_name in ("model", "normalization_model"):
        field_value = value.get(field_name)
        if field_name == "normalization_model" and mode != "deep_research":
            continue
        if not isinstance(field_value, str) or not field_value or field_value != field_value.strip() or len(field_value) > 200:
            raise HTTPException(422, f"{field_name} must be a non-empty, trimmed model ID")
    _validate_base_url(value.get("base_url"))
    numeric_ranges = {
        "temperature": (0, 2),
        "top_k": (1, 10_000),
        "top_p": (0, 1),
        "max_tokens": (1, 1_000_000),
        "research_timeout_seconds": (1, 86_400),
        "research_poll_interval_seconds": (0, 60),
        "research_max_tool_calls": (1, 1_000),
    }
    for field_name, (minimum, maximum) in numeric_ranges.items():
        field_value = value.get(field_name)
        if field_value is None and field_name in {"top_k", "top_p"}:
            continue
        if field_value is not None and (
            isinstance(field_value, bool)
            or not isinstance(field_value, (int, float))
            or not math.isfinite(field_value)
            or field_value < minimum
            or field_value > maximum
        ):
            raise HTTPException(422, f"invalid {field_name}")
    for field_name in ("research_thinking_summaries", "research_visualization"):
        if field_name in value and not isinstance(value[field_name], bool):
            raise HTTPException(422, f"invalid {field_name}")
    allowed_names = set(ModelConfig.__annotations__) | {"tools"}
    return {key: value[key] for key in allowed_names if key in value}


@app.put("/api/settings/nodes/{node_id}")
def put_node_settings(node_id: str, request: Request, value: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    valid_nodes = {item["id"] for item in node_settings(request)}
    if node_id not in valid_nodes:
        raise HTTPException(404, "node not found")
    allowed = _validated_node_config(node_id, value)
    services(request)[0].set_node_config(node_id, allowed)
    return {"id": node_id, **allowed}


@app.get("/api/keys")
def list_keys(request: Request) -> list[dict[str, Any]]:
    return services(request)[1].list()


@app.post("/api/keys", status_code=201)
def create_key(request: Request, value: KeyInput) -> dict[str, Any]:
    return services(request)[1].put(value.provider, value.label, value.value)


@app.put("/api/keys/{key_id}")
def update_key(key_id: str, request: Request, value: KeyInput) -> dict[str, Any]:
    if not services(request)[1].get(key_id):
        raise HTTPException(404, "key not found")
    return services(request)[1].put(value.provider, value.label, value.value, key_id)


@app.delete("/api/keys/{key_id}", status_code=204)
def delete_key(key_id: str, request: Request):
    if not services(request)[1].delete(key_id):
        raise HTTPException(404, "key not found")


frontend_dist = ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def development_landing():
        return "<h1>Dialogical Foundry</h1><p>Build the frontend with <code>npm run build</code> in <code>frontend/</code>.</p><p><a href='/api/docs'>API documentation</a></p>"


def cli() -> None:
    uvicorn.run("server.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    cli()

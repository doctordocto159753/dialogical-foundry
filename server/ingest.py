from __future__ import annotations

import io
import re
from pathlib import Path, PurePath
from typing import Any

import httpx
from fastapi import UploadFile
from pypdf import PdfReader

from .settings import Settings

GITHUB_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
TEXT_SUFFIXES = {".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".toml", ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".sql", ".csv"}
SKIP_PARTS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "coverage"}
TEXT_BASENAMES = {"readme", "license", "copying", "dockerfile", "makefile", "procfile"}


def word_count(value: str) -> int:
    return len(value.split())


def safe_name(value: str) -> str:
    name = PurePath(value).name
    if name in {"", ".", ".."} or "\x00" in name:
        raise ValueError("unsafe filename")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def is_text_path(value: str) -> bool:
    path = Path(value)
    basename = path.name.lower()
    return path.suffix.lower() in TEXT_SUFFIXES or basename in TEXT_BASENAMES or basename.startswith(("readme.", "license."))


async def extract_uploads(files: list[UploadFile], input_dir: Path, limits: Settings) -> tuple[list[str], list[dict[str, Any]]]:
    if len(files) > limits.max_files:
        raise ValueError(f"at most {limits.max_files} files are allowed")
    texts: list[str] = []
    manifest: list[dict[str, Any]] = []
    total = 0
    input_dir.mkdir(parents=True, exist_ok=True)
    for index, upload in enumerate(files):
        data = await upload.read(limits.max_file_bytes + 1)
        if len(data) > limits.max_file_bytes:
            raise ValueError(f"{upload.filename} exceeds the per-file limit")
        total += len(data)
        if total > limits.max_total_bytes:
            raise ValueError("uploads exceed the aggregate size limit")
        name = safe_name(upload.filename or f"file-{index}.txt")
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf":
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        elif suffix in TEXT_SUFFIXES or (upload.content_type or "").startswith("text/"):
            text = data.decode("utf-8")
        else:
            raise ValueError(f"unsupported file type: {name}")
        stored = input_dir / f"{index:02d}-{name}"
        stored.write_bytes(data)
        texts.append(f"FILE: {name}\n{text[:50_000]}")
        manifest.append({"name": name, "bytes": len(data), "stored_as": stored.name, "truncated": len(text) > 50_000})
    return texts, manifest


async def fetch_public_github(url: str, limits: Settings) -> tuple[str, dict[str, Any]]:
    match = GITHUB_RE.fullmatch(url.strip())
    if not match:
        raise ValueError("GitHub URL must be a canonical public https://github.com/owner/repo URL")
    owner, repo = match.groups()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "dialogical-foundry/1.0"}
    async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=False) as client:
        metadata = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if metadata.status_code == 404:
            raise ValueError("public GitHub repository was not found")
        metadata.raise_for_status()
        default_branch = metadata.json()["default_branch"]
        tree_response = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}", params={"recursive": "1"})
        tree_response.raise_for_status()
        candidates = []
        for item in tree_response.json().get("tree", []):
            path = item.get("path", "")
            parts = set(Path(path).parts)
            if item.get("type") == "blob" and is_text_path(path) and not parts.intersection(SKIP_PARTS) and int(item.get("size", 0)) <= limits.max_file_bytes:
                candidates.append(path)
        candidates = candidates[: limits.max_repo_files]
        chunks: list[str] = []
        total_chars = 0
        for path in candidates:
            raw = await client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}")
            if raw.status_code != 200:
                continue
            text = raw.text
            remaining = limits.max_repo_chars - total_chars
            if remaining <= 0:
                break
            text = text[:remaining]
            chunks.append(f"REPO FILE: {path}\n{text}")
            total_chars += len(text)
    return "\n\n---\n\n".join(chunks), {"url": url, "default_branch": default_branch, "files_included": len(chunks), "truncated": len(candidates) >= limits.max_repo_files or total_chars >= limits.max_repo_chars}

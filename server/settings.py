from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("FOUNDRY_DATA_DIR", ROOT / "data")).resolve()
    host: str = os.environ.get("FOUNDRY_HOST", "127.0.0.1")
    port: int = int(os.environ.get("FOUNDRY_PORT", "8000"))
    max_files: int = 5
    max_file_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024
    max_pasted_chars: int = 100_000
    max_repo_files: int = 40
    max_repo_chars: int = 250_000

    @property
    def database_path(self) -> Path:
        return self.data_dir / "foundry.sqlite3"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


settings = Settings()

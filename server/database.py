from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            migration = Path(__file__).with_name("migrations") / "001_initial.sql"
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO app_settings(id, value_json, updated_at) VALUES(1, ?, ?)", (json.dumps({"default_format": "json", "loops": {"ideation": 4, "architecture": 2, "workpackage": 2}, "search_provider": "mock", "search_key_ref": None}), now()))

    def create_run(self, run_id: str, brief: str, artifacts: list[str], fmt: str, loops: dict[str, int]) -> None:
        stamp = now()
        with self._write_lock, self.connect() as db:
            db.execute("INSERT INTO runs(id,status,format,brief,artifacts_json,loops_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (run_id, "pending", fmt, brief, json.dumps(artifacts, ensure_ascii=False), json.dumps(loops), stamp, stamp))

    def update_run(self, run_id: str, **values: Any) -> None:
        allowed = {"status", "tokens_json", "completed_layers_json", "error"}
        fields = [(key, value) for key, value in values.items() if key in allowed]
        if not fields:
            return
        assignments = ",".join(f"{key}=?" for key, _ in fields) + ",updated_at=?"
        with self._write_lock, self.connect() as db:
            db.execute(f"UPDATE runs SET {assignments} WHERE id=?", ([value for _, value in fields] + [now(), run_id]))

    @staticmethod
    def _run(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        for source, target in (("artifacts_json", "artifacts"), ("loops_json", "loops"), ("tokens_json", "tokens"), ("completed_layers_json", "completed_layers")):
            value[target] = json.loads(value.pop(source))
        return value

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [self._run(row) for row in db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

    def delete_run(self, run_id: str) -> bool:
        with self._write_lock, self.connect() as db:
            result = db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            return result.rowcount > 0

    def interrupt_orphans(self) -> list[str]:
        with self._write_lock, self.connect() as db:
            run_ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM runs WHERE status IN ('pending','running')"
                ).fetchall()
            ]
            db.execute(
                "UPDATE runs SET status='interrupted', updated_at=? "
                "WHERE status IN ('pending','running')",
                (now(),),
            )
        return run_ids

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        with self._write_lock, self.connect() as db:
            seq = int(db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM run_events WHERE run_id=?", (run_id,)).fetchone()[0])
            db.execute("INSERT INTO run_events(run_id,seq,type,payload_json,created_at) VALUES(?,?,?,?,?)", (run_id, seq, event_type, json.dumps(payload, ensure_ascii=False), now()))
            return seq

    def events_after(self, run_id: str, seq: int) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, seq)).fetchall()
        return [{"seq": row["seq"], "run_id": run_id, "type": row["type"], "at": row["created_at"], "payload": json.loads(row["payload_json"])} for row in rows]

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            return json.loads(db.execute("SELECT value_json FROM app_settings WHERE id=1").fetchone()[0])

    def set_settings(self, value: dict[str, Any]) -> None:
        with self._write_lock, self.connect() as db:
            db.execute("UPDATE app_settings SET value_json=?, updated_at=? WHERE id=1", (json.dumps(value), now()))

    def node_configs(self) -> dict[str, dict[str, Any]]:
        with self.connect() as db:
            return {row["node_id"]: json.loads(row["config_json"]) for row in db.execute("SELECT * FROM node_configs")}

    def set_node_config(self, node_id: str, value: dict[str, Any]) -> None:
        with self._write_lock, self.connect() as db:
            db.execute("INSERT INTO node_configs(node_id,config_json,updated_at) VALUES(?,?,?) ON CONFLICT(node_id) DO UPDATE SET config_json=excluded.config_json, updated_at=excluded.updated_at", (node_id, json.dumps(value), now()))

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from .database import Database, now


class KeyStore:
    def __init__(self, db: Database, data_dir: Path):
        self.db = db
        env_key = os.environ.get("FOUNDRY_MASTER_KEY")
        key_path = data_dir / ".master-key"
        if env_key:
            key = env_key.encode()
        elif key_path.exists():
            key = key_path.read_bytes().strip()
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        self.cipher = Fernet(key)

    def list(self) -> list[dict[str, Any]]:
        with self.db.connect() as db:
            rows = db.execute("SELECT id,provider,label,fingerprint,created_at,updated_at FROM keystore ORDER BY label").fetchall()
            return [dict(row) for row in rows]

    def get(self, key_id: str) -> str | None:
        with self.db.connect() as db:
            row = db.execute("SELECT encrypted_value FROM keystore WHERE id=?", (key_id,)).fetchone()
        return self.cipher.decrypt(row[0]).decode() if row else None

    def put(self, provider: str, label: str, value: str, key_id: str | None = None) -> dict[str, Any]:
        if not value.strip():
            raise ValueError("key value cannot be empty")
        key_id = key_id or uuid.uuid4().hex
        fingerprint = hashlib.sha256(value.encode()).hexdigest()[:12]
        encrypted = self.cipher.encrypt(value.encode())
        stamp = now()
        with self.db._write_lock, self.db.connect() as db:
            db.execute("INSERT INTO keystore(id,provider,label,encrypted_value,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,label=excluded.label,encrypted_value=excluded.encrypted_value,fingerprint=excluded.fingerprint,updated_at=excluded.updated_at", (key_id, provider, label, encrypted, fingerprint, stamp, stamp))
        return next(item for item in self.list() if item["id"] == key_id)

    def delete(self, key_id: str) -> bool:
        with self.db._write_lock, self.db.connect() as db:
            result = db.execute("DELETE FROM keystore WHERE id=?", (key_id,))
            return result.rowcount > 0

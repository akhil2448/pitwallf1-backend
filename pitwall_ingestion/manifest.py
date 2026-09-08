from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionRecord:
    key: str
    year: int
    round_number: int
    session_type: str
    event_name: str
    session_date: str | None = None
    status: str = "missing"
    fastf1_version: str | None = None
    attempted_at: str | None = None
    completed_at: str | None = None
    last_error: str | None = None
    retries: int = 0
    size_bytes: int | None = None
    cache_path: str | None = None
    files: list[str] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)


class Manifest:
    CURRENT_SCHEMA = 1

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {
            "schema_version": self.CURRENT_SCHEMA,
            "generated_at": utc_now(),
            "sessions": {},
            "last_run": None,
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if loaded.get("schema_version") != self.CURRENT_SCHEMA:
            raise RuntimeError(
                f"Unsupported manifest schema: {loaded.get('schema_version')}"
            )
        self.data = loaded

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["generated_at"] = utc_now()
        fd, temp_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data["sessions"].get(key)

    def upsert(self, record: SessionRecord) -> None:
        self.data["sessions"][record.key] = asdict(record)

    def update(self, key: str, **fields: Any) -> SessionRecord:
        raw = self.data["sessions"].get(key)
        if raw is None:
            raise KeyError(key)
        raw.update(fields)
        return SessionRecord(**raw)

    def set_last_run(self, summary: dict[str, Any]) -> None:
        self.data["last_run"] = summary

    def complete_count(self) -> int:
        return sum(
            1 for r in self.data["sessions"].values()
            if r.get("status") == "complete"
        )

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL,
    engine TEXT NOT NULL,
    text TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    edi_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def create(
        self,
        *,
        source: str,
        engine: str,
        text: str,
        fields: dict[str, Any],
        quality: dict[str, Any],
        edi: dict[str, str],
        warnings: list[str],
        status: str = "recognized",
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        timestamp = now_iso()
        row = {
            "id": job_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "engine": engine,
            "text": text,
            "fields_json": json.dumps(fields, ensure_ascii=False),
            "quality_json": json.dumps(quality, ensure_ascii=False),
            "edi_json": json.dumps(edi, ensure_ascii=False),
            "warnings_json": json.dumps(warnings, ensure_ascii=False),
            "status": status,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, created_at, updated_at, source, engine, text, fields_json,
                    quality_json, edi_json, warnings_json, status
                ) VALUES (
                    :id, :created_at, :updated_at, :source, :engine, :text,
                    :fields_json, :quality_json, :edi_json, :warnings_json, :status
                )
                """,
                row,
            )
        return self._decode(row)

    def list(self, query: str = "", limit: int = 80) -> list[dict[str, Any]]:
        like = f"%{query.strip()}%"
        params: tuple[Any, ...]
        where = ""
        if query.strip():
            where = """
            WHERE source LIKE ?
               OR fields_json LIKE ?
               OR engine LIKE ?
               OR status LIKE ?
            """
            params = (like, like, like, like, limit)
        else:
            params = (limit,)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM jobs
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._decode(dict(row)) for row in rows]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._decode(dict(row)) if row else None

    def update(
        self,
        job_id: str,
        *,
        fields: dict[str, Any],
        quality: dict[str, Any],
        edi: dict[str, str],
        warnings: list[str],
        status: str,
    ) -> dict[str, Any] | None:
        timestamp = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET updated_at = ?,
                    fields_json = ?,
                    quality_json = ?,
                    edi_json = ?,
                    warnings_json = ?,
                    status = ?
                WHERE id = ?
                """,
                (
                    timestamp,
                    json.dumps(fields, ensure_ascii=False),
                    json.dumps(quality, ensure_ascii=False),
                    json.dumps(edi, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    status,
                    job_id,
                ),
            )
        return self.get(job_id)

    def _decode(self, row: dict[str, Any]) -> dict[str, Any]:
        fields = json.loads(row.pop("fields_json"))
        quality = json.loads(row.pop("quality_json"))
        edi = json.loads(row.pop("edi_json"))
        warnings = json.loads(row.pop("warnings_json"))
        return {**row, "fields": fields, "quality": quality, "edi": edi, "warnings": warnings}

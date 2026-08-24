from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .db import Database
from .governance import resolve_field_row


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EntityService:
    def __init__(self, db: Database):
        self.db = db

    def create_entity(self, *, label: str, kind: str = "record", entity_id: str | None = None) -> dict[str, Any]:
        label = label.strip()
        kind = kind.strip() or "record"
        if not label:
            raise ValueError("entity label is required")
        entity_id = entity_id or uuid4().hex
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
                (entity_id, kind, label, now, now),
            )
        return self.get_entity(entity_id, include_cells=False)

    def list_entities(self, *, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entities ORDER BY created_at, id LIMIT ? OFFSET ?",
                (max(1, min(limit, 10000)), max(0, offset)),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_entity(self, entity_id: str, *, include_cells: bool = True) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
            if row is None:
                raise KeyError(f"entity not found: {entity_id}")
            result = dict(row)
            if not include_cells:
                return result
            cell_rows = conn.execute(
                """
                SELECT f.key, c.value_json, c.source, c.confidence, c.updated_at
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                WHERE c.entity_id=?
                ORDER BY f.key
                """,
                (entity_id,),
            ).fetchall()
        values: dict[str, Any] = {}
        cells: dict[str, dict[str, Any]] = {}
        for cell in cell_rows:
            value = json.loads(cell["value_json"])
            values[cell["key"]] = value
            cells[cell["key"]] = {
                "value": value,
                "source": cell["source"],
                "confidence": cell["confidence"],
                "updated_at": cell["updated_at"],
            }
        result["values"] = values
        result["cells"] = cells
        return result

    def _resolve_field(self, conn, field_key: str):
        return resolve_field_row(conn, field_key)

    def _require_entity(self, conn, entity_id: str) -> None:
        if conn.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone() is None:
            raise KeyError(f"entity not found: {entity_id}")

    def set_cell(
        self,
        entity_id: str,
        field_key: str,
        value: Any,
        *,
        source: str = "",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        now = _now()
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.db.connect() as conn:
            self._require_entity(conn, entity_id)
            field = self._resolve_field(conn, field_key)
            conn.execute(
                """
                INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(entity_id,field_id) DO UPDATE SET
                    value_json=excluded.value_json,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (entity_id, field["id"], payload, source, confidence, now),
            )
            conn.execute("UPDATE entities SET updated_at=? WHERE id=?", (now, entity_id))
        return self.get_entity(entity_id)["cells"][field["key"]]

    def delete_cell(self, entity_id: str, field_key: str) -> bool:
        now = _now()
        with self.db.connect() as conn:
            self._require_entity(conn, entity_id)
            field = self._resolve_field(conn, field_key)
            cur = conn.execute(
                "DELETE FROM cells WHERE entity_id=? AND field_id=?",
                (entity_id, field["id"]),
            )
            if cur.rowcount:
                conn.execute("UPDATE entities SET updated_at=? WHERE id=?", (now, entity_id))
                return True
            return False

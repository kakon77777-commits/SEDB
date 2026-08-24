from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .db import Database
from .governance import resolve_field_row


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ViewService:
    def __init__(self, db: Database):
        self.db = db

    def create_view(self, name: str, field_keys: Iterable[str], *, query_text: str = "") -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("view name is required")
        keys = list(dict.fromkeys(str(key).strip() for key in field_keys if str(key).strip()))
        if not keys:
            raise ValueError("at least one field is required")
        with self.db.connect() as conn:
            resolved = []
            for key in keys:
                resolved.append(resolve_field_row(conn, key))
            view_id = uuid4().hex
            now = _now()
            conn.execute(
                "INSERT INTO task_views(id,name,query_text,created_at) VALUES(?,?,?,?)",
                (view_id, name, query_text, now),
            )
            conn.executemany(
                "INSERT INTO task_view_fields(view_id,field_id,ordinal) VALUES(?,?,?)",
                [(view_id, row["id"], ordinal) for ordinal, row in enumerate(resolved)],
            )
        return self.get_view(view_id)

    def get_view(self, view_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            view = conn.execute("SELECT * FROM task_views WHERE id=?", (view_id,)).fetchone()
            if view is None:
                raise KeyError(f"view not found: {view_id}")
            fields = conn.execute(
                """
                SELECT f.id,f.key,f.label,f.value_type,f.status,tvf.ordinal
                FROM task_view_fields tvf
                JOIN fields f ON f.id=tvf.field_id
                WHERE tvf.view_id=?
                ORDER BY tvf.ordinal
                """,
                (view_id,),
            ).fetchall()
        result = dict(view)
        result["fields"] = [dict(row) for row in fields]
        return result

    def list_views(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*, COUNT(vf.field_id) AS field_count
                FROM task_views v
                LEFT JOIN task_view_fields vf ON vf.view_id=v.id
                GROUP BY v.id
                ORDER BY v.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_view_matrix(
        self,
        view_id: str,
        *,
        field_offset: int = 0,
        field_limit: int = 25,
        entity_limit: int = 1000,
        entity_offset: int = 0,
    ) -> dict[str, Any]:
        field_offset = max(0, int(field_offset))
        field_limit = max(1, min(int(field_limit), 200))
        entity_limit = max(1, min(int(entity_limit), 5000))
        entity_offset = max(0, int(entity_offset))
        with self.db.connect() as conn:
            view = conn.execute("SELECT * FROM task_views WHERE id=?", (view_id,)).fetchone()
            if view is None:
                raise KeyError(f"view not found: {view_id}")
            total_fields = conn.execute(
                "SELECT COUNT(*) FROM task_view_fields WHERE view_id=?", (view_id,)
            ).fetchone()[0]
            field_rows = conn.execute(
                """
                SELECT f.id,f.key,f.label,f.value_type,f.status,tvf.ordinal
                FROM task_view_fields tvf
                JOIN fields f ON f.id=tvf.field_id
                WHERE tvf.view_id=?
                ORDER BY tvf.ordinal
                LIMIT ? OFFSET ?
                """,
                (view_id, field_limit, field_offset),
            ).fetchall()
            entity_rows = conn.execute(
                "SELECT * FROM entities ORDER BY created_at,id LIMIT ? OFFSET ?",
                (entity_limit, entity_offset),
            ).fetchall()
            total_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            values_by_entity: dict[str, dict[str, Any]] = {row["id"]: {} for row in entity_rows}
            if field_rows and entity_rows:
                field_ids = [row["id"] for row in field_rows]
                entity_ids = [row["id"] for row in entity_rows]
                field_placeholders = ",".join("?" for _ in field_ids)
                entity_placeholders = ",".join("?" for _ in entity_ids)
                sql = f"""
                    SELECT c.entity_id,f.key,c.value_json
                    FROM cells c
                    JOIN fields f ON f.id=c.field_id
                    WHERE c.field_id IN ({field_placeholders})
                      AND c.entity_id IN ({entity_placeholders})
                """
                for cell in conn.execute(sql, [*field_ids, *entity_ids]).fetchall():
                    values_by_entity[cell["entity_id"]][cell["key"]] = json.loads(cell["value_json"])
        rows = []
        for entity in entity_rows:
            item = dict(entity)
            item["values"] = values_by_entity[entity["id"]]
            rows.append(item)
        return {
            "view": dict(view),
            "total_fields": total_fields,
            "field_offset": field_offset,
            "field_limit": field_limit,
            "fields": [dict(row) for row in field_rows],
            "total_entities": total_entities,
            "entity_offset": entity_offset,
            "rows": rows,
        }

    def search(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 500))
        needle = f"%{query}%"
        results: list[dict[str, Any]] = []
        with self.db.connect() as conn:
            field_rows = conn.execute(
                """
                SELECT id,key,label,value_type,status FROM fields
                WHERE key LIKE ? OR label LIKE ? OR description LIKE ?
                ORDER BY key LIMIT ?
                """,
                (needle, needle, needle, limit),
            ).fetchall()
            for row in field_rows:
                item = dict(row)
                item["type"] = "field"
                results.append(item)
            remaining = max(0, limit - len(results))
            if remaining:
                entity_rows = conn.execute(
                    "SELECT id,kind,label FROM entities WHERE id LIKE ? OR label LIKE ? ORDER BY label LIMIT ?",
                    (needle, needle, remaining),
                ).fetchall()
                for row in entity_rows:
                    item = dict(row)
                    item["type"] = "entity"
                    results.append(item)
            remaining = max(0, limit - len(results))
            if remaining:
                cell_rows = conn.execute(
                    """
                    SELECT c.entity_id,e.label AS entity_label,f.key AS field_key,c.value_json
                    FROM cells c
                    JOIN entities e ON e.id=c.entity_id
                    JOIN fields f ON f.id=c.field_id
                    WHERE c.value_json LIKE ?
                    ORDER BY e.label,f.key
                    LIMIT ?
                    """,
                    (needle, remaining),
                ).fetchall()
                for row in cell_rows:
                    item = dict(row)
                    item["value"] = json.loads(item.pop("value_json"))
                    item["type"] = "cell"
                    results.append(item)
        return results[:limit]

    def stats(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            fields = conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
            active_fields = conn.execute("SELECT COUNT(*) FROM fields WHERE status='active'").fetchone()[0]
            converged_fields = conn.execute("SELECT COUNT(*) FROM fields WHERE status='converged'").fetchone()[0]
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            cells = conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
            proposals = conn.execute("SELECT COUNT(*) FROM field_proposals").fetchone()[0]
            views = conn.execute("SELECT COUNT(*) FROM task_views").fetchone()[0]
        logical_capacity = fields * entities
        density = 0.0 if logical_capacity == 0 else cells / logical_capacity
        return {
            "fields": fields,
            "active_fields": active_fields,
            "converged_fields": converged_fields,
            "entities": entities,
            "cells": cells,
            "proposals": proposals,
            "views": views,
            "logical_capacity": logical_capacity,
            "density": density,
        }

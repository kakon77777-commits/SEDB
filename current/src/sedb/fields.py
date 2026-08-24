from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .db import Database
from .naming import normalize_field_key


ALLOWED_TRANSITIONS = {
    "proposed": {"active", "deprecated"},
    "active": {"converged", "merged", "split", "deprecated"},
    "converged": {"active", "merged", "split", "deprecated"},
    "merged": set(),
    "split": set(),
    "deprecated": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


class FieldService:
    def __init__(self, db: Database):
        self.db = db

    def create_field(
        self,
        *,
        key: str,
        label: str,
        value_type: str = "text",
        description: str = "",
        status: str = "active",
        namespace: str = "global",
    ) -> dict[str, Any]:
        key = key.strip()
        label = label.strip()
        namespace = namespace.strip() or "global"
        if not key or not label:
            raise ValueError("field key and label are required")
        if status not in ALLOWED_TRANSITIONS:
            raise ValueError(f"unsupported field status: {status}")
        normalized_key = normalize_field_key(key)
        field_id = uuid4().hex
        now = _now()
        try:
            with self.db.connect() as conn:
                duplicate = conn.execute(
                    "SELECT id,key FROM fields WHERE namespace=? AND normalized_key=?",
                    (namespace, normalized_key),
                ).fetchone()
                if duplicate is not None:
                    raise ValueError(
                        f"normalized field key already exists in namespace {namespace}: {duplicate['key']}"
                    )
                conn.execute(
                    """
                    INSERT INTO fields(
                        id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        field_id, key, label, value_type, description, status, now, now,
                        namespace, normalized_key,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO field_events(field_id,event_type,from_status,to_status,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (field_id, "created", None, status, now),
                )
                conn.execute(
                    """
                    INSERT INTO field_versions(
                        field_id,version,label,value_type,description,reason,evaluator,created_at
                    ) VALUES(?,1,?,?,?,?,?,?)
                    """,
                    (field_id, label, value_type, description, "field created", "system:registry", now),
                )
        except sqlite3.IntegrityError as exc:
            if "fields.key" in str(exc):
                raise ValueError(f"field key already exists: {key}") from exc
            raise
        return self.get_field(field_id)

    def bulk_create_fields(self, specs: Iterable[dict[str, Any]]) -> int:
        prepared: list[tuple[str, str, str, str, str, str, str, str, str, str]] = []
        events: list[tuple[str, str, None, str, str]] = []
        versions: list[tuple[str, int, str, str, str, str, str, str]] = []
        now = _now()
        seen_raw: set[str] = set()
        seen_normalized: set[tuple[str, str]] = set()
        with self.db.connect() as conn:
            existing = {
                (row["namespace"], row["normalized_key"])
                for row in conn.execute(
                    "SELECT namespace,normalized_key FROM fields WHERE normalized_key IS NOT NULL"
                ).fetchall()
            }
        for spec in specs:
            key = str(spec["key"]).strip()
            label = str(spec.get("label") or key).strip()
            status = str(spec.get("status", "active"))
            namespace = str(spec.get("namespace", "global")).strip() or "global"
            if not key or not label:
                raise ValueError("field key and label are required")
            if key in seen_raw:
                raise ValueError(f"duplicate field key in batch: {key}")
            if status not in ALLOWED_TRANSITIONS:
                raise ValueError(f"unsupported field status: {status}")
            normalized_key = normalize_field_key(key)
            identity = (namespace, normalized_key)
            if identity in existing or identity in seen_normalized:
                raise ValueError(
                    f"normalized field key already exists in namespace {namespace}: {key}"
                )
            seen_raw.add(key)
            seen_normalized.add(identity)
            field_id = uuid4().hex
            prepared.append(
                (
                    field_id,
                    key,
                    label,
                    str(spec.get("value_type", "text")),
                    str(spec.get("description", "")),
                    status,
                    now,
                    now,
                    namespace,
                    normalized_key,
                )
            )
            events.append((field_id, "created", None, status, now))
            versions.append(
                (
                    field_id, 1, label, str(spec.get("value_type", "text")),
                    str(spec.get("description", "")), "field created", "system:registry", now,
                )
            )
        if not prepared:
            return 0
        try:
            with self.db.connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO fields(
                        id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    prepared,
                )
                conn.executemany(
                    """
                    INSERT INTO field_events(field_id,event_type,from_status,to_status,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    events,
                )
                conn.executemany(
                    """
                    INSERT INTO field_versions(
                        field_id,version,label,value_type,description,reason,evaluator,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    versions,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"bulk field registration failed: {exc}") from exc
        return len(prepared)

    def get_field(self, field_id_or_key: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM fields WHERE id=? OR key=?",
                (field_id_or_key, field_id_or_key),
            ).fetchone()
        if row is None:
            raise KeyError(f"field not found: {field_id_or_key}")
        return dict(row)

    def list_fields(
        self,
        *,
        search: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if search:
            where.append("(key LIKE ? OR label LIKE ? OR description LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        if status:
            where.append("status=?")
            params.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, min(limit, 10000)), max(0, offset)])
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fields {clause} ORDER BY key LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(
        self,
        field_id: str,
        to_status: str,
        *,
        reason: str = "",
        evidence: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        evaluator: str = "",
        reversible: bool = True,
    ) -> dict[str, Any]:
        if to_status in {"merged", "split"}:
            raise ValueError("merged/split transitions require governance lineage operations")
        current = self.get_field(field_id)
        from_status = current["status"]
        if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
            raise ValueError(f"illegal field transition: {from_status} -> {to_status}")
        reason = reason.strip()
        needs_reason = to_status == "converged" or (from_status == "converged" and to_status == "active")
        if needs_reason and not reason:
            raise ValueError("reason is required for convergence/reactivation")
        evidence = evidence or {}
        metrics = metrics or {}
        now = _now()
        if to_status == "converged":
            event_type = "converged"
            decision = "converge"
        elif from_status == "converged" and to_status == "active":
            event_type = "reactivated"
            decision = "reactivate"
        else:
            event_type = to_status
            decision = ""
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE fields SET status=?, updated_at=? WHERE id=?",
                (to_status, now, current["id"]),
            )
            conn.execute(
                """
                INSERT INTO field_events(
                    field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    current["id"],
                    event_type,
                    from_status,
                    to_status,
                    reason,
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    evaluator,
                    now,
                ),
            )
            if decision:
                conn.execute(
                    """
                    INSERT INTO field_evaluations(
                        field_id,decision,reason,evidence_json,metrics_json,evaluator,reversible,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        current["id"],
                        decision,
                        reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                        evaluator,
                        int(bool(reversible)),
                        now,
                    ),
                )
        return self.get_field(current["id"])

    def list_evaluations(self, field_id: str) -> list[dict[str, Any]]:
        field = self.get_field(field_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_evaluations WHERE field_id=? ORDER BY id",
                (field["id"],),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["reversible"] = bool(item["reversible"])
            result.append(item)
        return result

    def create_proposal(
        self,
        *,
        key: str,
        label: str,
        reason: str,
        value_type: str = "text",
        description: str = "",
        proposed_by: str = "",
        namespace: str = "global",
    ) -> dict[str, Any]:
        key = key.strip()
        label = label.strip()
        reason = reason.strip()
        namespace = namespace.strip() or "global"
        if not key or not label or not reason:
            raise ValueError("proposal key, label, and reason are required")
        proposal_id = uuid4().hex
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO field_proposals(
                    id,key,label,value_type,description,reason,proposed_by,status,created_at,namespace
                ) VALUES(?,?,?,?,?,?,?,'pending',?,?)
                """,
                (
                    proposal_id, key, label, value_type, description, reason, proposed_by,
                    now, namespace,
                ),
            )
        return self.get_proposal(proposal_id)

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        return dict(row)

    def list_proposals(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_proposals ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (max(1, min(limit, 1000)), max(0, offset)),
            ).fetchall()
        return [dict(row) for row in rows]

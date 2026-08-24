from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .db import Database
from .naming import normalize_field_key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_field_row(
    conn: sqlite3.Connection,
    ref: str,
    namespace: str = "global",
) -> sqlite3.Row:
    ref = str(ref).strip()
    namespace = str(namespace).strip() or "global"
    if not ref:
        raise KeyError("field reference is required")

    row = conn.execute(
        "SELECT * FROM fields WHERE id=? OR key=? ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END LIMIT 1",
        (ref, ref, ref),
    ).fetchone()
    if row is not None:
        return row

    try:
        normalized = normalize_field_key(ref)
    except ValueError as exc:
        raise KeyError(f"field not found: {ref}") from exc

    canonical = conn.execute(
        "SELECT * FROM fields WHERE namespace=? AND normalized_key=? ORDER BY id LIMIT 2",
        (namespace, normalized),
    ).fetchall()
    if len(canonical) == 1:
        return canonical[0]
    if len(canonical) > 1:
        raise ValueError(
            f"ambiguous normalized field identity in namespace {namespace}: {ref}"
        )

    alias_rows = conn.execute(
        """
        SELECT f.*
        FROM field_aliases a
        JOIN fields f ON f.id=a.field_id
        WHERE a.namespace=? AND a.normalized_alias=?
        ORDER BY a.id
        LIMIT 2
        """,
        (namespace, normalized),
    ).fetchall()
    if len(alias_rows) == 1:
        return alias_rows[0]
    if len(alias_rows) > 1:
        raise ValueError(f"ambiguous alias in namespace {namespace}: {ref}")
    raise KeyError(f"field not found: {ref}")


class FieldGovernanceService:
    def __init__(self, db: Database):
        self.db = db

    def resolve_field(self, ref: str, namespace: str = "global") -> dict[str, Any]:
        with self.db.connect() as conn:
            return dict(resolve_field_row(conn, ref, namespace))

    def add_alias(
        self,
        field_ref: str,
        alias: str,
        *,
        namespace: str = "global",
        reason: str = "",
    ) -> dict[str, Any]:
        alias = str(alias).strip()
        namespace = str(namespace).strip() or "global"
        if not alias:
            raise ValueError("alias is required")
        normalized_alias = normalize_field_key(alias)
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref, namespace)

            canonical_conflict = conn.execute(
                """
                SELECT id,key FROM fields
                WHERE namespace=? AND normalized_key=?
                ORDER BY id LIMIT 2
                """,
                (namespace, normalized_alias),
            ).fetchall()
            for conflict in canonical_conflict:
                if conflict["id"] != field["id"]:
                    raise ValueError(
                        f"alias conflicts with canonical field in namespace {namespace}: {conflict['key']}"
                    )

            existing = conn.execute(
                "SELECT * FROM field_aliases WHERE namespace=? AND normalized_alias=?",
                (namespace, normalized_alias),
            ).fetchone()
            if existing is not None:
                if existing["field_id"] != field["id"]:
                    raise ValueError(
                        f"alias already resolves to another field in namespace {namespace}: {alias}"
                    )
                return dict(existing)

            now = _now()
            cur = conn.execute(
                """
                INSERT INTO field_aliases(namespace,alias,normalized_alias,field_id,reason,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (namespace, alias, normalized_alias, field["id"], reason.strip(), now),
            )
            row = conn.execute(
                "SELECT * FROM field_aliases WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
        return dict(row)

    def list_aliases(self, field_ref: str, namespace: str = "global") -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref, namespace)
            rows = conn.execute(
                "SELECT * FROM field_aliases WHERE field_id=? ORDER BY id",
                (field["id"],),
            ).fetchall()
        return [dict(row) for row in rows]
    def get_proposal_decision(self, proposal_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proposal_decisions WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"proposal decision not found: {proposal_id}")
        item = dict(row)
        import json
        item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def decide_proposal(
        self,
        proposal_id: str,
        decision: str,
        *,
        reason: str,
        evaluator: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json

        token = str(decision).strip().lower()
        if token in {"accept", "accepted"}:
            final_decision = "accepted"
        elif token in {"reject", "rejected"}:
            final_decision = "rejected"
        else:
            raise ValueError("proposal decision must be accept or reject")
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for proposal decisions")
        evidence = evidence or {}
        now = _now()

        with self.db.connect() as conn:
            proposal = conn.execute(
                "SELECT * FROM field_proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
            if proposal is None:
                raise KeyError(f"proposal not found: {proposal_id}")
            if proposal["status"] != "pending":
                raise ValueError(f"proposal already decided: {proposal['status']}")

            target_field_id: str | None = None
            outcome = "rejected"
            if final_decision == "accepted":
                namespace = proposal["namespace"] or "global"
                normalized = normalize_field_key(proposal["key"])
                matches = conn.execute(
                    "SELECT * FROM fields WHERE namespace=? AND normalized_key=? ORDER BY id LIMIT 2",
                    (namespace, normalized),
                ).fetchall()
                if len(matches) > 1:
                    raise ValueError(
                        f"ambiguous normalized field identity in namespace {namespace}: {proposal['key']}"
                    )
                if matches:
                    target = matches[0]
                    target_field_id = target["id"]
                    existing_alias = conn.execute(
                        "SELECT * FROM field_aliases WHERE namespace=? AND normalized_alias=?",
                        (namespace, normalized),
                    ).fetchone()
                    if existing_alias is not None and existing_alias["field_id"] != target_field_id:
                        raise ValueError(
                            f"alias already resolves to another field in namespace {namespace}: {proposal['key']}"
                        )
                    if existing_alias is None:
                        conn.execute(
                            """
                            INSERT INTO field_aliases(
                                namespace,alias,normalized_alias,field_id,reason,created_at
                            ) VALUES(?,?,?,?,?,?)
                            """,
                            (namespace, proposal["key"], normalized, target_field_id, reason, now),
                        )
                    outcome = "alias_existing"
                else:
                    target_field_id = uuid4().hex
                    try:
                        conn.execute(
                            """
                            INSERT INTO fields(
                                id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
                            ) VALUES(?,?,?,?,?,'active',?,?,?,?)
                            """,
                            (
                                target_field_id, proposal["key"], proposal["label"],
                                proposal["value_type"], proposal["description"],
                                now, now, namespace, normalized,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise ValueError(
                            f"proposal key conflicts with an existing canonical key: {proposal['key']}"
                        ) from exc
                    conn.execute(
                        """
                        INSERT INTO field_events(field_id,event_type,from_status,to_status,reason,evaluator,created_at)
                        VALUES(?, 'created', NULL, 'active', ?, ?, ?)
                        """,
                        (target_field_id, reason, evaluator, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO field_versions(
                            field_id,version,label,value_type,description,reason,evaluator,created_at
                        ) VALUES(?,1,?,?,?,?,?,?)
                        """,
                        (
                            target_field_id, proposal["label"], proposal["value_type"],
                            proposal["description"], reason, evaluator, now,
                        ),
                    )
                    outcome = "created"

            conn.execute(
                "UPDATE field_proposals SET status=? WHERE id=?",
                (final_decision, proposal_id),
            )
            conn.execute(
                """
                INSERT INTO proposal_decisions(
                    proposal_id,decision,outcome,target_field_id,reason,evidence_json,evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    proposal_id, final_decision, outcome, target_field_id, reason,
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True), evaluator, now,
                ),
            )

        return self.get_proposal_decision(proposal_id)
    def list_versions(self, field_ref: str, namespace: str = "global") -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref, namespace)
            rows = conn.execute(
                "SELECT * FROM field_versions WHERE field_id=? ORDER BY version",
                (field["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_definition(
        self,
        field_ref: str,
        *,
        label: str | None = None,
        value_type: str | None = None,
        description: str | None = None,
        reason: str,
        evaluator: str = "",
        namespace: str = "global",
    ) -> dict[str, Any]:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for field definition updates")
        if label is None and value_type is None and description is None:
            raise ValueError("definition update requires at least one changed property")
        now = _now()
        with self.db.connect() as conn:
            current = resolve_field_row(conn, field_ref, namespace)
            new_label = current["label"] if label is None else str(label).strip()
            new_value_type = current["value_type"] if value_type is None else str(value_type).strip()
            new_description = current["description"] if description is None else str(description)
            if not new_label:
                raise ValueError("field label is required")
            if not new_value_type:
                raise ValueError("field value_type is required")
            latest = conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM field_versions WHERE field_id=?",
                (current["id"],),
            ).fetchone()[0]
            conn.execute(
                "UPDATE fields SET label=?,value_type=?,description=?,updated_at=? WHERE id=?",
                (new_label, new_value_type, new_description, now, current["id"]),
            )
            conn.execute(
                """
                INSERT INTO field_versions(
                    field_id,version,label,value_type,description,reason,evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    current["id"], int(latest)+1, new_label, new_value_type, new_description,
                    reason, evaluator, now,
                ),
            )
            updated = conn.execute("SELECT * FROM fields WHERE id=?", (current["id"],)).fetchone()
        return dict(updated)
    def _lineage_rows_for_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM field_lineage WHERE id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        import json
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result

    def merge_fields(
        self,
        source_refs: list[str],
        target_ref: str,
        *,
        reason: str,
        evaluator: str = "",
        evidence: dict[str, Any] | None = None,
        namespace: str = "global",
    ) -> list[dict[str, Any]]:
        import json

        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for field merge")
        source_refs = list(dict.fromkeys(str(ref).strip() for ref in source_refs if str(ref).strip()))
        if not source_refs:
            raise ValueError("at least one merge source is required")
        evidence = evidence or {}
        now = _now()
        inserted_ids: list[int] = []
        with self.db.connect() as conn:
            target = resolve_field_row(conn, target_ref, namespace)
            if target["status"] not in {"active", "converged"}:
                raise ValueError(f"merge target must be active or converged: {target['status']}")
            sources = [resolve_field_row(conn, ref, namespace) for ref in source_refs]
            seen_ids: set[str] = set()
            for source in sources:
                if source["id"] == target["id"]:
                    raise ValueError("merge source cannot equal merge target")
                if source["id"] in seen_ids:
                    continue
                seen_ids.add(source["id"])
                if source["status"] not in {"active", "converged"}:
                    raise ValueError(f"merge source must be active or converged: {source['status']}")
                cur = conn.execute(
                    """
                    INSERT INTO field_lineage(
                        parent_field_id,child_field_id,relation,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,?,'merged_into',?,?,?,?)
                    """,
                    (
                        source["id"], target["id"], reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True), evaluator, now,
                    ),
                )
                inserted_ids.append(int(cur.lastrowid))
                conn.execute(
                    "UPDATE fields SET status='merged',updated_at=? WHERE id=?",
                    (now, source["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO field_events(
                        field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,'merged',?,'merged',?,?,?,?)
                    """,
                    (
                        source["id"], source["status"], reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True), evaluator, now,
                    ),
                )
        return self._lineage_rows_for_ids(inserted_ids)

    def split_field(
        self,
        source_ref: str,
        child_refs: list[str],
        *,
        reason: str,
        evaluator: str = "",
        evidence: dict[str, Any] | None = None,
        namespace: str = "global",
    ) -> list[dict[str, Any]]:
        import json

        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for field split")
        child_refs = list(dict.fromkeys(str(ref).strip() for ref in child_refs if str(ref).strip()))
        if len(child_refs) < 2:
            raise ValueError("field split requires at least two children")
        evidence = evidence or {}
        now = _now()
        inserted_ids: list[int] = []
        with self.db.connect() as conn:
            source = resolve_field_row(conn, source_ref, namespace)
            if source["status"] not in {"active", "converged"}:
                raise ValueError(f"split source must be active or converged: {source['status']}")
            children = [resolve_field_row(conn, ref, namespace) for ref in child_refs]
            child_ids = {child["id"] for child in children}
            if len(child_ids) < 2:
                raise ValueError("field split requires at least two distinct children")
            if source["id"] in child_ids:
                raise ValueError("split source cannot also be a split child")
            for child in children:
                if child["status"] not in {"active", "converged"}:
                    raise ValueError(f"split child must be active or converged: {child['status']}")
                cur = conn.execute(
                    """
                    INSERT INTO field_lineage(
                        parent_field_id,child_field_id,relation,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,?,'split_into',?,?,?,?)
                    """,
                    (
                        source["id"], child["id"], reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True), evaluator, now,
                    ),
                )
                inserted_ids.append(int(cur.lastrowid))
            conn.execute(
                "UPDATE fields SET status='split',updated_at=? WHERE id=?",
                (now, source["id"]),
            )
            conn.execute(
                """
                INSERT INTO field_events(
                    field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at
                ) VALUES(?,'split',?,'split',?,?,?,?)
                """,
                (
                    source["id"], source["status"], reason,
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True), evaluator, now,
                ),
            )
        return self._lineage_rows_for_ids(inserted_ids)

    def list_lineage(self, field_ref: str, namespace: str = "global") -> list[dict[str, Any]]:
        import json

        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref, namespace)
            rows = conn.execute(
                """
                SELECT * FROM field_lineage
                WHERE parent_field_id=? OR child_field_id=?
                ORDER BY id
                """,
                (field["id"], field["id"]),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result


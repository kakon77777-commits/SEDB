"""SEDB store for the AI Frontier Repository Intelligence catalog.

Thin, typed access on top of SEDB v0.4B (`sedb.db.Database`, field/entity/view
services). Rules enforced here, not in callers:

* schema bootstrap is idempotent and conflict-detecting (existing fields or
  views whose definition differs from the contract block the write);
* immutable kinds are append-only: writing an existing entity with different
  source-owned values raises `ImmutableConflict`; identical writes are no-ops;
* current-state kinds may be updated in place, and every update is a cell
  upsert with provenance (`source`, `confidence`);
* bulk writes happen inside one SQLite transaction (grounding catalogs are
  tens of thousands of rows).

Workers never get this object. Only the orchestrator writes here, after
validation.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from config import (
    CELL_SOURCE_PREFIX,
    CURRENT_KINDS,
    FIELD_SPECS,
    IMMUTABLE_KINDS,
    KINDS,
    NAMESPACE,
    SCHEMA_VERSION,
    VIEW_SPECS,
    ProjectConfig,
)
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.naming import normalize_field_key
from sedb.views import ViewService


class SchemaConflictError(RuntimeError):
    reason_code = "schema_conflict"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []


class ImmutableConflict(RuntimeError):
    reason_code = "immutable_conflict"

    def __init__(self, entity_id: str, differences: list[dict]):
        super().__init__(f"immutable record {entity_id} already exists with different values")
        self.entity_id = entity_id
        self.differences = differences


class StorageError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SchemaResult:
    fields_created: int
    fields_reused: int
    views_created: int
    views_reused: int
    integrity: str


@dataclass(frozen=True)
class WriteResult:
    created_entities: int
    unchanged_entities: int
    updated_entities: int
    written_cells: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


FIELD_BY_KEY = {spec.key: spec for spec in FIELD_SPECS}


class RepoIntelStore:
    def __init__(self, config: ProjectConfig, db: Database):
        self.config = config
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)
        self.views = ViewService(db)

    @classmethod
    def open(cls, config: ProjectConfig) -> "RepoIntelStore":
        return cls(config, Database(config.database_path))

    # ------------------------------------------------------------------ schema
    def integrity_check(self) -> str:
        result = str(self.db.scalar("PRAGMA integrity_check"))
        if result != "ok":
            raise StorageError("integrity_failure", f"SQLite integrity check failed: {result}")
        return result

    def ensure_schema(self) -> SchemaResult:
        if len({s.key for s in FIELD_SPECS}) != len(FIELD_SPECS):
            raise SchemaConflictError("duplicate field key in project contract")
        if len({s.name for s in VIEW_SPECS}) != len(VIEW_SPECS):
            raise SchemaConflictError("duplicate view name in project contract")
        existing_rows = self.fields.list_fields(limit=10000)
        by_key = {row["key"]: row for row in existing_rows}
        by_identity = {(row.get("namespace", "global"), row.get("normalized_key")): row for row in existing_rows}
        conflicts, missing = [], []
        for spec in FIELD_SPECS:
            row = by_key.get(spec.key)
            collision = by_identity.get((NAMESPACE, normalize_field_key(spec.key)))
            if row is None and collision is not None:
                conflicts.append({"field": spec.key, "reason": "normalized_key_collision", "actual_key": collision["key"]})
                continue
            if row is None:
                missing.append(spec)
                continue
            expected = spec.as_sedb_spec()
            actual = {k: row.get(k) for k in expected}
            if actual != expected:
                conflicts.append({"field": spec.key, "expected": expected, "actual": actual})
        if conflicts:
            raise SchemaConflictError("existing SEDB fields conflict with the repository-intelligence contract", conflicts)
        created = self.fields.bulk_create_fields([s.as_sedb_spec() for s in missing]) if missing else 0

        existing_views = {v["name"]: v for v in self.views.list_views()}
        views_created = views_reused = 0
        view_conflicts = []
        for spec in VIEW_SPECS:
            view = existing_views.get(spec.name)
            if view is None:
                self.views.create_view(spec.name, spec.field_keys, query_text=spec.description)
                views_created += 1
                continue
            actual_keys = [f["key"] for f in self.views.get_view(view["id"]).get("fields", [])]
            if actual_keys and actual_keys != list(spec.field_keys):
                view_conflicts.append({"view": spec.name, "expected": list(spec.field_keys), "actual": actual_keys})
            views_reused += 1
        if view_conflicts:
            raise SchemaConflictError("existing SEDB task views conflict with the contract", view_conflicts)
        return SchemaResult(created, len(FIELD_SPECS) - created, views_created, views_reused, self.integrity_check())

    # ------------------------------------------------------------------ writes
    def _field_ids(self, conn: sqlite3.Connection) -> dict[str, str]:
        rows = conn.execute("SELECT id, key FROM fields WHERE namespace=?", (NAMESPACE,)).fetchall()
        return {row["key"]: row["id"] for row in rows}

    def _read_values(self, conn: sqlite3.Connection, entity_id: str) -> dict[str, Any] | None:
        row = conn.execute("SELECT id, kind, label FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            return None
        cells = conn.execute(
            "SELECT f.key, c.value_json FROM cells c JOIN fields f ON f.id=c.field_id WHERE c.entity_id=? AND f.namespace=?",
            (entity_id, NAMESPACE),
        ).fetchall()
        return {"kind": row["kind"], "label": row["label"], "values": {c["key"]: json.loads(c["value_json"]) for c in cells}}

    def write(self, records: Iterable[Mapping[str, Any]], *, source: str, confidence: float | None = None) -> WriteResult:
        """Write records atomically.

        Each record: {"entity_id", "kind", "label", "values": {field_key: value}}.
        Immutable kinds: identical → no-op, different → ImmutableConflict (whole
        batch rolled back). Current kinds: upsert.
        """
        records = list(records)
        for rec in records:
            if rec["kind"] not in KINDS:
                raise StorageError("unknown_kind", f"unknown entity kind: {rec['kind']}")
            for key in rec["values"]:
                if key not in FIELD_BY_KEY:
                    raise StorageError("unknown_field", f"unknown field {key} on {rec['entity_id']}")
        created = unchanged = updated = cells = 0
        now = utc_now()
        cell_source = f"{CELL_SOURCE_PREFIX}:{source}"
        conn = self.db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            field_ids = self._field_ids(conn)
            missing = [k for rec in records for k in rec["values"] if k not in field_ids]
            if missing:
                raise StorageError("schema_missing", f"fields not bootstrapped: {sorted(set(missing))[:5]}")
            for rec in records:
                values = dict(rec["values"])
                values.setdefault("af_schema_version", SCHEMA_VERSION)
                existing = self._read_values(conn, rec["entity_id"])
                if existing is not None:
                    if existing["kind"] != rec["kind"]:
                        raise ImmutableConflict(rec["entity_id"], [{"field": "entity.kind", "expected": rec["kind"], "actual": existing["kind"]}])
                    diffs = [
                        {"field": k, "expected": v, "actual": existing["values"].get(k)}
                        for k, v in values.items()
                        if _canonical(existing["values"].get(k)) != _canonical(v)
                    ]
                    if not diffs and existing["label"] == rec["label"]:
                        unchanged += 1
                        continue
                    if rec["kind"] in IMMUTABLE_KINDS:
                        raise ImmutableConflict(rec["entity_id"], diffs)
                    updated += 1
                    conn.execute("UPDATE entities SET label=?, updated_at=? WHERE id=?", (rec["label"], now, rec["entity_id"]))
                    to_write = {d["field"]: values[d["field"]] for d in diffs}
                else:
                    conn.execute(
                        "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (rec["entity_id"], rec["kind"], rec["label"], now, now),
                    )
                    created += 1
                    to_write = values
                conn.executemany(
                    """
                    INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(entity_id,field_id) DO UPDATE SET
                        value_json=excluded.value_json, source=excluded.source,
                        confidence=excluded.confidence, updated_at=excluded.updated_at
                    """,
                    [
                        (rec["entity_id"], field_ids[k], _canonical(v), cell_source, confidence, now)
                        for k, v in to_write.items()
                    ],
                )
                cells += len(to_write)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return WriteResult(created, unchanged, updated, cells)

    # ------------------------------------------------------------------ reads
    def get(self, entity_id: str) -> dict[str, Any] | None:
        conn = self.db.connect()
        try:
            return self._read_values(conn, entity_id) and {"entity_id": entity_id, **self._read_values(conn, entity_id)}
        finally:
            conn.close()

    def find(self, kind: str, **equals: Any) -> list[dict[str, Any]]:
        """Return entities of `kind` whose cells equal the given values."""
        conn = self.db.connect()
        try:
            rows = conn.execute("SELECT id FROM entities WHERE kind=? ORDER BY created_at, id", (kind,)).fetchall()
            out = []
            for row in rows:
                rec = self._read_values(conn, row["id"])
                if all(_canonical(rec["values"].get(k)) == _canonical(v) for k, v in equals.items()):
                    out.append({"entity_id": row["id"], **rec})
            return out
        finally:
            conn.close()

    def count_by_kind(self) -> dict[str, int]:
        conn = self.db.connect()
        try:
            rows = conn.execute("SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind ORDER BY kind").fetchall()
            return {row["kind"]: row["n"] for row in rows}
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        conn = self.db.connect()
        try:
            cells = conn.execute(
                "SELECT COUNT(*) FROM cells c JOIN fields f ON f.id=c.field_id WHERE f.namespace=?", (NAMESPACE,)
            ).fetchone()[0]
            fields = conn.execute("SELECT COUNT(*) FROM fields WHERE namespace=?", (NAMESPACE,)).fetchone()[0]
        finally:
            conn.close()
        return {
            "schema_version": SCHEMA_VERSION,
            "namespace": NAMESPACE,
            "fields": fields,
            "views": len([v for v in self.views.list_views() if v["name"].startswith("AI Frontier")]),
            "entities_by_kind": self.count_by_kind(),
            "cells": cells,
            "integrity": self.integrity_check(),
        }

    def provenance_chain(self, asset_revision_id: str) -> dict[str, Any]:
        """Answer the FINAL_HANDOFF verification questions for one asset revision."""
        ar = self.get(asset_revision_id)
        if ar is None or ar["kind"] != "af_asset_revision":
            raise StorageError("not_found", f"asset revision not found: {asset_revision_id}")
        v = ar["values"]
        asset = self.get(v.get("af_asset_id"))
        repo = self.get(v.get("af_repository_id"))
        rev = self.get(v.get("af_repository_revision_id"))
        run = self.get(v.get("af_analysis_run_id"))
        lic = self.find("af_license_record", af_revision_id=v.get("af_repository_revision_id"))
        workers = [self.get(w) for w in v.get("af_worker_run_ids", [])]
        validations = self.find("af_validation_run", af_target_id=asset_revision_id)
        pubs = self.find("af_publication_event", af_asset_revision_id=asset_revision_id)
        def pick(rec, *keys):
            return None if rec is None else {k: rec["values"].get(k) for k in keys}
        return {
            "asset_revision_id": asset_revision_id,
            "1_which_repository": pick(repo, "af_full_name", "af_platform", "af_platform_repository_id", "af_canonical_source_url"),
            "2_which_commit": pick(rev, "af_commit_sha", "af_branch", "af_committed_at"),
            "3_which_license_state": [pick(l, "af_license_status", "af_detected_spdx", "af_license_file_sha256", "af_license_policy") for l in lic],
            "4_which_analysis": pick(run, "af_engine", "af_engine_version", "af_manifest_schema_version", "af_analysis_mode", "af_external_provider", "af_artifact_ref", "af_artifact_sha256"),
            "5_which_grounding_bundle": pick(run, "af_grounding_bundle_ref", "af_grounding_bundle_sha256"),
            "6_which_worker_runs": [{"worker_run_id": w["entity_id"], **pick(w, "af_worker_role", "af_model_name", "af_macr_candidate_id", "af_input_sha256", "af_output_sha256", "af_run_status", "af_cost_usd")} for w in workers if w],
            "7_which_validation_runs": [{"validation_run_id": x["entity_id"], **pick(x, "af_validator_type", "af_validator_version", "af_validation_status")} for x in validations],
            "8_canonical_markdown_hash": v.get("af_canonical_source_sha256"),
            "9_public_url": [p["values"].get("af_url") for p in pubs] or None,
            "9_publication_status": v.get("af_publication_status"),
            "10_rollback": (
                "unpublished: nothing to roll back" if not pubs else
                f"point {asset['values'].get('af_current_revision_id')} back to the previous validated asset revision and emit an 'unpublished' event"
            ),
        }

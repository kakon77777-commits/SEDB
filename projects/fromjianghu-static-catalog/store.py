from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from config import CELL_SOURCE, FIELD_SPECS, SOURCE_OWNED_KEYS, VIEW_SPECS, ProjectConfig
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.naming import normalize_field_key
from sedb.views import ViewService
from source import CatalogRecord, CatalogSnapshot


MISSING = object()


class SchemaConflictError(RuntimeError):
    reason_code = "schema_conflict"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []


class StorageError(RuntimeError):
    def __init__(self, reason_code: str, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class SchemaResult:
    fields_created: int
    fields_reused: int
    views_created: int
    integrity: str


@dataclass(frozen=True)
class FieldDifference:
    field: str
    expected: Any
    actual: Any
    reason: str = "value_mismatch"


@dataclass(frozen=True)
class RecordConflict:
    entity_id: str
    differences: tuple[FieldDifference, ...]


@dataclass(frozen=True)
class MissingSourceRecord:
    entity_id: str
    kind: str


@dataclass(frozen=True)
class DiffPlan:
    new: tuple[CatalogRecord, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[RecordConflict, ...]
    missing_from_source: tuple[MissingSourceRecord, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts or self.missing_from_source)


@dataclass(frozen=True)
class WriteResult:
    created_entities: int
    created_cells: int
    integrity: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CatalogStore:
    def __init__(self, config: ProjectConfig, db: Database):
        self.config = config
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)
        self.views = ViewService(db)

    @classmethod
    def open(cls, config: ProjectConfig) -> "CatalogStore":
        return cls(config, Database(config.database_path))

    def integrity_check(self) -> str:
        result = str(self.db.scalar("PRAGMA integrity_check"))
        if result != "ok":
            raise StorageError("integrity_failure", f"SQLite integrity check failed: {result}")
        return result

    def _schema_preflight(self) -> tuple[list, list]:
        if len({spec.key for spec in FIELD_SPECS}) != len(FIELD_SPECS):
            raise SchemaConflictError("duplicate field key in project contract")
        if len({spec.name for spec in VIEW_SPECS}) != len(VIEW_SPECS):
            raise SchemaConflictError("duplicate view name in project contract")

        existing_rows = self.fields.list_fields(limit=10000)
        existing = {row["key"]: row for row in existing_rows}
        normalized = {
            (row.get("namespace", "global"), row.get("normalized_key")): row
            for row in existing_rows
        }
        missing_fields = []
        conflicts = []
        for spec in FIELD_SPECS:
            row = existing.get(spec.key)
            collision = normalized.get((self.config.namespace, normalize_field_key(spec.key)))
            if row is None and collision is not None:
                conflicts.append({
                    "field": spec.key,
                    "reason": "normalized_key_collision",
                    "actual_key": collision["key"],
                })
                continue
            if row is None:
                missing_fields.append(spec)
                continue
            expected = spec.as_sedb_spec()
            actual = {key: row.get(key) for key in expected}
            if actual != expected:
                conflicts.append({"field": spec.key, "expected": expected, "actual": actual})

        views_by_name: dict[str, list[dict]] = {}
        for row in self.views.list_views():
            views_by_name.setdefault(row["name"], []).append(row)
        missing_views = []
        for spec in VIEW_SPECS:
            matches = views_by_name.get(spec.name, [])
            if len(matches) > 1:
                conflicts.append({"view": spec.name, "reason": "duplicate_view_name"})
            elif not matches:
                missing_views.append(spec)
            else:
                view = self.views.get_view(matches[0]["id"])
                actual_keys = [field["key"] for field in view["fields"]]
                if actual_keys != list(spec.field_keys):
                    conflicts.append({
                        "view": spec.name,
                        "expected": list(spec.field_keys),
                        "actual": actual_keys,
                    })
        if conflicts:
            raise SchemaConflictError("SEDB schema conflicts with FromJianghu contract", conflicts)
        return missing_fields, missing_views

    def ensure_schema(self) -> SchemaResult:
        missing_fields, missing_views = self._schema_preflight()
        if missing_fields:
            self.fields.bulk_create_fields([spec.as_sedb_spec() for spec in missing_fields])
        # ViewService lists newest first. Reversed lexical creation produces a stable lexical readback.
        for spec in sorted(missing_views, key=lambda item: item.name, reverse=True):
            self.views.create_view(spec.name, spec.field_keys, query_text=spec.description)
        return SchemaResult(
            fields_created=len(missing_fields),
            fields_reused=len(FIELD_SPECS) - len(missing_fields),
            views_created=len(missing_views),
            integrity=self.integrity_check(),
        )

    def _owned_state(self) -> dict[str, dict[str, Any]]:
        with self.db.connect() as conn:
            return self._state_from_connection(conn, self.config)

    @staticmethod
    def _state_from_connection(conn, config: ProjectConfig) -> dict[str, dict[str, Any]]:
        kinds = tuple(sorted(config.expected_entity_counts))
        if not kinds:
            return {}
        marks = ",".join("?" for _ in kinds)
        entities = {
            row["id"]: {"kind": row["kind"], "label": row["label"], "values": {}}
            for row in conn.execute(
                f"SELECT id,kind,label FROM entities WHERE kind IN ({marks})",
                kinds,
            ).fetchall()
        }
        if not entities:
            return entities
        field_keys = tuple(sorted(SOURCE_OWNED_KEYS))
        field_marks = ",".join("?" for _ in field_keys)
        for row in conn.execute(
            f"""
            SELECT c.entity_id,f.key,c.value_json
            FROM cells c
            JOIN fields f ON f.id=c.field_id
            WHERE f.namespace=? AND f.key IN ({field_marks})
            """,
            (config.namespace, *field_keys),
        ).fetchall():
            if row["entity_id"] in entities:
                entities[row["entity_id"]]["values"][row["key"]] = json.loads(row["value_json"])
        return entities

    @classmethod
    def read_only_plan(cls, config: ProjectConfig, snapshot: CatalogSnapshot) -> DiffPlan:
        db_path = Path(config.database_path)
        if not db_path.exists():
            return DiffPlan(snapshot.records, (), (), ())
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                required = {"entities", "fields", "cells"}
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not required.issubset(tables):
                    raise SchemaConflictError("existing database is not an initialized SEDB database")
                cls._validate_schema_connection(conn, config)
                state = cls._state_from_connection(conn, config)
            finally:
                conn.close()
        except SchemaConflictError:
            raise
        except sqlite3.Error as exc:
            raise StorageError("read_only_plan_failure", str(exc)) from exc
        return cls._plan_against_state(snapshot, state)

    @staticmethod
    def _validate_schema_connection(conn, config: ProjectConfig) -> None:
        rows = conn.execute(
            "SELECT key,label,value_type,description,status,namespace,normalized_key FROM fields"
        ).fetchall()
        by_key = {row["key"]: row for row in rows}
        by_identity = {
            (row["namespace"], row["normalized_key"]): row
            for row in rows
        }
        conflicts = []
        for spec in FIELD_SPECS:
            row = by_key.get(spec.key)
            collision = by_identity.get((config.namespace, normalize_field_key(spec.key)))
            if row is None and collision is not None:
                conflicts.append({
                    "field": spec.key,
                    "reason": "normalized_key_collision",
                    "actual_key": collision["key"],
                })
                continue
            if row is None:
                continue
            expected = {
                "key": spec.key,
                "label": spec.label,
                "value_type": spec.value_type,
                "description": spec.description,
                "status": "active",
                "namespace": config.namespace,
                "normalized_key": normalize_field_key(spec.key),
            }
            actual = {key: row[key] for key in expected}
            if actual != expected:
                conflicts.append({"field": spec.key, "expected": expected, "actual": actual})

        view_rows = conn.execute("SELECT id,name FROM task_views").fetchall()
        views_by_name: dict[str, list] = {}
        for row in view_rows:
            views_by_name.setdefault(row["name"], []).append(row)
        for spec in VIEW_SPECS:
            matches = views_by_name.get(spec.name, [])
            if len(matches) > 1:
                conflicts.append({"view": spec.name, "reason": "duplicate_view_name"})
            elif matches:
                actual_keys = [
                    row["key"]
                    for row in conn.execute(
                        """
                        SELECT f.key
                        FROM task_view_fields tvf
                        JOIN fields f ON f.id=tvf.field_id
                        WHERE tvf.view_id=?
                        ORDER BY tvf.ordinal
                        """,
                        (matches[0]["id"],),
                    ).fetchall()
                ]
                if actual_keys != list(spec.field_keys):
                    conflicts.append({
                        "view": spec.name,
                        "expected": list(spec.field_keys),
                        "actual": actual_keys,
                    })
        if conflicts:
            raise SchemaConflictError(
                "existing SEDB schema conflicts with FromJianghu contract",
                conflicts,
            )

    def plan(self, snapshot: CatalogSnapshot) -> DiffPlan:
        return self._plan_against_state(snapshot, self._owned_state())

    @staticmethod
    def _plan_against_state(
        snapshot: CatalogSnapshot,
        state: Mapping[str, Mapping[str, Any]],
    ) -> DiffPlan:
        new = []
        unchanged = []
        conflicts = []
        source_ids = {record.entity_id for record in snapshot.records}
        for record in snapshot.records:
            actual = state.get(record.entity_id)
            if actual is None:
                new.append(record)
                continue
            differences = []
            if actual["kind"] != record.kind:
                differences.append(FieldDifference("entity.kind", record.kind, actual["kind"]))
            if actual["label"] != record.label:
                differences.append(FieldDifference("entity.label", record.label, actual["label"]))
            actual_values = actual["values"]
            for key in sorted(SOURCE_OWNED_KEYS):
                expected = record.values.get(key, MISSING)
                observed = actual_values.get(key, MISSING)
                if expected != observed:
                    differences.append(FieldDifference(
                        key,
                        None if expected is MISSING else expected,
                        None if observed is MISSING else observed,
                    ))
            if differences:
                conflicts.append(RecordConflict(record.entity_id, tuple(differences)))
            else:
                unchanged.append(record.entity_id)
        missing = [
            MissingSourceRecord(entity_id, str(actual["kind"]))
            for entity_id, actual in state.items()
            if entity_id not in source_ids
        ]
        return DiffPlan(
            new=tuple(sorted(new, key=lambda item: item.entity_id)),
            unchanged=tuple(sorted(unchanged)),
            conflicts=tuple(sorted(conflicts, key=lambda item: item.entity_id)),
            missing_from_source=tuple(sorted(missing, key=lambda item: item.entity_id)),
        )

    def _insert_cells(self, conn, rows: list[tuple]) -> None:
        conn.executemany(
            """
            INSERT INTO cells(entity_id,field_id,value_json,source,confidence,updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            rows,
        )

    def apply(self, plan: DiffPlan) -> WriteResult:
        if plan.blocked:
            raise StorageError("blocked_plan", "blocked difference plan cannot be applied")
        if not plan.new:
            return WriteResult(0, 0, self.integrity_check())
        now = _now()
        try:
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                field_rows = conn.execute(
                    "SELECT id,key FROM fields WHERE namespace=?",
                    (self.config.namespace,),
                ).fetchall()
                field_ids = {row["key"]: row["id"] for row in field_rows}
                missing_fields = SOURCE_OWNED_KEYS - field_ids.keys()
                if missing_fields:
                    raise StorageError(
                        "storage_failure",
                        f"owned fields missing after schema preflight: {sorted(missing_fields)}",
                    )
                conn.executemany(
                    "INSERT INTO entities(id,kind,label,created_at,updated_at) VALUES(?,?,?,?,?)",
                    [(record.entity_id, record.kind, record.label, now, now) for record in plan.new],
                )
                cell_rows = [
                    (
                        record.entity_id,
                        field_ids[key],
                        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        CELL_SOURCE,
                        None,
                        now,
                    )
                    for record in plan.new
                    for key, value in record.values.items()
                ]
                self._insert_cells(conn, cell_rows)
                state = self._state_from_connection(conn, self.config)
                for record in plan.new:
                    actual = state.get(record.entity_id)
                    if actual is None or actual["kind"] != record.kind or actual["label"] != record.label:
                        raise StorageError("readback_failure", f"entity readback mismatch: {record.entity_id}")
                    if actual["values"] != record.values:
                        raise StorageError("readback_failure", f"cell readback mismatch: {record.entity_id}")
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise StorageError("integrity_failure", f"SQLite integrity check failed: {integrity}")
            return WriteResult(len(plan.new), len(cell_rows), "ok")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("storage_failure", str(exc)) from exc

    def stats(self) -> dict[str, Any]:
        base = self.views.stats()
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT kind,COUNT(*) AS count FROM entities GROUP BY kind ORDER BY kind"
            ).fetchall()
        return {
            **base,
            "entities_by_kind": {row["kind"]: row["count"] for row in rows},
            "integrity": self.integrity_check(),
        }

    def classify(self) -> dict[str, Any]:
        return {
            "by_kind": self.stats()["entities_by_kind"],
            "function_catalogs": self._group_values("fj_function_snapshot", "fj_function_catalog"),
            "trigger_catalogs": self._group_values("fj_trigger_snapshot", "fj_trigger_catalog"),
            "asset_extensions": self._group_values("fj_asset_snapshot", "fj_asset_extension"),
            "claim_statuses": self._group_values("fj_evidence_claim", "fj_claim_status"),
            "runtime_statuses": self._group_values(None, "fj_runtime_status"),
        }

    def _group_values(self, kind: str | None, field_key: str) -> dict[str, int]:
        params: list[Any] = [self.config.namespace, field_key]
        kind_clause = ""
        if kind is not None:
            kind_clause = "AND e.kind=?"
            params.append(kind)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.value_json
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                JOIN entities e ON e.id=c.entity_id
                WHERE f.namespace=? AND f.key=? {kind_clause}
                """,
                params,
            ).fetchall()
        result: dict[str, int] = {}
        for row in rows:
            value = json.loads(row["value_json"])
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items(), key=lambda item: (item[0].casefold(), item[0])))

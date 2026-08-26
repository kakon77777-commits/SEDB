from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config import CELL_SOURCE, FIELD_SPECS, ProjectConfig
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService
from source import PaperRecord, RegistrySelection


MISSING = {"state": "missing"}


class SchemaConflictError(RuntimeError):
    reason_code = "schema_conflict"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []


class StorageError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class InitResult:
    fields_created: int
    fields_reused: int
    view_created: bool
    integrity: str


@dataclass(frozen=True)
class FieldDifference:
    field: str
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class RecordConflict:
    paper_id: str
    reason_code: str
    differences: tuple[FieldDifference, ...]


@dataclass(frozen=True)
class MissingSourceRecord:
    paper_id: str
    actual_month: str


@dataclass(frozen=True)
class DiffPlan:
    month: str
    new: tuple[PaperRecord, ...]
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


class CorpusStore:
    def __init__(self, config: ProjectConfig, db: Database):
        self.config = config
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)
        self.views = ViewService(db)

    @classmethod
    def open(cls, config: ProjectConfig) -> "CorpusStore":
        return cls(config, Database(config.database_path))

    def integrity_check(self) -> str:
        result = str(self.db.scalar("PRAGMA integrity_check"))
        if result != "ok":
            raise StorageError(
                "integrity_failure",
                f"SQLite integrity check failed: {result}",
            )
        return result

    def _schema_preflight(self) -> tuple[list, bool]:
        rows = self.fields.list_fields(limit=10000)
        existing = {row["key"]: row for row in rows}
        normalized = {
            (row.get("namespace", "global"), row.get("normalized_key")): row
            for row in rows
        }
        missing = []
        conflicts = []

        for spec in FIELD_SPECS:
            row = existing.get(spec.key)
            identity_row = normalized.get((self.config.namespace, spec.key))
            if row is None and identity_row is not None:
                conflicts.append(
                    {
                        "field": spec.key,
                        "reason": "normalized_key_collision",
                        "expected_key": spec.key,
                        "actual_key": identity_row["key"],
                    }
                )
                continue
            if row is None:
                missing.append(spec)
                continue

            expected = {
                "namespace": self.config.namespace,
                "normalized_key": spec.key,
                "label": spec.label,
                "value_type": spec.value_type,
                "description": spec.description,
                "status": "active",
            }
            actual = {key: row.get(key) for key in expected}
            if actual != expected:
                conflicts.append(
                    {
                        "field": spec.key,
                        "expected": expected,
                        "actual": actual,
                    }
                )

        matching_views = [
            view
            for view in self.views.list_views()
            if view["name"] == self.config.task_view_name
        ]
        if len(matching_views) > 1:
            conflicts.append(
                {
                    "view": self.config.task_view_name,
                    "reason": "duplicate_view_name",
                }
            )
        elif matching_views:
            view = self.views.get_view(matching_views[0]["id"])
            actual_keys = [field["key"] for field in view["fields"]]
            expected_keys = [spec.key for spec in FIELD_SPECS]
            if actual_keys != expected_keys:
                conflicts.append(
                    {
                        "view": self.config.task_view_name,
                        "expected": expected_keys,
                        "actual": actual_keys,
                    }
                )

        if conflicts:
            raise SchemaConflictError(
                "SEDB schema conflicts with the MVP contract",
                conflicts,
            )
        return missing, not matching_views

    def ensure_schema(self) -> InitResult:
        missing, view_missing = self._schema_preflight()
        if missing:
            self.fields.bulk_create_fields(
                [
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "value_type": spec.value_type,
                        "description": spec.description,
                        "status": "active",
                        "namespace": self.config.namespace,
                    }
                    for spec in missing
                ]
            )
        if view_missing:
            self.views.create_view(
                self.config.task_view_name,
                [spec.key for spec in FIELD_SPECS],
            )
        return InitResult(
            fields_created=len(missing),
            fields_reused=len(FIELD_SPECS) - len(missing),
            view_created=view_missing,
            integrity=self.integrity_check(),
        )

    def stats(self) -> dict[str, Any]:
        base = self.views.stats()
        with self.db.connect() as conn:
            paper_entities = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE kind=?",
                (self.config.entity_kind,),
            ).fetchone()[0]
            month_rows = conn.execute(
                """
                SELECT json_extract(c.value_json, '$') AS month, COUNT(*) AS count
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                JOIN entities e ON e.id=c.entity_id
                WHERE e.kind=? AND f.key='month' AND f.namespace=?
                GROUP BY month
                ORDER BY month
                """,
                (self.config.entity_kind, self.config.namespace),
            ).fetchall()
        return {
            **base,
            "paper_entities": paper_entities,
            "by_month": {row["month"]: row["count"] for row in month_rows},
            "integrity": self.integrity_check(),
        }

    def _owned_state(self) -> dict[str, dict[str, Any]]:
        owned = tuple(spec.key for spec in FIELD_SPECS)
        placeholders = ",".join("?" for _ in owned)
        with self.db.connect() as conn:
            entities = {
                row["id"]: {
                    "kind": row["kind"],
                    "label": row["label"],
                    "values": {},
                }
                for row in conn.execute(
                    "SELECT id,kind,label FROM entities"
                ).fetchall()
            }
            rows = conn.execute(
                f"""
                SELECT c.entity_id,f.key,c.value_json
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                WHERE f.namespace=? AND f.key IN ({placeholders})
                """,
                (self.config.namespace, *owned),
            ).fetchall()

        for row in rows:
            if row["entity_id"] in entities:
                entities[row["entity_id"]]["values"][row["key"]] = json.loads(
                    row["value_json"]
                )
        return entities

    def plan(self, selection: RegistrySelection) -> DiffPlan:
        state = self._owned_state()
        source_by_id = {paper.paper_id: paper for paper in selection.papers}
        new = []
        unchanged = []
        conflicts = []

        for paper in selection.papers:
            actual = state.get(paper.paper_id)
            if actual is None:
                new.append(paper)
                continue

            differences = []
            if actual["kind"] != self.config.entity_kind:
                differences.append(
                    FieldDifference(
                        "entity.kind",
                        self.config.entity_kind,
                        actual["kind"],
                        "value_mismatch",
                    )
                )
            if actual["label"] != paper.label:
                differences.append(
                    FieldDifference(
                        "entity.label",
                        paper.label,
                        actual["label"],
                        "value_mismatch",
                    )
                )

            actual_values = actual["values"]
            for spec in FIELD_SPECS:
                expected = paper.values.get(spec.key, MISSING)
                observed = actual_values.get(spec.key, MISSING)
                if expected != observed:
                    differences.append(
                        FieldDifference(
                            spec.key,
                            expected,
                            observed,
                            "value_mismatch",
                        )
                    )

            if differences:
                reason_code = (
                    "month_reassignment"
                    if any(diff.field == "month" for diff in differences)
                    else "source_conflict"
                )
                conflicts.append(
                    RecordConflict(
                        paper.paper_id,
                        reason_code,
                        tuple(sorted(differences, key=lambda diff: diff.field)),
                    )
                )
            else:
                unchanged.append(paper.paper_id)

        missing = []
        for paper_id, actual in state.items():
            if actual["kind"] != self.config.entity_kind:
                continue
            if (
                actual["values"].get("month") == selection.month
                and paper_id not in source_by_id
            ):
                missing.append(MissingSourceRecord(paper_id, selection.month))

        return DiffPlan(
            month=selection.month,
            new=tuple(sorted(new, key=lambda item: item.paper_id)),
            unchanged=tuple(sorted(unchanged)),
            conflicts=tuple(sorted(conflicts, key=lambda item: item.paper_id)),
            missing_from_source=tuple(
                sorted(missing, key=lambda item: item.paper_id)
            ),
        )

    def _insert_cells(self, conn, rows: list[tuple]) -> None:
        conn.executemany(
            """
            INSERT INTO cells(
                entity_id,
                field_id,
                value_json,
                source,
                confidence,
                updated_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            rows,
        )

    def apply(self, plan: DiffPlan) -> WriteResult:
        if plan.blocked:
            raise StorageError(
                "blocked_plan",
                "blocked difference plan cannot be applied",
            )
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
                expected_keys = {spec.key for spec in FIELD_SPECS}
                if expected_keys - field_ids.keys():
                    raise StorageError(
                        "storage_failure",
                        "owned field IDs changed after successful schema preflight",
                    )

                conn.executemany(
                    """
                    INSERT INTO entities(id,kind,label,created_at,updated_at)
                    VALUES(?,?,?,?,?)
                    """,
                    [
                        (
                            paper.paper_id,
                            self.config.entity_kind,
                            paper.label,
                            now,
                            now,
                        )
                        for paper in plan.new
                    ],
                )
                cell_rows = [
                    (
                        paper.paper_id,
                        field_ids[key],
                        json.dumps(
                            value,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        CELL_SOURCE,
                        None,
                        now,
                    )
                    for paper in plan.new
                    for key, value in paper.values.items()
                ]
                self._insert_cells(conn, cell_rows)

                ids = [paper.paper_id for paper in plan.new]
                id_marks = ",".join("?" for _ in ids)
                entity_count = conn.execute(
                    f"SELECT COUNT(*) FROM entities WHERE id IN ({id_marks})",
                    ids,
                ).fetchone()[0]
                cell_count = conn.execute(
                    f"SELECT COUNT(*) FROM cells WHERE entity_id IN ({id_marks})",
                    ids,
                ).fetchone()[0]
                if entity_count != len(plan.new) or cell_count != len(cell_rows):
                    raise StorageError(
                        "readback_failure",
                        "created entity/cell counts do not match plan",
                    )

                for paper in plan.new:
                    actual = {
                        row["key"]: json.loads(row["value_json"])
                        for row in conn.execute(
                            """
                            SELECT f.key,c.value_json
                            FROM cells c
                            JOIN fields f ON f.id=c.field_id
                            WHERE c.entity_id=? AND f.namespace=?
                            """,
                            (paper.paper_id, self.config.namespace),
                        ).fetchall()
                    }
                    if actual != paper.values:
                        raise StorageError(
                            "readback_failure",
                            f"paper readback mismatch: {paper.paper_id}",
                        )

                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise StorageError(
                        "integrity_failure",
                        f"SQLite integrity check failed: {integrity}",
                    )

            return WriteResult(len(plan.new), len(cell_rows), "ok")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("storage_failure", str(exc)) from exc

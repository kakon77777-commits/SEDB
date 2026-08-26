from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import FIELD_SPECS, ProjectConfig
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService


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

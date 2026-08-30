from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from config import ProjectConfig
from schema import FIELD_SPECS, SOURCE_OWNED_KEYS, VIEW_SPECS
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.naming import normalize_field_key
from sedb.views import ViewService
from source import SnapshotSelection, SourceEntity


MISSING = {"state": "missing"}
PROJECT_ENTITY_KINDS = frozenset(
    {
        "wanxiang_build_snapshot",
        "wanxiang_character_identity",
        "wanxiang_character_form_snapshot",
        "wanxiang_visual_asset_snapshot",
        "wanxiang_visual_candidate_snapshot",
        "wanxiang_source_gap_snapshot",
        "wanxiang_methodology_reference",
    }
)
BUILD_SCOPED_KINDS = PROJECT_ENTITY_KINDS - {
    "wanxiang_methodology_reference"
}


class SchemaConflictError(RuntimeError):
    reason_code = "schema_conflict"

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.details = details or []


class StorageError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class InitResult:
    fields_created: int
    fields_reused: int
    views_created: int
    views_reused: int
    integrity: str


@dataclass(frozen=True)
class FieldDifference:
    field: str
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class EntityConflict:
    entity_id: str
    differences: tuple[FieldDifference, ...]
    reason_code: str = "source_conflict"


@dataclass(frozen=True)
class PlannedCell:
    key: str
    value: Any
    source: str


@dataclass(frozen=True)
class EntityEnrichment:
    entity_id: str
    cells: tuple[PlannedCell, ...]


@dataclass(frozen=True)
class DiffPlan:
    build_id: int
    new: tuple[SourceEntity, ...]
    enrich: tuple[EntityEnrichment, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[EntityConflict, ...]
    missing_from_source: tuple[str, ...]
    source_fingerprint: str

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts or self.missing_from_source)


@dataclass(frozen=True)
class WriteResult:
    created_entities: int
    enriched_entities: int
    created_cells: int
    integrity: str
    source_fingerprint: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return len(value) == 0
    return False


def _owned_values(entity: SourceEntity) -> dict[str, Any]:
    unknown = set(entity.values) - SOURCE_OWNED_KEYS
    if unknown:
        raise StorageError(
            "invalid_source_entity",
            f"source entity {entity.entity_id} has non-source fields: {sorted(unknown)}",
        )
    return {
        key: value
        for key, value in entity.values.items()
        if key in SOURCE_OWNED_KEYS and not _is_blank(value)
    }


def _selection_owned_keys(selection: SnapshotSelection) -> frozenset[str]:
    if selection.owned_keys:
        return selection.owned_keys
    return frozenset(
        key for entity in selection.entities for key in entity.values
    )


def _selection_scope_kinds(selection: SnapshotSelection) -> frozenset[str]:
    return selection.scope_entity_kinds or frozenset(selection.counts)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(selection: SnapshotSelection) -> str:
    owned_keys = _selection_owned_keys(selection)
    seen: set[str] = set()
    records = []
    for entity in sorted(selection.entities, key=lambda item: item.entity_id):
        if entity.entity_id in seen:
            raise StorageError(
                "duplicate_source_entity",
                f"duplicate source entity {entity.entity_id}",
            )
        seen.add(entity.entity_id)
        records.append(
            {
                "entity_id": entity.entity_id,
                "kind": entity.kind,
                "label": entity.label,
                "cells": {
                    key: {
                        "value": value,
                        "source": entity.source_for(key),
                    }
                    for key, value in _owned_values(entity).items()
                    if key in owned_keys
                },
            }
        )
    projection = {
        "build_id": selection.build_id,
        "source_hashes": {
            key: selection.source_hashes[key]
            for key in sorted(selection.source_hashes)
        },
        "scope_name": selection.scope_name,
        "owned_keys": sorted(owned_keys),
        "scope_entity_kinds": sorted(_selection_scope_kinds(selection)),
        "entities": records,
    }
    return hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest().upper()


def _chunks(values: Sequence[str], size: int = 500) -> Iterator[Sequence[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class CanonStore:
    def __init__(self, config: ProjectConfig, db: Database):
        self.config = config
        self.db = db
        self.fields = FieldService(db)
        self.entities = EntityService(db)
        self.views = ViewService(db)

    @classmethod
    def open(cls, config: ProjectConfig) -> "CanonStore":
        return cls(config, Database(config.database_path))

    def integrity_check(self) -> str:
        result = str(self.db.scalar("PRAGMA integrity_check"))
        if result != "ok":
            raise StorageError(
                "integrity_failure",
                f"SQLite integrity check failed: {result}",
            )
        return result

    def _schema_preflight(self) -> tuple[list[Any], list[Any]]:
        rows = self.fields.list_fields(limit=10_000)
        by_key = {row["key"]: row for row in rows}
        by_normalized = {
            (row.get("namespace", "global"), row.get("normalized_key")): row
            for row in rows
        }
        missing_fields = []
        conflicts: list[dict[str, Any]] = []

        for spec in FIELD_SPECS:
            expected_normalized = normalize_field_key(spec.key)
            row = by_key.get(spec.key)
            normalized_row = by_normalized.get((spec.namespace, expected_normalized))
            if row is None and normalized_row is not None:
                conflicts.append(
                    {
                        "field": spec.key,
                        "reason": "normalized_key_collision",
                        "expected_key": spec.key,
                        "actual_key": normalized_row["key"],
                    }
                )
                continue
            if row is None:
                missing_fields.append(spec)
                continue
            expected = {
                "namespace": spec.namespace,
                "normalized_key": expected_normalized,
                "label": spec.label,
                "value_type": spec.value_type,
                "description": spec.description,
                "status": spec.status,
            }
            actual = {key: row.get(key) for key in expected}
            if actual != expected:
                conflicts.append(
                    {
                        "field": spec.key,
                        "reason": "field_contract_mismatch",
                        "expected": expected,
                        "actual": actual,
                    }
                )

        existing_views: dict[str, list[dict[str, Any]]] = {}
        for view in self.views.list_views():
            existing_views.setdefault(view["name"], []).append(view)
        missing_views = []
        for spec in VIEW_SPECS:
            matches = existing_views.get(spec.name, [])
            if len(matches) > 1:
                conflicts.append(
                    {"view": spec.name, "reason": "duplicate_view_name"}
                )
                continue
            if not matches:
                missing_views.append(spec)
                continue
            view = self.views.get_view(matches[0]["id"])
            actual_keys = tuple(field["key"] for field in view["fields"])
            if actual_keys != spec.field_keys:
                conflicts.append(
                    {
                        "view": spec.name,
                        "reason": "view_field_order_mismatch",
                        "expected": spec.field_keys,
                        "actual": actual_keys,
                    }
                )

        if conflicts:
            raise SchemaConflictError(
                "SEDB schema conflicts with the Wanxiang canon contract",
                conflicts,
            )
        return missing_fields, missing_views

    def ensure_schema(self) -> InitResult:
        missing_fields, missing_views = self._schema_preflight()
        if missing_fields:
            self.fields.bulk_create_fields(
                [spec.as_sedb_spec() for spec in missing_fields]
            )
        for spec in missing_views:
            self.views.create_view(
                spec.name,
                spec.field_keys,
                query_text=spec.description,
            )
        return InitResult(
            fields_created=len(missing_fields),
            fields_reused=len(FIELD_SPECS) - len(missing_fields),
            views_created=len(missing_views),
            views_reused=len(VIEW_SPECS) - len(missing_views),
            integrity=self.integrity_check(),
        )

    def _owned_state(self) -> dict[str, dict[str, Any]]:
        owned = sorted(SOURCE_OWNED_KEYS)
        placeholders = ",".join("?" for _ in owned)
        with self.db.connect() as conn:
            state = {
                row["id"]: {
                    "kind": row["kind"],
                    "label": row["label"],
                    "values": {},
                    "sources": {},
                }
                for row in conn.execute(
                    "SELECT id,kind,label FROM entities"
                ).fetchall()
            }
            rows = conn.execute(
                f"""
                SELECT c.entity_id,f.key,c.value_json,c.source
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                WHERE f.namespace=? AND f.key IN ({placeholders})
                """,
                (self.config.namespace, *owned),
            ).fetchall()
        for row in rows:
            if row["entity_id"] in state:
                state[row["entity_id"]]["values"][row["key"]] = json.loads(
                    row["value_json"]
                )
                state[row["entity_id"]]["sources"][row["key"]] = row["source"]
        return state

    def plan(self, selection: SnapshotSelection) -> DiffPlan:
        self._schema_preflight()
        if selection.build_id != self.config.build_id:
            raise StorageError(
                "build_id_mismatch",
                f"selection BuildID {selection.build_id} != configured {self.config.build_id}",
            )
        source_fingerprint = _fingerprint(selection)
        owned_keys = _selection_owned_keys(selection)
        scope_kinds = _selection_scope_kinds(selection)
        state = self._owned_state()
        source_by_id = {entity.entity_id: entity for entity in selection.entities}
        if len(source_by_id) != len(selection.entities):
            raise StorageError(
                "duplicate_source_entity",
                "selection contains duplicate entity IDs",
            )

        new: list[SourceEntity] = []
        enrich: list[EntityEnrichment] = []
        unchanged: list[str] = []
        conflicts: list[EntityConflict] = []
        for entity in sorted(selection.entities, key=lambda item: item.entity_id):
            actual = state.get(entity.entity_id)
            if actual is None:
                new.append(entity)
                continue
            differences: list[FieldDifference] = []
            if actual["kind"] != entity.kind:
                differences.append(
                    FieldDifference(
                        "entity.kind",
                        entity.kind,
                        actual["kind"],
                        "value_mismatch",
                    )
                )
            if actual["label"] != entity.label:
                differences.append(
                    FieldDifference(
                        "entity.label",
                        entity.label,
                        actual["label"],
                        "value_mismatch",
                    )
                )
            expected_values = _owned_values(entity)
            actual_values = actual["values"]
            additions: list[PlannedCell] = []
            for key in sorted(owned_keys):
                expected = expected_values.get(key, MISSING)
                observed = actual_values.get(key, MISSING)
                if expected != MISSING and observed == MISSING:
                    additions.append(
                        PlannedCell(key, expected, entity.source_for(key))
                    )
                    continue
                if expected != observed:
                    differences.append(
                        FieldDifference(
                            key,
                            expected,
                            observed,
                            "value_mismatch",
                        )
                    )
                    continue
                if expected != MISSING:
                    expected_source = entity.source_for(key)
                    actual_source = actual["sources"].get(key, MISSING)
                    if expected_source != actual_source:
                        differences.append(
                            FieldDifference(
                                f"{key}.source",
                                expected_source,
                                actual_source,
                                "source_mismatch",
                            )
                        )
            if differences:
                conflicts.append(
                    EntityConflict(
                        entity.entity_id,
                        tuple(differences),
                    )
                )
            elif additions:
                enrich.append(
                    EntityEnrichment(entity.entity_id, tuple(additions))
                )
            else:
                unchanged.append(entity.entity_id)

        missing: list[str] = []
        build_prefix = f"wx-build-{selection.build_id}"
        for entity_id, actual in state.items():
            if entity_id in source_by_id or actual["kind"] not in scope_kinds:
                continue
            is_methodology = actual["kind"] == "wanxiang_methodology_reference"
            source_build = actual["values"].get("source_build_id")
            id_scoped = entity_id == build_prefix or entity_id.startswith(
                f"{build_prefix}-"
            )
            if is_methodology or source_build == selection.build_id or id_scoped:
                missing.append(entity_id)

        return DiffPlan(
            build_id=selection.build_id,
            new=tuple(new),
            enrich=tuple(sorted(enrich, key=lambda item: item.entity_id)),
            unchanged=tuple(sorted(unchanged)),
            conflicts=tuple(sorted(conflicts, key=lambda item: item.entity_id)),
            missing_from_source=tuple(sorted(missing)),
            source_fingerprint=source_fingerprint,
        )

    def _verify_readback(
        self,
        conn,
        entities: Sequence[SourceEntity],
        enrichments: Sequence[EntityEnrichment],
        expected_cell_count: int,
    ) -> None:
        ids = list(
            dict.fromkeys(
                [entity.entity_id for entity in entities]
                + [item.entity_id for item in enrichments]
            )
        )
        expected = {
            entity.entity_id: {
                "kind": entity.kind,
                "label": entity.label,
                "cells": {
                    key: (value, entity.source_for(key))
                    for key, value in _owned_values(entity).items()
                },
            }
            for entity in entities
        }
        expected_enrichment = {
            item.entity_id: {
                cell.key: (cell.value, cell.source)
                for cell in item.cells
            }
            for item in enrichments
        }
        actual_entities: dict[str, dict[str, Any]] = {}
        actual_cells: dict[str, dict[str, tuple[Any, str]]] = {
            entity_id: {} for entity_id in ids
        }
        for chunk in _chunks(ids):
            marks = ",".join("?" for _ in chunk)
            for row in conn.execute(
                f"SELECT id,kind,label FROM entities WHERE id IN ({marks})",
                tuple(chunk),
            ).fetchall():
                actual_entities[row["id"]] = dict(row)
            for row in conn.execute(
                f"""
                SELECT c.entity_id,f.key,c.value_json,c.source
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                WHERE c.entity_id IN ({marks}) AND f.namespace=?
                """,
                (*chunk, self.config.namespace),
            ).fetchall():
                actual_cells[row["entity_id"]][row["key"]] = (
                    json.loads(row["value_json"]),
                    row["source"],
                )

        if set(actual_entities) != set(ids):
            raise StorageError(
                "readback_failure",
                "planned entity IDs do not match readback",
            )
        planned_cell_count = sum(
            len(record["cells"]) for record in expected.values()
        ) + sum(len(cells) for cells in expected_enrichment.values())
        if planned_cell_count != expected_cell_count:
            raise StorageError(
                "readback_failure",
                "planned cell count does not match insert rows",
            )
        for entity_id, record in expected.items():
            actual_entity = actual_entities[entity_id]
            if (
                actual_entity["kind"] != record["kind"]
                or actual_entity["label"] != record["label"]
            ):
                raise StorageError(
                    "readback_failure",
                    f"entity metadata mismatch: {entity_id}",
                )
            if actual_cells[entity_id] != record["cells"]:
                raise StorageError(
                    "readback_failure",
                    f"owned cell readback mismatch: {entity_id}",
                )
        for entity_id, cells in expected_enrichment.items():
            for key, expected_cell in cells.items():
                if actual_cells[entity_id].get(key) != expected_cell:
                    raise StorageError(
                        "readback_failure",
                        f"enrichment cell mismatch: {entity_id}/{key}",
                    )

    def apply(self, plan: DiffPlan) -> WriteResult:
        if plan.blocked:
            raise StorageError(
                "blocked_plan",
                "blocked difference plan cannot be applied",
            )
        missing_fields, missing_views = self._schema_preflight()
        if missing_fields or missing_views:
            raise StorageError(
                "schema_not_initialized",
                "project fields and views must be initialized before apply",
            )
        if not plan.new and not plan.enrich:
            return WriteResult(
                0,
                0,
                0,
                self.integrity_check(),
                plan.source_fingerprint,
            )

        now = _now()
        try:
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                field_rows = conn.execute(
                    "SELECT id,key FROM fields WHERE namespace=?",
                    (self.config.namespace,),
                ).fetchall()
                field_ids = {row["key"]: row["id"] for row in field_rows}
                missing = SOURCE_OWNED_KEYS - field_ids.keys()
                if missing:
                    raise StorageError(
                        "schema_not_initialized",
                        f"source-owned fields missing at apply: {sorted(missing)}",
                    )

                for enrichment in plan.enrich:
                    if conn.execute(
                        "SELECT 1 FROM entities WHERE id=?",
                        (enrichment.entity_id,),
                    ).fetchone() is None:
                        raise StorageError(
                            "stale_enrichment",
                            f"entity disappeared: {enrichment.entity_id}",
                        )
                    for cell in enrichment.cells:
                        if conn.execute(
                            "SELECT 1 FROM cells WHERE entity_id=? AND field_id=?",
                            (enrichment.entity_id, field_ids[cell.key]),
                        ).fetchone() is not None:
                            raise StorageError(
                                "stale_enrichment",
                                f"cell is no longer missing: {enrichment.entity_id}/{cell.key}",
                            )

                conn.executemany(
                    """
                    INSERT INTO entities(id,kind,label,created_at,updated_at)
                    VALUES(?,?,?,?,?)
                    """,
                    [
                        (
                            entity.entity_id,
                            entity.kind,
                            entity.label,
                            now,
                            now,
                        )
                        for entity in plan.new
                    ],
                )
                new_cell_rows = [
                    (
                        entity.entity_id,
                        field_ids[key],
                        _canonical_json(value),
                        entity.source_for(key),
                        None,
                        now,
                    )
                    for entity in plan.new
                    for key, value in _owned_values(entity).items()
                ]
                enrichment_cell_rows = [
                    (
                        enrichment.entity_id,
                        field_ids[cell.key],
                        _canonical_json(cell.value),
                        cell.source,
                        None,
                        now,
                    )
                    for enrichment in plan.enrich
                    for cell in enrichment.cells
                ]
                cell_rows = new_cell_rows + enrichment_cell_rows
                conn.executemany(
                    """
                    INSERT INTO cells(
                        entity_id,field_id,value_json,source,confidence,updated_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    cell_rows,
                )
                self._verify_readback(
                    conn,
                    plan.new,
                    plan.enrich,
                    len(cell_rows),
                )
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise StorageError(
                        "integrity_failure",
                        f"SQLite integrity check failed: {integrity}",
                    )
            return WriteResult(
                len(plan.new),
                len(plan.enrich),
                len(cell_rows),
                "ok",
                plan.source_fingerprint,
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("storage_failure", str(exc)) from exc

    def stats(self) -> dict[str, Any]:
        base = self.views.stats()
        kind_marks = ",".join("?" for _ in PROJECT_ENTITY_KINDS)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT kind,COUNT(*) AS count
                FROM entities
                WHERE kind IN ({kind_marks})
                GROUP BY kind
                ORDER BY kind
                """,
                tuple(sorted(PROJECT_ENTITY_KINDS)),
            ).fetchall()
            project_cells = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                JOIN entities e ON e.id=c.entity_id
                WHERE f.namespace=? AND e.kind IN ({kind_marks})
                """,
                (self.config.namespace, *sorted(PROJECT_ENTITY_KINDS)),
            ).fetchone()[0]
        observed = {row["kind"]: row["count"] for row in rows}
        by_kind = {
            kind: observed.get(kind, 0)
            for kind in self.config.expected_entity_counts
        }
        return {
            "namespace": self.config.namespace,
            "database_path": str(self.config.database_path),
            "database_entities": base["entities"],
            "database_cells": base["cells"],
            "project_entities": sum(by_kind.values()),
            "project_cells": project_cells,
            "by_kind": by_kind,
            "fields": base["fields"],
            "views": base["views"],
            "density": base["density"],
            "integrity": self.integrity_check(),
        }

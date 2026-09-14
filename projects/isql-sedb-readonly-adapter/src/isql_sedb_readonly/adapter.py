from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Mapping
from urllib.parse import quote

from isql_core.semantic_addressing import (
    ExactStateRef,
    SemanticAddress,
    SemanticAddressIndex,
    SemanticCandidate,
    SemanticResolveResult,
    build_semantic_address_index,
    resolve_semantic_candidates,
    verify_exact_state,
)
from isql_core.semantics import SemanticAnalysis


SEDB_ENTITY_SNAPSHOT_SCHEMA = "sedb.entity-snapshot/isql-readonly-v0.1"


class SEDBReadOnlyAdapterError(RuntimeError):
    pass


class SEDBExactStateMismatch(SEDBReadOnlyAdapterError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SEDBReadOnlyAdapterError("SEDB_SNAPSHOT_NOT_CANONICAL_JSON") from exc


def _require_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SEDBReadOnlyAdapterError(code)
    return value


def _json_value(raw: str) -> object:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SEDBReadOnlyAdapterError("SEDB_CELL_VALUE_JSON_INVALID") from exc
    _canonical_json_bytes(value)
    return value


def _confidence(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise SEDBReadOnlyAdapterError("SEDB_CELL_CONFIDENCE_NONFINITE")
    return number


@dataclass(frozen=True, slots=True)
class SEDBFieldBindingSnapshot:
    field_id: str
    key: str
    namespace: str
    normalized_key: str | None
    label: str
    value_type: str
    description: str
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "field_id": self.field_id,
            "key": self.key,
            "namespace": self.namespace,
            "normalized_key": self.normalized_key,
            "label": self.label,
            "value_type": self.value_type,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class SEDBCellSnapshot:
    field: SEDBFieldBindingSnapshot
    value: object
    source: str
    confidence: float | None
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field.to_dict(),
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class SEDBEntitySnapshot:
    entity_id: str
    kind: str
    label: str
    created_at: str
    updated_at: str
    cells: tuple[SEDBCellSnapshot, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SEDB_ENTITY_SNAPSHOT_SCHEMA,
            "entity": {
                "id": self.entity_id,
                "kind": self.kind,
                "label": self.label,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
            "cells": [cell.to_dict() for cell in self.cells],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedSEDBRead:
    candidate: SemanticCandidate
    snapshot: SEDBEntitySnapshot

    def __post_init__(self) -> None:
        if self.candidate.exact.entity_id != self.snapshot.entity_id:
            raise SEDBReadOnlyAdapterError("SEDB_ENTITY_ID_BINDING_MISMATCH")
        if self.candidate.exact.state_sha256 != self.snapshot.sha256():
            raise SEDBReadOnlyAdapterError("SEDB_STATE_HASH_BINDING_MISMATCH")


class SEDBReadOnlyAdapter:
    """Read-only current-head adapter for the SEDB v0.4B SQLite schema.

    This adapter never calls SEDB mutation services and opens SQLite with
    `mode=ro` plus `PRAGMA query_only=ON`.  It resolves only the current
    materialized entity snapshot. Historical state resolution is out of scope.
    """

    def __init__(self, database_path: str | Path):
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise SEDBReadOnlyAdapterError("SEDB_DATABASE_FILE_REQUIRED")
        self.database_path = path

    def _connect(self) -> sqlite3.Connection:
        encoded = quote(self.database_path.as_posix(), safe="/:")
        conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('entities','fields','cells')"
        ).fetchall()
        names = {str(row["name"]) for row in rows}
        if names != {"entities", "fields", "cells"}:
            raise SEDBReadOnlyAdapterError("SEDB_REQUIRED_SCHEMA_MISSING")

    def list_entity_ids(self, *, limit: int = 1000, offset: int = 0) -> tuple[str, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise SEDBReadOnlyAdapterError("SEDB_ENTITY_LIMIT_INVALID")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise SEDBReadOnlyAdapterError("SEDB_ENTITY_OFFSET_INVALID")
        with self._connect() as conn:
            self._require_schema(conn)
            rows = conn.execute(
                "SELECT id FROM entities ORDER BY id LIMIT ? OFFSET ?",
                (min(limit, 10000), offset),
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def read_entity_snapshot(self, entity_id: str) -> SEDBEntitySnapshot:
        entity_id = _require_text(entity_id, "SEDB_ENTITY_ID_INVALID")
        with self._connect() as conn:
            self._require_schema(conn)
            entity = conn.execute(
                "SELECT id,kind,label,created_at,updated_at FROM entities WHERE id=?",
                (entity_id,),
            ).fetchone()
            if entity is None:
                raise KeyError(f"SEDB entity not found: {entity_id}")
            rows = conn.execute(
                """
                SELECT
                    f.id AS field_id,
                    f.key AS field_key,
                    f.namespace AS field_namespace,
                    f.normalized_key AS field_normalized_key,
                    f.label AS field_label,
                    f.value_type AS field_value_type,
                    f.description AS field_description,
                    f.status AS field_status,
                    f.created_at AS field_created_at,
                    f.updated_at AS field_updated_at,
                    c.value_json AS cell_value_json,
                    c.source AS cell_source,
                    c.confidence AS cell_confidence,
                    c.updated_at AS cell_updated_at
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                WHERE c.entity_id=?
                ORDER BY f.id
                """,
                (entity_id,),
            ).fetchall()

        cells: list[SEDBCellSnapshot] = []
        for row in rows:
            field = SEDBFieldBindingSnapshot(
                field_id=_require_text(row["field_id"], "SEDB_FIELD_ID_INVALID"),
                key=_require_text(row["field_key"], "SEDB_FIELD_KEY_INVALID"),
                namespace=_require_text(row["field_namespace"], "SEDB_FIELD_NAMESPACE_INVALID"),
                normalized_key=(
                    None if row["field_normalized_key"] is None else str(row["field_normalized_key"])
                ),
                label=_require_text(row["field_label"], "SEDB_FIELD_LABEL_INVALID"),
                value_type=_require_text(row["field_value_type"], "SEDB_FIELD_VALUE_TYPE_INVALID"),
                description=str(row["field_description"] or ""),
                status=_require_text(row["field_status"], "SEDB_FIELD_STATUS_INVALID"),
                created_at=_require_text(row["field_created_at"], "SEDB_FIELD_CREATED_AT_INVALID"),
                updated_at=_require_text(row["field_updated_at"], "SEDB_FIELD_UPDATED_AT_INVALID"),
            )
            cells.append(SEDBCellSnapshot(
                field=field,
                value=_json_value(row["cell_value_json"]),
                source=str(row["cell_source"] or ""),
                confidence=_confidence(row["cell_confidence"]),
                updated_at=_require_text(row["cell_updated_at"], "SEDB_CELL_UPDATED_AT_INVALID"),
            ))

        snapshot = SEDBEntitySnapshot(
            entity_id=_require_text(entity["id"], "SEDB_ENTITY_ID_INVALID"),
            kind=_require_text(entity["kind"], "SEDB_ENTITY_KIND_INVALID"),
            label=_require_text(entity["label"], "SEDB_ENTITY_LABEL_INVALID"),
            created_at=_require_text(entity["created_at"], "SEDB_ENTITY_CREATED_AT_INVALID"),
            updated_at=_require_text(entity["updated_at"], "SEDB_ENTITY_UPDATED_AT_INVALID"),
            cells=tuple(cells),
        )
        snapshot.canonical_bytes()
        return snapshot

    def index_records(
        self,
        analyses: Mapping[str, SemanticAnalysis],
    ) -> tuple[tuple[str, bytes, SemanticAnalysis], ...]:
        if not isinstance(analyses, Mapping):
            raise SEDBReadOnlyAdapterError("SEDB_ANALYSIS_MAPPING_REQUIRED")
        records: list[tuple[str, bytes, SemanticAnalysis]] = []
        for entity_id in sorted(analyses):
            analysis = analyses[entity_id]
            if not isinstance(analysis, SemanticAnalysis):
                raise SEDBReadOnlyAdapterError("SEDB_SEMANTIC_ANALYSIS_REQUIRED")
            snapshot = self.read_entity_snapshot(entity_id)
            records.append((entity_id, snapshot.canonical_bytes(), analysis))
        return tuple(records)

    def build_semantic_index(
        self,
        analyses: Mapping[str, SemanticAnalysis],
        *,
        profile_revision: int = 0,
    ) -> SemanticAddressIndex:
        return build_semantic_address_index(
            self.index_records(analyses),
            profile_revision=profile_revision,
        )

    def read_current_exact(self, exact: ExactStateRef) -> SEDBEntitySnapshot:
        if not isinstance(exact, ExactStateRef):
            raise SEDBReadOnlyAdapterError("SEDB_EXACT_STATE_REF_REQUIRED")
        snapshot = self.read_entity_snapshot(exact.entity_id)
        if not verify_exact_state(snapshot.canonical_bytes(), exact):
            raise SEDBExactStateMismatch(
                f"SEDB current state no longer matches exact ref for {exact.entity_id}"
            )
        return snapshot

    def resolve_and_read_verified(
        self,
        query: SemanticAddress,
        index: SemanticAddressIndex,
        *,
        top_k: int = 8,
    ) -> tuple[SemanticResolveResult, tuple[VerifiedSEDBRead, ...]]:
        result = resolve_semantic_candidates(query, index, top_k=top_k)
        verified: list[VerifiedSEDBRead] = []
        for candidate in result.candidates:
            snapshot = self.read_current_exact(candidate.exact)
            verified.append(VerifiedSEDBRead(candidate=candidate, snapshot=snapshot))
        return result, tuple(verified)

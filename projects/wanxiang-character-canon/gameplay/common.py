from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import quote

from config import ProjectConfig


ClaimClass = Literal["OBSERVED", "INFERRED", "UNKNOWN", "FALSIFYING_TEST"]
CLAIM_CLASSES = frozenset({"OBSERVED", "INFERRED", "UNKNOWN", "FALSIFYING_TEST"})

ANALYSIS_ENTITY_KINDS = frozenset(
    {
        "wanxiang_character_identity",
        "wanxiang_character_form_snapshot",
        "wanxiang_visual_asset_snapshot",
        "wanxiang_table_row_snapshot",
        "wanxiang_treasure_snapshot",
        "wanxiang_hero_sentinel_snapshot",
        "wanxiang_reference_edge_snapshot",
    }
)
SOURCE_ROW_KINDS = frozenset(
    {
        "wanxiang_character_form_snapshot",
        "wanxiang_table_row_snapshot",
        "wanxiang_treasure_snapshot",
        "wanxiang_hero_sentinel_snapshot",
    }
)
ANALYSIS_FIELD_KEYS = frozenset(
    {
        "source_build_id",
        "source_table",
        "source_record_id",
        "source_row_payload",
        "source_row_sha256",
        "hero_id",
        "identity_entity_id",
        "skill_ids",
        "property_ids",
        "resource_numeric_id",
        "extraction_status",
        "selection_options",
        "guide_steps",
        "edge_source_entity_id",
        "edge_source_table",
        "edge_source_field",
        "edge_target_entity_id",
        "edge_target_table",
        "edge_resolution_status",
        "edge_rule_version",
    }
)


class GameplayDataError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class Claim:
    claim_class: ClaimClass
    text: str
    evidence: tuple[str, ...]
    falsifying_test: str = ""

    def __post_init__(self) -> None:
        if self.claim_class not in CLAIM_CLASSES:
            raise ValueError(f"unsupported claim class: {self.claim_class}")
        if not self.text.strip():
            raise ValueError("claim text is required")
        if not self.evidence:
            raise ValueError("evidence is required")
        if self.claim_class == "OBSERVED":
            normalized = self.text.casefold().replace("_", "-")
            if "runtime-unreachable" in normalized:
                raise ValueError("runtime claim upgrade is forbidden")
            if "proves fun" in normalized:
                raise ValueError("gameplay acceptance upgrade is forbidden")


@dataclass(frozen=True)
class StaticRecord:
    record_id: str
    kind: str
    label: str
    values: dict[str, Any]


@dataclass(frozen=True)
class StaticDataset:
    build_id: int
    catalog_fingerprint: str
    rule_version: str
    records: tuple[StaticRecord, ...]
    catalog_source_fingerprint: str = ""
    database_sha256: str = ""
    database_path: str = ""
    source_table_counts: Mapping[str, int] = field(default_factory=dict)
    accepted_at: str = ""
    source_root: str = ""
    all_excel_root: str = ""

    def by_kind(self, kind: str) -> tuple[StaticRecord, ...]:
        return tuple(record for record in self.records if record.kind == kind)

    def table(self, table: str) -> tuple[StaticRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.values.get("source_table") == table
        )

    def record_index(self) -> dict[str, StaticRecord]:
        return {record.record_id: record for record in self.records}

    def source_id_index(self, table: str) -> dict[Any, StaticRecord]:
        return {
            record.values.get("source_record_id"): record
            for record in self.table(table)
        }

    def edges(self) -> tuple[StaticRecord, ...]:
        return self.by_kind("wanxiang_reference_edge_snapshot")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_acceptance(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GameplayDataError(
            "acceptance_evidence_unreadable",
            f"cannot read accepted catalog evidence: {path}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise GameplayDataError(
            "acceptance_evidence_invalid",
            "accepted catalog evidence must be a JSON object",
        )
    return payload


def _accepted_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GameplayDataError(
            "acceptance_evidence_invalid",
            f"accepted catalog evidence requires integer {key}",
        )
    return value


def _load_entity_values(
    connection: sqlite3.Connection,
    namespace: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    kind_marks = ",".join("?" for _ in ANALYSIS_ENTITY_KINDS)
    records = {
        row["id"]: {
            "id": row["id"],
            "kind": row["kind"],
            "label": row["label"],
            "values": {},
        }
        for row in connection.execute(
            f"""
            SELECT id,kind,label
            FROM entities
            WHERE kind IN ({kind_marks})
            ORDER BY id
            """,
            tuple(sorted(ANALYSIS_ENTITY_KINDS)),
        )
    }
    field_marks = ",".join("?" for _ in ANALYSIS_FIELD_KEYS)
    for row in connection.execute(
        f"""
        SELECT c.entity_id,f.key,c.value_json
        FROM cells c
        JOIN fields f ON f.id=c.field_id
        JOIN entities e ON e.id=c.entity_id
        WHERE f.namespace=?
          AND e.kind IN ({kind_marks})
          AND f.key IN ({field_marks})
        ORDER BY c.entity_id,f.key
        """,
        (
            namespace,
            *sorted(ANALYSIS_ENTITY_KINDS),
            *sorted(ANALYSIS_FIELD_KEYS),
        ),
    ):
        try:
            records[row["entity_id"]]["values"][row["key"]] = json.loads(
                row["value_json"]
            )
        except json.JSONDecodeError as exc:
            raise GameplayDataError(
                "database_cell_json_invalid",
                f"invalid JSON cell {row['entity_id']}:{row['key']}",
            ) from exc

    build_rows = connection.execute(
        """
        SELECT e.id,f.key,c.value_json
        FROM entities e
        JOIN cells c ON c.entity_id=e.id
        JOIN fields f ON f.id=c.field_id
        WHERE e.kind='wanxiang_build_snapshot'
          AND f.namespace=?
          AND f.key IN (
              'source_build_id',
              'catalog_source_fingerprint',
              'catalog_table_counts',
              'catalog_total_rows'
          )
        ORDER BY e.id,f.key
        """,
        (namespace,),
    ).fetchall()
    build_ids = {row["id"] for row in build_rows}
    if len(build_ids) != 1:
        raise GameplayDataError(
            "build_snapshot_count_mismatch",
            f"expected one build snapshot, found {len(build_ids)}",
        )
    build_values: dict[str, Any] = {}
    for row in build_rows:
        try:
            build_values[row["key"]] = json.loads(row["value_json"])
        except json.JSONDecodeError as exc:
            raise GameplayDataError(
                "database_cell_json_invalid",
                f"invalid JSON build cell {row['id']}:{row['key']}",
            ) from exc
    return records, build_values


def load_verified_dataset(
    config: ProjectConfig,
    *,
    acceptance_path: Path | None = None,
) -> StaticDataset:
    database = config.database_path.resolve()
    evidence_path = acceptance_path or (
        Path(__file__).resolve().parents[1]
        / "evidence"
        / "full-catalog-acceptance.json"
    )
    acceptance = _read_acceptance(evidence_path)
    if acceptance.get("status") != "FULL_STATIC_DATABASE_ACCEPTED":
        raise GameplayDataError(
            "catalog_not_accepted",
            "full static database acceptance status is required",
        )
    if _accepted_int(acceptance, "build_id") != config.build_id:
        raise GameplayDataError(
            "accepted_build_mismatch",
            "accepted BuildID does not match requested BuildID",
        )
    if not database.is_file():
        raise GameplayDataError(
            "database_missing",
            f"accepted catalog database does not exist: {database}",
        )

    accepted_database = acceptance.get("database")
    accepted_source = acceptance.get("source")
    if not isinstance(accepted_database, dict) or not isinstance(accepted_source, dict):
        raise GameplayDataError(
            "acceptance_evidence_invalid",
            "accepted catalog evidence requires database and source objects",
        )
    accepted_path = Path(str(accepted_database.get("path", ""))).resolve()
    if os.path.normcase(str(accepted_path)) != os.path.normcase(str(database)):
        raise GameplayDataError(
            "accepted_database_path_mismatch",
            "accepted database path does not match requested database",
        )
    database_sha256 = _sha256(database)
    if database_sha256 != str(accepted_database.get("sha256", "")).upper():
        raise GameplayDataError(
            "database_sha256_mismatch",
            "accepted database SHA-256 does not match the current database",
        )

    catalog_fingerprint = str(
        accepted_source.get("catalog_fingerprint", "")
    ).upper()
    if len(catalog_fingerprint) != 64:
        raise GameplayDataError(
            "acceptance_evidence_invalid",
            "accepted catalog fingerprint must be a 64-character SHA-256",
        )
    accepted_rule_version = str(
        accepted_source.get("reference_rule_version", "")
    )
    if not accepted_rule_version:
        raise GameplayDataError(
            "acceptance_evidence_invalid",
            "accepted reference rule version is required",
        )

    uri = f"file:{quote(database.as_posix(), safe='/:')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=30.0)
    except sqlite3.Error as exc:
        raise GameplayDataError(
            "database_open_failed",
            f"cannot open accepted database read-only: {exc}",
        ) from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise GameplayDataError(
                "database_integrity_failure",
                f"accepted database integrity check failed: {integrity}",
            )
        database_counts = {
            "entities": connection.execute(
                "SELECT COUNT(*) FROM entities"
            ).fetchone()[0],
            "cells": connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0],
            "fields": connection.execute("SELECT COUNT(*) FROM fields").fetchone()[0],
            "views": connection.execute(
                "SELECT COUNT(*) FROM task_views"
            ).fetchone()[0],
        }
        for key, actual in database_counts.items():
            if _accepted_int(accepted_database, key) != actual:
                raise GameplayDataError(
                    "accepted_database_count_mismatch",
                    f"accepted database {key} count does not match current database",
                )
        records, build_values = _load_entity_values(connection, config.namespace)
    except sqlite3.Error as exc:
        raise GameplayDataError(
            "database_schema_or_query_failure",
            f"accepted database query failed: {exc}",
        ) from exc
    finally:
        connection.close()

    if build_values.get("source_build_id") != config.build_id:
        raise GameplayDataError(
            "database_build_mismatch",
            "database build snapshot does not match requested BuildID",
        )
    catalog_source_fingerprint = str(
        build_values.get("catalog_source_fingerprint", "")
    ).upper()
    if len(catalog_source_fingerprint) != 64:
        raise GameplayDataError(
            "catalog_source_fingerprint_invalid",
            "database catalog source fingerprint must be a 64-character SHA-256",
        )

    source_rows = [
        record
        for record in records.values()
        if record["kind"] in SOURCE_ROW_KINDS
    ]
    if any(not record["values"].get("source_row_sha256") for record in source_rows):
        raise GameplayDataError(
            "source_row_evidence_missing",
            "every catalog source row requires a stored row SHA-256",
        )
    source_table_counts = dict(
        sorted(
            Counter(
                record["values"].get("source_table") for record in source_rows
            ).items()
        )
    )
    if None in source_table_counts:
        raise GameplayDataError(
            "source_table_missing",
            "every catalog source row requires a source table",
        )
    expected_table_counts = build_values.get("catalog_table_counts")
    if expected_table_counts != source_table_counts:
        raise GameplayDataError(
            "catalog_table_count_mismatch",
            "stored source table counts do not match the build catalog contract",
        )
    source_row_count = len(source_rows)
    if build_values.get("catalog_total_rows") != source_row_count:
        raise GameplayDataError(
            "catalog_total_rows_mismatch",
            "stored source rows do not match the build catalog total",
        )
    if _accepted_int(accepted_source, "source_rows") != source_row_count:
        raise GameplayDataError(
            "accepted_source_count_mismatch",
            "accepted source row count does not match the current database",
        )
    if _accepted_int(accepted_source, "tables") != len(source_table_counts):
        raise GameplayDataError(
            "accepted_table_count_mismatch",
            "accepted table count does not match the current database",
        )
    if _accepted_int(accepted_source, "event_dialog_rows") != source_table_counts.get(
        "EventDialog", 0
    ):
        raise GameplayDataError(
            "accepted_event_dialog_count_mismatch",
            "accepted EventDialog count does not match the current database",
        )

    edge_rule_versions = {
        record["values"].get("edge_rule_version")
        for record in records.values()
        if record["kind"] == "wanxiang_reference_edge_snapshot"
    }
    if edge_rule_versions != {accepted_rule_version}:
        raise GameplayDataError(
            "reference_rule_version_mismatch",
            "stored reference edges do not match the accepted rule version",
        )

    static_records = tuple(
        StaticRecord(
            record_id=record["id"],
            kind=record["kind"],
            label=record["label"],
            values=record["values"],
        )
        for record in records.values()
    )
    return StaticDataset(
        build_id=config.build_id,
        catalog_fingerprint=catalog_fingerprint,
        rule_version=accepted_rule_version,
        records=static_records,
        catalog_source_fingerprint=catalog_source_fingerprint,
        database_sha256=database_sha256,
        database_path=str(database),
        source_table_counts=source_table_counts,
        accepted_at=str(acceptance.get("generated_at", "NOT_RECORDED")),
        source_root=str(config.source_root.resolve()),
        all_excel_root=str(
            (
                config.source_root
                / "baseline"
                / "game"
                / "wanxiang"
                / "wanxiang"
                / "ModDocs"
                / "AllExcel"
            ).resolve()
        ),
    )


def standard_claims(
    *,
    observed: str,
    inferred: str,
    unknown: str,
    falsifying_test: str,
    evidence: tuple[str, ...],
) -> tuple[Claim, ...]:
    return (
        Claim("OBSERVED", observed, evidence),
        Claim("INFERRED", inferred, evidence),
        Claim("UNKNOWN", unknown, evidence),
        Claim("FALSIFYING_TEST", falsifying_test, evidence, falsifying_test),
    )

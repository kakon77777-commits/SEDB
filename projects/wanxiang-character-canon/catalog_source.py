from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from catalog_config import (
    READER_VERSION,
    SOURCE_AUTHORITY,
    SOURCE_LAYER,
    CatalogContract,
    CatalogContractError,
    default_catalog_contract,
)
from catalog_identity import canonical_source_id, table_row_entity_id
from excel_reader import WorkbookReadError, read_workbook
from identity import form_entity_id
from config import ProjectConfig
from source import SnapshotSelection, SourceEntity, load_snapshot


class CatalogSourceError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class RuntimeCandidate:
    path: str
    length: int
    sha256: str


@dataclass(frozen=True)
class CatalogRow:
    table: str
    source_id: Any
    row_number: int
    workbook_path: str
    workbook_sha256: str
    payload: dict[str, Any]
    payload_json: str
    source_row_sha256: str


@dataclass(frozen=True)
class CatalogRows:
    table_counts: dict[str, int]
    source_hashes: dict[str, str]
    rows: tuple[CatalogRow, ...]
    runtime_candidates: tuple[RuntimeCandidate, ...]
    source_fingerprint: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_manifest(contract: CatalogContract) -> tuple[dict[str, dict], str]:
    try:
        data = contract.manifest_path.read_bytes()
    except OSError as exc:
        raise CatalogSourceError("source_manifest_missing", str(exc)) from exc
    observed_hash = _sha256(data)
    if observed_hash != contract.manifest_sha256.upper():
        raise CatalogSourceError(
            "source_manifest_hash_mismatch",
            f"expected {contract.manifest_sha256}, got {observed_hash}",
        )
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogSourceError("source_manifest_invalid", str(exc)) from exc
    if payload.get("schema") != "wanxiang-source-inventory/v1":
        raise CatalogSourceError(
            "source_manifest_schema_unsupported", str(payload.get("schema"))
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise CatalogSourceError("source_manifest_invalid", "records must be a list")
    by_path: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(
            record.get("relativePath"), str
        ):
            raise CatalogSourceError("source_manifest_invalid", "invalid record")
        relative_path = record["relativePath"].replace("\\", "/")
        if relative_path in by_path:
            raise CatalogSourceError(
                "source_manifest_duplicate_member", relative_path
            )
        by_path[relative_path] = record
    return by_path, observed_hash


def _runtime_candidates(contract: CatalogContract) -> tuple[RuntimeCandidate, ...]:
    paths = tuple(sorted(contract.runtime_candidate_root.glob("*.dat")))
    if len(paths) != contract.runtime_candidate_count:
        raise CatalogSourceError(
            "runtime_candidate_count_mismatch",
            f"expected {contract.runtime_candidate_count}, got {len(paths)}",
        )
    return tuple(
        RuntimeCandidate(
            path=f"WXQXZ_Data/StreamingAssets/{path.name}",
            length=path.stat().st_size,
            sha256=_sha256(path.read_bytes()),
        )
        for path in paths
    )


def load_catalog_rows(contract: CatalogContract) -> CatalogRows:
    manifest_records, manifest_hash = _read_manifest(contract)
    rows: list[CatalogRow] = []
    observed_counts: dict[str, int] = {}
    source_hashes = {"manifest:current-verification.manifest.json": manifest_hash}

    for table in contract.table_counts:
        member = contract.manifest_member(table)
        record = manifest_records.get(member)
        if record is None:
            raise CatalogSourceError("manifest_member_missing", member)
        workbook_path = contract.workbook_path(table)
        try:
            data = workbook_path.read_bytes()
        except OSError as exc:
            raise CatalogSourceError("workbook_missing", str(exc)) from exc
        observed_hash = _sha256(data)
        if (
            record.get("length") != len(data)
            or str(record.get("sha256", "")).upper() != observed_hash
        ):
            raise CatalogSourceError(
                "workbook_hash_mismatch",
                f"{table}: expected length/hash {record.get('length')}/{record.get('sha256')}, got {len(data)}/{observed_hash}",
            )
        try:
            workbook = read_workbook(
                workbook_path,
                header_overrides=contract.header_overrides(table),
            )
        except WorkbookReadError as exc:
            raise CatalogSourceError(exc.reason_code, f"{table}: {exc}") from exc
        source_hashes[f"workbook:{table}"] = observed_hash
        observed_counts[table] = len(workbook.rows)
        seen_ids: set[str] = set()
        for row in workbook.rows:
            source_id = row.values.get("Id")
            if source_id is not None:
                try:
                    key = canonical_source_id(source_id)
                except ValueError as exc:
                    raise CatalogSourceError(
                        "source_id_type_unsupported",
                        f"{table} row {row.row_number}: {source_id!r}",
                    ) from exc
                if key in seen_ids:
                    raise CatalogSourceError(
                        "duplicate_table_source_id", f"{table}: {source_id!r}"
                    )
                seen_ids.add(key)
            rows.append(
                CatalogRow(
                    table=table,
                    source_id=source_id,
                    row_number=row.row_number,
                    workbook_path=member,
                    workbook_sha256=observed_hash,
                    payload=row.values,
                    payload_json=row.canonical_json,
                    source_row_sha256=row.sha256,
                )
            )
    try:
        contract.validate_table_counts(observed_counts)
    except CatalogContractError as exc:
        raise CatalogSourceError(exc.reason_code, str(exc)) from exc

    runtime_candidates = _runtime_candidates(contract)
    for candidate in runtime_candidates:
        source_hashes[f"runtime:{candidate.path}"] = candidate.sha256
    projection = {
        "table_counts": observed_counts,
        "source_hashes": source_hashes,
        "rows": [
            [row.table, row.row_number, row.source_row_sha256]
            for row in rows
        ],
        "runtime_candidates": [
            [candidate.path, candidate.length, candidate.sha256]
            for candidate in runtime_candidates
        ],
    }
    fingerprint = _sha256(_canonical_json(projection).encode("utf-8"))
    return CatalogRows(
        table_counts=observed_counts,
        source_hashes=source_hashes,
        rows=tuple(rows),
        runtime_candidates=runtime_candidates,
        source_fingerprint=fingerprint,
    )


def _row_source(row: CatalogRow) -> str:
    return f"wanxiang:{row.workbook_path}#row={row.row_number}"


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _base_row_values(build_id: int, row: CatalogRow) -> dict[str, Any]:
    payload = row.payload
    return _without_none(
        {
            "source_build_id": build_id,
            "source_layer": SOURCE_LAYER,
            "source_authority": SOURCE_AUTHORITY,
            "source_table": row.table,
            "source_record_id": row.source_id,
            "source_row": row.row_number,
            "source_workbook_path": row.workbook_path,
            "source_workbook_sha256": row.workbook_sha256,
            "source_row_sha256": row.source_row_sha256,
            "source_row_payload": payload,
            "record_status": "SOURCE_SNAPSHOT",
            "name_zh": payload.get("Name"),
            "name_tw": payload.get("NameTw"),
            "title": payload.get("Title"),
            "title_tw": payload.get("TitleTw"),
            "description": payload.get("Desc"),
            "description_tw": payload.get("DescTw"),
            "flag": payload.get("Flag"),
        }
    )


def _row_entity(build_id: int, row: CatalogRow) -> SourceEntity:
    values = _base_row_values(build_id, row)
    label_value = (
        row.payload.get("Name")
        or row.payload.get("Title")
        or row.source_id
        or f"row {row.row_number}"
    )
    return SourceEntity(
        entity_id=table_row_entity_id(
            build_id,
            row.table,
            row.source_id,
            row_number=row.row_number,
            workbook_sha256=row.workbook_sha256,
        ),
        kind="wanxiang_table_row_snapshot",
        label=f"{row.table} {label_value}",
        values=values,
        cell_source=_row_source(row),
    )


def _list_without_sentinel(payload: dict[str, Any], prefix: str, count: int) -> list[Any]:
    return [
        value
        for index in range(count)
        if (value := payload.get(f"{prefix}{index}")) not in (None, -1, "-1", "nil")
    ]


def _hero_extension(build_id: int, row: CatalogRow) -> SourceEntity:
    payload = row.payload
    hero_id = payload.get("Id")
    if isinstance(hero_id, bool) or not isinstance(hero_id, int) or hero_id < 0:
        raise CatalogSourceError("hero_id_invalid", f"row {row.row_number}")
    properties = _list_without_sentinel(payload, "Property", 6)
    skill_ids = _list_without_sentinel(payload, "SkillId", 4)
    ji_values = []
    for index in range(3):
        ji_id = payload.get(f"Ji{index}")
        ji_value = payload.get(f"JiValue{index}")
        if ji_id not in (None, -1, "-1", "nil"):
            ji_values.append({"id": ji_id, "value": ji_value})
    values = _base_row_values(build_id, row)
    values.update(
        _without_none(
            {
                "hero_id": hero_id,
                "id_name": payload.get("IdName"),
                "birth_id": payload.get("Birth"),
                "faction_text": (
                    str(payload["Menpai"])
                    if payload.get("Menpai") is not None
                    else None
                ),
                "card_name": payload.get("CardName"),
                "card_name_tw": payload.get("CardNameTw"),
                "base_description": payload.get("BaseDesc"),
                "level": payload.get("Level"),
                "rarity": payload.get("CardRare"),
                "card_path": payload.get("CardPath"),
                "image_path": payload.get("Image"),
                "hp": payload.get("Hp"),
                "power": payload.get("Power"),
                "skill_ids": skill_ids,
                "is_player": payload.get("IsPlayer"),
                "property_ids": properties,
                "ji_values": ji_values,
                "parent_id": payload.get("ParentId"),
                "is_atlas": payload.get("IsAtlas"),
                "atlas_index": payload.get("AtlasIndex"),
                "acquisition_description": payload.get("GetDesc"),
                "acquisition_description_tw": payload.get("GetDescTw"),
                "point_value": payload.get("Point"),
                "extra_hero_id": payload.get("ExtraHeroId"),
                "skin_group_id": payload.get("SkinGroupId"),
                "story_id": payload.get("StoryId"),
                "route_filter": payload.get("RouteFilter"),
            }
        )
    )
    return SourceEntity(
        entity_id=form_entity_id(build_id, hero_id),
        kind="wanxiang_character_form_snapshot",
        label=f"{payload.get('Name')} [{hero_id}]",
        values=values,
        cell_source=_row_source(row),
    )


def merge_source_entities(base: SourceEntity, extension: SourceEntity) -> SourceEntity:
    if (base.entity_id, base.kind, base.label) != (
        extension.entity_id,
        extension.kind,
        extension.label,
    ):
        raise CatalogSourceError(
            "entity_merge_identity_conflict", extension.entity_id
        )
    values = dict(base.values)
    sources = {
        key: base.source_for(key)
        for key in base.values
    }
    for key, value in extension.values.items():
        if key in values:
            if values[key] != value:
                raise CatalogSourceError(
                    "entity_merge_value_conflict",
                    f"{base.entity_id} {key}: {values[key]!r} != {value!r}",
                )
            continue
        values[key] = value
        sources[key] = extension.source_for(key)
    return SourceEntity(
        entity_id=base.entity_id,
        kind=base.kind,
        label=base.label,
        values=values,
        cell_source=base.cell_source,
        cell_sources=sources,
    )


def _reconcile_hero(base: SourceEntity, extension: SourceEntity) -> None:
    keys = (
        "source_row",
        "hero_id",
        "id_name",
        "name_zh",
        "name_tw",
        "title",
        "title_tw",
        "birth_id",
        "faction_text",
        "image_path",
        "card_path",
        "parent_id",
        "extra_hero_id",
        "skin_group_id",
        "story_id",
    )
    differences = {
        key: {"reduced": base.values.get(key), "full": extension.values.get(key)}
        for key in keys
        if base.values.get(key) != extension.values.get(key)
        and not (
            base.values.get(key) is None and extension.values.get(key) is None
        )
    }
    if differences:
        raise CatalogSourceError(
            "hero_registry_reconciliation_conflict",
            f"{base.entity_id}: {differences}",
        )


def _hero_non_form_entity(
    build_id: int,
    row: CatalogRow,
    *,
    kind: str,
    table_key: str,
) -> SourceEntity:
    values = _base_row_values(build_id, row)
    values.update(
        _without_none(
            {
                "hero_id": row.payload.get("Id"),
                "id_name": row.payload.get("IdName"),
                "birth_id": row.payload.get("Birth"),
            }
        )
    )
    return SourceEntity(
        entity_id=table_row_entity_id(
            build_id,
            table_key,
            row.source_id,
            row_number=row.row_number,
            workbook_sha256=row.workbook_sha256,
        ),
        kind=kind,
        label=f"{row.payload.get('Name')} [{row.source_id}]",
        values=values,
        cell_source=_row_source(row),
    )


def compose_catalog_entities(
    build_id: int,
    wave1_entities: tuple[SourceEntity, ...],
    catalog: CatalogRows,
) -> tuple[SourceEntity, ...]:
    entities = {entity.entity_id: entity for entity in wave1_entities}
    if len(entities) != len(wave1_entities):
        raise CatalogSourceError("duplicate_wave1_entity_id", "wave1 selection")

    for row in catalog.rows:
        if row.table != "Hero":
            entity = _row_entity(build_id, row)
            if entity.entity_id in entities:
                raise CatalogSourceError("duplicate_catalog_entity_id", entity.entity_id)
            entities[entity.entity_id] = entity
            continue
        hero_type = row.payload.get("Type")
        if hero_type == 0:
            extension = _hero_extension(build_id, row)
            base = entities.get(extension.entity_id)
            if base is None:
                raise CatalogSourceError("hero_form_missing", extension.entity_id)
            _reconcile_hero(base, extension)
            entities[extension.entity_id] = merge_source_entities(base, extension)
        elif hero_type == 1:
            entity = _hero_non_form_entity(
                build_id,
                row,
                kind="wanxiang_treasure_snapshot",
                table_key="HeroTreasure",
            )
            if entity.entity_id in entities:
                raise CatalogSourceError("duplicate_catalog_entity_id", entity.entity_id)
            entities[entity.entity_id] = entity
        elif hero_type is None and row.source_id == -1:
            entity = _hero_non_form_entity(
                build_id,
                row,
                kind="wanxiang_hero_sentinel_snapshot",
                table_key="HeroSentinel",
            )
            if entity.entity_id in entities:
                raise CatalogSourceError("duplicate_catalog_entity_id", entity.entity_id)
            entities[entity.entity_id] = entity
        else:
            raise CatalogSourceError(
                "hero_type_unsupported",
                f"row {row.row_number}: {hero_type!r}",
            )

    build_id_value = f"wx-build-{build_id}"
    build = entities.get(build_id_value)
    if build is None:
        raise CatalogSourceError("build_entity_missing", build_id_value)
    catalog_source = "wanxiang:catalog-manifest"
    build_extension_values = {
        "source_build_id": build_id,
        "catalog_schema_version": "wanxiang-full-static-canon/v1",
        "catalog_manifest_path": "evidence/source-inventory/current-verification.manifest.json",
        "catalog_manifest_sha256": catalog.source_hashes[
            "manifest:current-verification.manifest.json"
        ],
        "catalog_workbook_hashes": {
            key.removeprefix("workbook:"): value
            for key, value in catalog.source_hashes.items()
            if key.startswith("workbook:")
        },
        "catalog_table_counts": catalog.table_counts,
        "catalog_total_rows": sum(catalog.table_counts.values()),
        "catalog_source_fingerprint": catalog.source_fingerprint,
        "catalog_reader_version": READER_VERSION,
        "runtime_candidate_files": [
            {
                "path": candidate.path,
                "length": candidate.length,
                "sha256": candidate.sha256,
            }
            for candidate in catalog.runtime_candidates
        ],
    }
    build_extension = SourceEntity(
        entity_id=build.entity_id,
        kind=build.kind,
        label=build.label,
        values=build_extension_values,
        cell_source=catalog_source,
    )
    entities[build.entity_id] = merge_source_entities(build, build_extension)
    return tuple(sorted(entities.values(), key=lambda entity: entity.entity_id))


def compose_full_selection(
    wave1: SnapshotSelection,
    catalog: CatalogRows,
    *,
    include_edges: bool = False,
) -> SnapshotSelection:
    if include_edges:
        raise CatalogSourceError(
            "reference_graph_unavailable",
            "reference graph is introduced by Task 5",
        )
    entities = compose_catalog_entities(wave1.build_id, wave1.entities, catalog)
    represented_rows = sum("source_table" in entity.values for entity in entities)
    if represented_rows != len(catalog.rows):
        raise CatalogSourceError(
            "catalog_row_representation_mismatch",
            f"expected {len(catalog.rows)}, got {represented_rows}",
        )
    counts = dict(Counter(entity.kind for entity in entities))
    source_hashes = dict(wave1.source_hashes)
    source_hashes.update(
        {f"catalog:{key}": value for key, value in catalog.source_hashes.items()}
    )
    return SnapshotSelection(
        build_id=wave1.build_id,
        source_hashes=source_hashes,
        entities=entities,
        counts=counts,
        scope_name="full_catalog",
        owned_keys=frozenset(
            key for entity in entities for key in entity.values
        ),
        scope_entity_kinds=frozenset(counts),
    )


def compose_full_catalog(
    config: ProjectConfig,
    contract: CatalogContract | None = None,
    *,
    include_edges: bool = False,
) -> SnapshotSelection:
    wave1 = load_snapshot(config)
    catalog = load_catalog_rows(contract or default_catalog_contract())
    return compose_full_selection(
        wave1,
        catalog,
        include_edges=include_edges,
    )

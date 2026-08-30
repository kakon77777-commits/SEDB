from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from config import ProjectConfig
from identity import (
    asset_entity_id,
    build_entity_id,
    candidate_entity_id,
    character_identity_id,
    form_entity_id,
    gap_entity_id,
    methodology_entity_id,
    normalize_name_key,
)


ROLE_TARGETS_PATH = (
    "art-engineering/inventory/build-25006280/role-targets.json"
)
CHARACTERS_PATH = "art-engineering/registry/characters.json"
UNITY_INDEX_PATH = (
    "art-engineering/inventory/build-25006280/unity-object-index.json"
)
MAPPING_CANDIDATES_PATH = (
    "art-engineering/inventory/build-25006280/mapping-candidates.json"
)
EXTRACTION_RESULT_PATH = "art-engineering/evidence/extraction-result.json"
OUTPUT_MANIFEST_PATH = (
    "art-engineering/evidence/extraction-output-manifest.json"
)
SOURCE_ROOTS_PATH = "evidence/source-inventory/source-roots.json"
ART_CHECKPOINT_PATH = "evidence/checkpoints/task-18-art-extraction-final.json"
METHODOLOGY_CHECKPOINT_PATH = (
    "evidence/checkpoints/task-19-methodology-papers.json"
)

CORE_JSON_SPECS = {
    ROLE_TARGETS_PATH: "wanxiang-role-targets/v1",
    CHARACTERS_PATH: "wanxiang-character-registry/v1",
    UNITY_INDEX_PATH: "wanxiang-unity-object-index/v1",
    MAPPING_CANDIDATES_PATH: "wanxiang-role-mapping/v1",
    EXTRACTION_RESULT_PATH: "wanxiang-role-extraction/v1",
    OUTPUT_MANIFEST_PATH: "wanxiang-role-art-output-manifest/v1",
    SOURCE_ROOTS_PATH: "wanxiang-source-roots/v1",
}

METHODOLOGY_SPECS = (
    {
        "slug": "exposure-tension-decoupling",
        "version": "v0.1",
        "title": "Exposure–Tension Decoupling / SFW Sensuality Control",
        "paper": (
            "inputs/methodology-papers/2026-08-30/"
            "exposure-tension-decoupling-v0.1/documents/"
            "Exposure_Tension_Decoupling_SFW_Sensuality_Control_Internal_v0.1.md"
        ),
        "validation": (
            "inputs/methodology-papers/2026-08-30/"
            "exposure-tension-decoupling-v0.1/documents/"
            "VALIDATION_MANIFEST.json"
        ),
        "intended_use": (
            "Independent Exposure, Tension, Audience and Safety control; "
            "conservative-first SFW editing reference."
        ),
    },
    {
        "slug": "heluo-character-art-methodology",
        "version": "v0.1",
        "title": "Heluo Character Art Methodology",
        "paper": (
            "inputs/methodology-papers/2026-08-30/"
            "heluo-character-art-methodology-v0.1/documents/"
            "Heluo_Character_Art_Methodology_Internal_Paper_v0.1.md"
        ),
        "validation": (
            "inputs/methodology-papers/2026-08-30/"
            "heluo-character-art-methodology-v0.1/documents/"
            "VALIDATION_MANIFEST.json"
        ),
        "intended_use": (
            "Character identity, motif, gesture, rendering and group-"
            "difference methodology reference."
        ),
    },
)

_CANDIDATE_FILENAME = re.compile(
    r"^(?P<source>.+)__(?P<path_id>\d+)__(?P<object_type>[^.]+)\.png$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class SourceValidationError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class SourceEntity:
    entity_id: str
    kind: str
    label: str
    values: dict[str, Any]
    cell_source: str
    cell_sources: dict[str, str] = field(default_factory=dict)

    def source_for(self, key: str) -> str:
        return self.cell_sources.get(key, self.cell_source)


@dataclass(frozen=True)
class SnapshotSelection:
    build_id: int
    source_hashes: dict[str, str]
    entities: tuple[SourceEntity, ...]
    counts: dict[str, int]
    scope_name: str = "wave1"
    owned_keys: frozenset[str] = frozenset()
    scope_entity_kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _InputFile:
    relative: str
    path: Path
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest().upper()

    @property
    def length(self) -> int:
        return len(self.data)


def _error(reason_code: str, message: str) -> None:
    raise SourceValidationError(reason_code, message)


def _normalized_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        _error("unsafe_source_path", f"invalid relative source path: {value!r}")
    return pure.as_posix()


def _safe_source_path(root: Path, relative: str) -> Path:
    relative = _normalized_relative(relative)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        _error("missing_source_root", f"cannot resolve source root {root}: {exc}")
    if any(part.casefold() == "steamapps" for part in resolved_root.parts):
        _error("steam_path_rejected", f"source root is inside Steam: {resolved_root}")

    unresolved = resolved_root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        _error("missing_source_file", f"cannot resolve {relative}: {exc}")
    if not resolved.is_relative_to(resolved_root):
        _error("source_path_escape", f"source path escapes root: {relative}")
    if any(part.casefold() == "steamapps" for part in resolved.parts):
        _error("steam_path_rejected", f"source path is inside Steam: {relative}")
    return resolved


def _read_input(root: Path, relative: str) -> _InputFile:
    relative = _normalized_relative(relative)
    path = _safe_source_path(root, relative)
    try:
        data = path.read_bytes()
    except OSError as exc:
        _error("source_read_failed", f"cannot read {relative}: {exc}")
    return _InputFile(relative=relative, path=path, data=data)


def _decode_json(source: _InputFile) -> dict[str, Any]:
    try:
        value = json.loads(source.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error("invalid_json", f"invalid UTF-8 JSON in {source.relative}: {exc}")
    if not isinstance(value, dict):
        _error("invalid_json_shape", f"JSON root must be an object: {source.relative}")
    return value


def _require_list(value: dict[str, Any], key: str, relative: str) -> list[Any]:
    result = value.get(key)
    if not isinstance(result, list):
        _error("invalid_source_contract", f"{relative} requires list {key!r}")
    return result


def _validate_schema(value: dict[str, Any], expected: str, relative: str) -> None:
    if value.get("schema") != expected:
        _error(
            "unsupported_schema",
            f"{relative} schema {value.get('schema')!r}; expected {expected!r}",
        )


def _checkpoint_records(
    value: dict[str, Any], relative: str
) -> dict[str, dict[str, Any]]:
    _validate_schema(value, "non-git-checkpoint/v1", relative)
    records: dict[str, dict[str, Any]] = {}
    for raw in _require_list(value, "files", relative):
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            _error("invalid_checkpoint", f"invalid file record in {relative}")
        path = _normalized_relative(raw["path"])
        if path in records:
            _error("invalid_checkpoint", f"duplicate checkpoint path {path}")
        records[path] = raw
    return records


def _validate_checkpoint_file(
    source: _InputFile,
    records: dict[str, dict[str, Any]],
    checkpoint_relative: str,
) -> None:
    record = records.get(source.relative)
    if record is None:
        _error(
            "checkpoint_entry_missing",
            f"{checkpoint_relative} does not list {source.relative}",
        )
    if record.get("length") != source.length:
        _error(
            "source_hash_mismatch",
            f"length drift for {source.relative}",
        )
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or expected_hash.upper() != source.sha256:
        _error(
            "source_hash_mismatch",
            f"SHA-256 drift for {source.relative}",
        )


def _normalize_resource_path(value: str) -> str:
    if not isinstance(value, str):
        _error("invalid_resource_path", f"resource path is not text: {value!r}")
    normalized = value.replace("\\", "/").strip("/").lower()
    normalized = "/".join(part for part in normalized.split("/") if part)
    if not normalized:
        _error("invalid_resource_path", "empty resource path")
    return normalized


def _manifest_path_key(value: str) -> str:
    return _normalize_resource_path(value)


def _without_png(value: str) -> str:
    normalized = _manifest_path_key(value)
    if not normalized.endswith(".png"):
        _error("invalid_manifest_path", f"manifest path is not PNG: {value}")
    return normalized[:-4]


def _int_value(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _error("invalid_source_contract", f"{label} must be integer >= {minimum}")
    return value


def _optional_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _append_entity(
    entities: list[SourceEntity],
    seen: set[str],
    entity: SourceEntity,
) -> None:
    if entity.entity_id in seen:
        _error("duplicate_entity_id", f"duplicate entity ID {entity.entity_id}")
    seen.add(entity.entity_id)
    entities.append(entity)


def _validate_manifest_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        _error("invalid_output_manifest", "manifest record requires path")
    length = record.get("length")
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        _error("invalid_output_manifest", f"invalid length for {record['path']}")
    sha256 = record.get("sha256")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        _error("invalid_output_manifest", f"invalid SHA-256 for {record['path']}")
    return record


def _source_hash_digest(source_hashes: dict[str, str]) -> str:
    projection = "\n".join(
        f"{path}\t{source_hashes[path]}" for path in sorted(source_hashes)
    )
    return hashlib.sha256(projection.encode("utf-8")).hexdigest().upper()


def _validate_mapping_counts(mapping_data: dict[str, Any], mappings: list[Any]) -> None:
    if mapping_data.get("mappingCount") != len(mappings):
        _error("mapping_count_mismatch", "mappingCount does not match mappings")
    observed = Counter()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            _error("invalid_source_contract", "mapping record must be an object")
        observed[(mapping.get("class"), mapping.get("status"))] += 1
    declared = Counter()
    for record in _require_list(mapping_data, "counts", MAPPING_CANDIDATES_PATH):
        if not isinstance(record, dict):
            _error("invalid_source_contract", "mapping count must be an object")
        declared[(record.get("class"), record.get("status"))] += record.get("count", 0)
    if observed != declared:
        _error("mapping_count_mismatch", "mapping status counts do not reconcile")


def _load_methodology(
    root: Path,
    inputs: dict[str, _InputFile],
    methodology_checkpoint: dict[str, dict[str, Any]],
    entities: list[SourceEntity],
    seen_ids: set[str],
) -> None:
    for spec in METHODOLOGY_SPECS:
        paper = _read_input(root, spec["paper"])
        validation_source = _read_input(root, spec["validation"])
        validation = _decode_json(validation_source)
        inputs[paper.relative] = paper
        inputs[validation_source.relative] = validation_source
        _validate_checkpoint_file(
            paper, methodology_checkpoint, METHODOLOGY_CHECKPOINT_PATH
        )
        _validate_checkpoint_file(
            validation_source,
            methodology_checkpoint,
            METHODOLOGY_CHECKPOINT_PATH,
        )

        if validation.get("validation") != "PASS":
            _error(
                "paper_validation_failed",
                f"methodology validation is not PASS: {validation_source.relative}",
            )
        if validation.get("encoding") != "UTF-8":
            _error(
                "paper_validation_failed",
                f"methodology encoding is not UTF-8: {validation_source.relative}",
            )
        if validation.get("file") != paper.path.name:
            _error(
                "paper_validation_failed",
                f"methodology file binding mismatch: {validation_source.relative}",
            )
        declared_hash = validation.get("sha256")
        if not isinstance(declared_hash, str) or declared_hash.upper() != paper.sha256:
            _error(
                "paper_validation_hash_mismatch",
                f"methodology paper hash mismatch: {paper.relative}",
            )
        if validation.get("version") not in (None, spec["version"]):
            _error(
                "paper_validation_failed",
                f"methodology version mismatch: {validation_source.relative}",
            )

        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=methodology_entity_id(spec["slug"], spec["version"]),
                kind="wanxiang_methodology_reference",
                label=spec["title"],
                values={
                    "source_schema": "methodology-validation-manifest/v1",
                    "source_path": paper.relative,
                    "source_sha256": paper.sha256,
                    "source_evidence_level": "USER_AUTHORED_METHOD_REFERENCE",
                    "record_status": "PRESERVED_NOT_AUTO_ADOPTED",
                    "methodology_title": spec["title"],
                    "methodology_version": spec["version"],
                    "methodology_path": paper.relative,
                    "methodology_sha256": paper.sha256,
                    "methodology_validation_path": validation_source.relative,
                    "methodology_intended_use": spec["intended_use"],
                },
                cell_source=f"wanxiang:{paper.relative}",
            ),
        )


def load_snapshot(config: ProjectConfig) -> SnapshotSelection:
    root = config.source_root
    expected_counts = dict(config.expected_entity_counts)
    inputs: dict[str, _InputFile] = {}
    json_values: dict[str, dict[str, Any]] = {}

    for relative, schema in CORE_JSON_SPECS.items():
        source = _read_input(root, relative)
        value = _decode_json(source)
        _validate_schema(value, schema, relative)
        inputs[relative] = source
        json_values[relative] = value

    art_checkpoint_source = _read_input(root, ART_CHECKPOINT_PATH)
    art_checkpoint_value = _decode_json(art_checkpoint_source)
    art_checkpoint = _checkpoint_records(
        art_checkpoint_value, ART_CHECKPOINT_PATH
    )
    inputs[ART_CHECKPOINT_PATH] = art_checkpoint_source
    for relative in (
        ROLE_TARGETS_PATH,
        CHARACTERS_PATH,
        UNITY_INDEX_PATH,
        MAPPING_CANDIDATES_PATH,
        EXTRACTION_RESULT_PATH,
        OUTPUT_MANIFEST_PATH,
    ):
        _validate_checkpoint_file(inputs[relative], art_checkpoint, ART_CHECKPOINT_PATH)

    methodology_checkpoint_source = _read_input(root, METHODOLOGY_CHECKPOINT_PATH)
    methodology_checkpoint_value = _decode_json(methodology_checkpoint_source)
    methodology_checkpoint = _checkpoint_records(
        methodology_checkpoint_value, METHODOLOGY_CHECKPOINT_PATH
    )
    inputs[METHODOLOGY_CHECKPOINT_PATH] = methodology_checkpoint_source

    source_roots = json_values[SOURCE_ROOTS_PATH]
    game = source_roots.get("game")
    if not isinstance(game, dict):
        _error("invalid_source_contract", "source-roots game record is missing")
    if game.get("buildId") != config.build_id:
        _error(
            "build_id_mismatch",
            f"source BuildID {game.get('buildId')} != configured {config.build_id}",
        )
    if game.get("steamAppId") != 3039500:
        _error("app_id_mismatch", "unexpected Steam AppID")

    role_targets = json_values[ROLE_TARGETS_PATH]
    heroes = _require_list(role_targets, "heroes", ROLE_TARGETS_PATH)
    expected_forms = expected_counts.get("wanxiang_character_form_snapshot")
    if len(heroes) != expected_forms:
        _error(
            "role_target_count_mismatch",
            f"Hero rows {len(heroes)} != expected {expected_forms}",
        )
    stats = role_targets.get("stats")
    if not isinstance(stats, dict) or stats.get("heroRows") != len(heroes):
        _error("role_target_count_mismatch", "role-target stats do not reconcile")

    hero_by_id: dict[int, dict[str, Any]] = {}
    identity_groups: dict[str, list[dict[str, Any]]] = {}
    for raw in heroes:
        if not isinstance(raw, dict):
            _error("invalid_source_contract", "Hero row must be an object")
        hero_id = _int_value(raw.get("id"), "Hero id")
        if hero_id in hero_by_id:
            _error("duplicate_entity_id", f"duplicate Hero id {hero_id}")
        name = raw.get("name")
        if not isinstance(name, str) or not normalize_name_key(name):
            _error("invalid_source_contract", f"Hero {hero_id} has invalid name")
        hero_by_id[hero_id] = raw
        identity_groups.setdefault(normalize_name_key(name), []).append(raw)
    expected_identities = expected_counts.get("wanxiang_character_identity")
    if len(identity_groups) != expected_identities:
        _error(
            "identity_count_mismatch",
            f"identity groups {len(identity_groups)} != expected {expected_identities}",
        )
    if stats.get("uniqueNames") != len(identity_groups):
        _error("identity_count_mismatch", "role-target uniqueNames does not reconcile")

    character_registry = json_values[CHARACTERS_PATH]
    characters = _require_list(character_registry, "characters", CHARACTERS_PATH)
    if len(characters) != expected_forms:
        _error("character_registry_mismatch", "character registry row count mismatch")
    character_by_id: dict[int, dict[str, Any]] = {}
    for raw in characters:
        if not isinstance(raw, dict):
            _error("invalid_source_contract", "character row must be an object")
        hero_id = _int_value(raw.get("id"), "character id")
        if hero_id in character_by_id:
            _error("duplicate_entity_id", f"duplicate character id {hero_id}")
        character_by_id[hero_id] = raw
    if set(character_by_id) != set(hero_by_id):
        _error("character_registry_mismatch", "character and Hero IDs differ")
    for hero_id, hero in hero_by_id.items():
        character = character_by_id[hero_id]
        for key in ("name", "nameTw", "idName", "expectedImagePath", "expectedCardPath"):
            if character.get(key) != hero.get(key):
                _error(
                    "character_registry_mismatch",
                    f"Hero {hero_id} field {key} differs from registry",
                )

    unity_index = json_values[UNITY_INDEX_PATH]
    image_objects = _require_list(unity_index, "imageObjects", UNITY_INDEX_PATH)
    role_records: list[tuple[str, dict[str, Any]]] = []
    role_by_path: dict[str, dict[str, Any]] = {}
    for raw in image_objects:
        if not isinstance(raw, dict):
            _error("invalid_source_contract", "Unity image object must be an object")
        paths = raw.get("containerPaths", [])
        if not isinstance(paths, list):
            _error("invalid_source_contract", "containerPaths must be a list")
        for path in paths:
            normalized = _normalize_resource_path(path)
            if not normalized.startswith("roles/"):
                continue
            if normalized in role_by_path:
                _error("duplicate_entity_id", f"duplicate exact role path {normalized}")
            role_by_path[normalized] = raw
            role_records.append((normalized, raw))
    expected_assets = expected_counts.get("wanxiang_visual_asset_snapshot")
    if len(role_records) != expected_assets:
        _error(
            "asset_count_mismatch",
            f"exact role paths {len(role_records)} != expected {expected_assets}",
        )

    mapping_data = json_values[MAPPING_CANDIDATES_PATH]
    mappings = _require_list(mapping_data, "mappings", MAPPING_CANDIDATES_PATH)
    _validate_mapping_counts(mapping_data, mappings)
    exact_mapping_by_path: dict[str, dict[str, Any]] = {}
    ambiguous_mapping_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    mapping_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for mapping in mappings:
        role_class = mapping.get("class")
        if not isinstance(role_class, str):
            _error("invalid_source_contract", "mapping class must be text")
        hero_id = _int_value(mapping.get("id"), "mapping id")
        key = (role_class.casefold(), hero_id)
        if key in mapping_by_key:
            _error("duplicate_entity_id", f"duplicate mapping key {key}")
        mapping_by_key[key] = mapping
        expected_path = _normalize_resource_path(mapping.get("expectedPath"))
        status = mapping.get("status")
        if status == "EXACT_CONTAINER_PATH":
            if expected_path not in role_by_path:
                _error(
                    "exact_path_omitted",
                    f"exact mapping is absent from ResourceManager inventory: {expected_path}",
                )
            if expected_path in exact_mapping_by_path:
                _error("duplicate_entity_id", f"duplicate exact mapping {expected_path}")
            exact_mapping_by_path[expected_path] = mapping
        elif status == "AMBIGUOUS":
            if expected_path in role_by_path:
                _error(
                    "ambiguous_promoted_to_exact",
                    f"ambiguous mapping has exact ResourceManager path: {expected_path}",
                )
            ambiguous_mapping_by_key[key] = mapping
        else:
            _error("unsupported_mapping_status", f"unsupported mapping status {status!r}")

    extraction = json_values[EXTRACTION_RESULT_PATH]
    targets = _require_list(extraction, "targets", EXTRACTION_RESULT_PATH)
    if len(targets) != len(mappings):
        _error("extraction_target_count_mismatch", "target and mapping counts differ")
    exact_target_by_resource: dict[str, dict[str, Any]] = {}
    ambiguous_targets: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            _error("invalid_source_contract", "extraction target must be an object")
        role_class = target.get("class")
        if not isinstance(role_class, str):
            _error("invalid_source_contract", "target class must be text")
        hero_id = _int_value(target.get("id"), "target id")
        key = (role_class.casefold(), hero_id)
        mapping = mapping_by_key.get(key)
        if mapping is None:
            _error("extraction_mapping_mismatch", f"target has no mapping {key}")
        if target.get("mappingStatus") != mapping.get("status"):
            _error("extraction_mapping_mismatch", f"target status differs for {key}")
        if mapping.get("status") == "EXACT_CONTAINER_PATH":
            if target.get("status") != "EXTRACTED" or not isinstance(
                target.get("outputPath"), str
            ):
                _error("extraction_mapping_mismatch", f"exact target not extracted: {key}")
            resource_path = _without_png(target["outputPath"])
            expected_path = _normalize_resource_path(mapping["expectedPath"])
            if resource_path != expected_path:
                _error("extraction_mapping_mismatch", f"output path differs for {key}")
            exact_target_by_resource[resource_path] = target
        else:
            if target.get("status") != "AMBIGUOUS" or target.get("outputPath") is not None:
                _error(
                    "ambiguous_promoted_to_exact",
                    f"ambiguous target has canonical output: {key}",
                )
            ambiguous_targets.append(target)

    manifest = json_values[OUTPUT_MANIFEST_PATH]
    manifest_files = [
        _validate_manifest_record(record)
        for record in _require_list(manifest, "files", OUTPUT_MANIFEST_PATH)
    ]
    if manifest.get("fileCount") != len(manifest_files):
        _error(
            "output_manifest_count_mismatch",
            "fileCount does not match manifest records",
        )
    total_bytes = sum(record["length"] for record in manifest_files)
    if manifest.get("totalBytes") != total_bytes:
        _error(
            "output_manifest_byte_mismatch",
            "totalBytes does not match manifest lengths",
        )
    if extraction.get("outputBytes") != total_bytes:
        _error(
            "output_manifest_byte_mismatch",
            "extraction outputBytes does not match manifest",
        )

    manifest_by_path: dict[str, dict[str, Any]] = {}
    canonical_manifest: dict[str, dict[str, Any]] = {}
    candidate_manifest: list[dict[str, Any]] = []
    ambiguous_expected = {
        _normalize_resource_path(mapping["expectedPath"])
        for mapping in ambiguous_mapping_by_key.values()
    }
    for record in manifest_files:
        path_key = _manifest_path_key(record["path"])
        if path_key in manifest_by_path:
            _error("duplicate_entity_id", f"duplicate manifest path {record['path']}")
        manifest_by_path[path_key] = record
        if path_key.startswith("roles/"):
            resource_path = _without_png(record["path"])
            if resource_path in ambiguous_expected:
                _error(
                    "ambiguous_promoted_to_exact",
                    f"ambiguous candidate appears under Roles/: {record['path']}",
                )
            canonical_manifest[resource_path] = record
        elif path_key.startswith("ambiguous/"):
            candidate_manifest.append(record)
        else:
            _error("invalid_manifest_path", f"unexpected output path {record['path']}")

    if set(canonical_manifest) != set(exact_target_by_resource):
        _error(
            "output_manifest_target_mismatch",
            "canonical manifest paths do not equal extracted exact targets",
        )
    expected_candidates = expected_counts.get("wanxiang_visual_candidate_snapshot")
    if len(candidate_manifest) != expected_candidates:
        _error(
            "candidate_count_mismatch",
            f"ambiguous PNGs {len(candidate_manifest)} != expected {expected_candidates}",
        )

    expected_gaps = expected_counts.get("wanxiang_source_gap_snapshot")
    gap_targets = [
        target
        for target in ambiguous_targets
        if str(target.get("class", "")).casefold() == "image"
        and target.get("heroIdKnown") is True
    ]
    if len(gap_targets) != expected_gaps:
        _error(
            "gap_count_mismatch",
            f"known Image gaps {len(gap_targets)} != expected {expected_gaps}",
        )

    entities: list[SourceEntity] = []
    seen_ids: set[str] = set()
    _load_methodology(
        root,
        inputs,
        methodology_checkpoint,
        entities,
        seen_ids,
    )
    source_hashes = {relative: source.sha256 for relative, source in inputs.items()}
    source_manifest_hash = _source_hash_digest(source_hashes)

    _append_entity(
        entities,
        seen_ids,
        SourceEntity(
            entity_id=build_entity_id(config.build_id),
            kind="wanxiang_build_snapshot",
            label=f"Wanxiang Build {config.build_id}",
            values={
                "source_build_id": config.build_id,
                "source_schema": "wanxiang-character-canon-source/v1",
                "source_path": ART_CHECKPOINT_PATH,
                "source_sha256": source_manifest_hash,
                "source_evidence_level": "HASH_GATED_OFFLINE_SNAPSHOT",
                "record_status": "SOURCE_SNAPSHOT",
                "steam_app_id": game["steamAppId"],
                "depot_manifest": str(game.get("depotManifest", "")),
                "snapshot_status": "ROLE_EXTRACT_PARTIAL",
            },
            cell_source=f"wanxiang:{SOURCE_ROOTS_PATH}",
        ),
    )

    role_source_hash = inputs[ROLE_TARGETS_PATH].sha256
    for normalized_name, group in sorted(identity_groups.items()):
        form_ids = sorted(
            form_entity_id(config.build_id, _int_value(hero["id"], "Hero id"))
            for hero in group
        )
        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=character_identity_id(normalized_name),
                kind="wanxiang_character_identity",
                label=normalized_name,
                values={
                    "source_build_id": config.build_id,
                    "source_schema": role_targets["schema"],
                    "source_path": ROLE_TARGETS_PATH,
                    "source_sha256": role_source_hash,
                    "source_evidence_level": "EXACT_NORMALIZED_NAME_GROUP",
                    "record_status": "PROVISIONAL_IDENTITY",
                    "normalized_name_key": normalized_name,
                    "identity_status": "provisional",
                    "identity_group_evidence": "NFKC_EXACT_NAME_GROUP",
                    "linked_form_ids": form_ids,
                    "name_zh": group[0]["name"],
                    "name_tw": group[0].get("nameTw", ""),
                },
                cell_source=f"wanxiang:{ROLE_TARGETS_PATH}",
            ),
        )

    character_source_hash = inputs[CHARACTERS_PATH].sha256
    for hero_id in sorted(character_by_id):
        row = character_by_id[hero_id]
        identity_id = character_identity_id(row["name"])
        values = _optional_values(
            {
                "source_build_id": config.build_id,
                "source_schema": character_registry["schema"],
                "source_path": CHARACTERS_PATH,
                "source_sha256": character_source_hash,
                "source_row": row.get("sourceRow"),
                "source_evidence_level": "EXACT_HERO_SOURCE_ROW",
                "record_status": "SOURCE_SNAPSHOT",
                "identity_entity_id": identity_id,
                "hero_id": hero_id,
                "id_name": row.get("idName"),
                "name_zh": row.get("name"),
                "name_tw": row.get("nameTw"),
                "title": row.get("title"),
                "title_tw": row.get("titleTw"),
                "birth_id": row.get("birth"),
                "faction_text": row.get("menpai"),
                "image_path": row.get("expectedImagePath"),
                "card_path": row.get("expectedCardPath"),
                "parent_id": row.get("parentId"),
                "extra_hero_id": row.get("extraHeroId"),
                "skin_group_id": row.get("skinGroupId"),
                "story_id": row.get("storyId"),
                "property_values": {
                    "type": row.get("type"),
                    "variantCount": row.get("variantCount"),
                    "variantIndex": row.get("variantIndex"),
                },
            }
        )
        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=form_entity_id(config.build_id, hero_id),
                kind="wanxiang_character_form_snapshot",
                label=f"{row['name']} [{hero_id}]",
                values=values,
                cell_source=f"wanxiang:{CHARACTERS_PATH}",
            ),
        )

    unity_source_hash = inputs[UNITY_INDEX_PATH].sha256
    for resource_path, unity_object in sorted(role_records):
        parts = resource_path.split("/")
        role_class = parts[1].title() if len(parts) > 1 else "Unknown"
        numeric_id = int(parts[-1]) if parts[-1].isdigit() else None
        mapping = exact_mapping_by_path.get(resource_path)
        target = exact_target_by_resource.get(resource_path)
        manifest_record = canonical_manifest.get(resource_path)
        if (mapping is None) != (target is None) or (target is None) != (
            manifest_record is None
        ):
            _error("extraction_mapping_mismatch", f"partial exact mapping {resource_path}")
        values = _optional_values(
            {
                "source_build_id": config.build_id,
                "source_schema": unity_index["schema"],
                "source_path": UNITY_INDEX_PATH,
                "source_sha256": unity_source_hash,
                "source_evidence_level": "EXACT_RESOURCE_MANAGER_PATH",
                "record_status": "SOURCE_SNAPSHOT",
                "role_class": role_class,
                "resource_path": resource_path,
                "resource_numeric_id": numeric_id,
                "unity_source_file": unity_object.get("sourceFile"),
                "unity_path_id": unity_object.get("pathId"),
                "mapping_status": (
                    mapping.get("status")
                    if mapping is not None
                    else "EXACT_INVENTORY_UNMAPPED"
                ),
                "extraction_status": (
                    target.get("status") if target is not None else "NOT_EXTRACTED"
                ),
                "hero_id_known": (
                    mapping.get("heroIdKnown")
                    if mapping is not None
                    else numeric_id in hero_by_id
                ),
                "png_path": manifest_record.get("path") if manifest_record else None,
                "png_sha256": (
                    manifest_record.get("sha256") if manifest_record else None
                ),
                "png_length": (
                    manifest_record.get("length") if manifest_record else None
                ),
                "image_width": unity_object.get("width"),
                "image_height": unity_object.get("height"),
                "image_mode": (
                    manifest_record.get("mode") if manifest_record else None
                ),
                "alpha_extrema": (
                    manifest_record.get("alphaExtrema")
                    if manifest_record
                    else None
                ),
            }
        )
        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=asset_entity_id(config.build_id, resource_path),
                kind="wanxiang_visual_asset_snapshot",
                label=f"{role_class} {parts[-1]}",
                values=values,
                cell_source=f"wanxiang:{UNITY_INDEX_PATH}",
            ),
        )

    output_source_hash = inputs[OUTPUT_MANIFEST_PATH].sha256
    for index, record in enumerate(sorted(candidate_manifest, key=lambda item: item["path"])):
        path_parts = PurePosixPath(record["path"].replace("\\", "/")).parts
        if len(path_parts) < 4 or path_parts[0].casefold() != "ambiguous":
            _error("invalid_candidate_path", f"invalid candidate path {record['path']}")
        role_class = path_parts[1]
        try:
            hero_id = int(path_parts[2])
        except ValueError:
            _error("invalid_candidate_path", f"candidate ID is not numeric: {record['path']}")
        mapping = ambiguous_mapping_by_key.get((role_class.casefold(), hero_id))
        if mapping is None:
            _error(
                "invalid_candidate_mapping",
                f"candidate has no ambiguous mapping: {record['path']}",
            )
        filename_match = _CANDIDATE_FILENAME.fullmatch(path_parts[-1])
        if filename_match is None:
            _error("invalid_candidate_path", f"invalid candidate filename {record['path']}")
        path_id = int(filename_match.group("path_id"))
        candidate_details = next(
            (
                candidate
                for candidate in mapping.get("candidates", [])
                if isinstance(candidate, dict)
                and candidate.get("pathId") == path_id
                and str(candidate.get("sourceFile", "")).casefold()
                == filename_match.group("source").casefold()
            ),
            None,
        )
        if candidate_details is None:
            _error(
                "invalid_candidate_mapping",
                f"candidate locator is not in mapping: {record['path']}",
            )
        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=candidate_entity_id(config.build_id, record["path"]),
                kind="wanxiang_visual_candidate_snapshot",
                label=f"Ambiguous {role_class} {hero_id} #{path_id}",
                values={
                    "source_build_id": config.build_id,
                    "source_schema": manifest["schema"],
                    "source_path": OUTPUT_MANIFEST_PATH,
                    "source_sha256": output_source_hash,
                    "source_row": index,
                    "source_evidence_level": "DECODED_NONCANONICAL_CANDIDATE",
                    "record_status": "AMBIGUOUS",
                    "role_class": role_class,
                    "resource_numeric_id": hero_id,
                    "unity_source_file": candidate_details.get("sourceFile"),
                    "unity_path_id": path_id,
                    "mapping_status": "AMBIGUOUS",
                    "extraction_status": "DECODED_CANDIDATE",
                    "hero_id_known": mapping.get("heroIdKnown", False),
                    "png_path": record["path"],
                    "png_sha256": record["sha256"],
                    "png_length": record["length"],
                    "image_width": record.get("width"),
                    "image_height": record.get("height"),
                    "image_mode": record.get("mode"),
                    "alpha_extrema": record.get("alphaExtrema"),
                    "candidate_reason": candidate_details.get(
                        "evidence", "AMBIGUOUS_NUMERIC_NAME"
                    ),
                    "related_expected_path": mapping["expectedPath"],
                },
                cell_source=f"wanxiang:{OUTPUT_MANIFEST_PATH}",
            ),
        )

    extraction_source_hash = inputs[EXTRACTION_RESULT_PATH].sha256
    for target in sorted(
        gap_targets, key=lambda item: (str(item["class"]), int(item["id"]))
    ):
        role_class = str(target["class"])
        hero_id = int(target["id"])
        mapping = ambiguous_mapping_by_key[(role_class.casefold(), hero_id)]
        _append_entity(
            entities,
            seen_ids,
            SourceEntity(
                entity_id=gap_entity_id(config.build_id, role_class, hero_id),
                kind="wanxiang_source_gap_snapshot",
                label=f"Missing exact {role_class} {hero_id}",
                values={
                    "source_build_id": config.build_id,
                    "source_schema": extraction["schema"],
                    "source_path": EXTRACTION_RESULT_PATH,
                    "source_sha256": extraction_source_hash,
                    "source_evidence_level": "KNOWN_TARGET_FAILURE",
                    "record_status": "OPEN_GAP",
                    "hero_id": hero_id,
                    "role_class": role_class,
                    "mapping_status": mapping["status"],
                    "extraction_status": target["status"],
                    "hero_id_known": target.get("heroIdKnown", False),
                    "gap_kind": "MISSING_EXACT_RESOURCE_PATH",
                    "gap_expected_path": mapping["expectedPath"],
                    "gap_reason": "AMBIGUOUS_NUMERIC_NAME",
                    "gap_candidates": mapping.get("candidates", []),
                },
                cell_source=f"wanxiang:{EXTRACTION_RESULT_PATH}",
            ),
        )

    source_hashes = {
        relative: source.sha256 for relative, source in sorted(inputs.items())
    }
    entities.sort(key=lambda entity: entity.entity_id)
    counts = dict(Counter(entity.kind for entity in entities))
    counts = {kind: counts.get(kind, 0) for kind in expected_counts}
    if counts != expected_counts:
        _error(
            "entity_count_mismatch",
            f"constructed counts {counts!r} != expected {expected_counts!r}",
        )
    return SnapshotSelection(
        build_id=config.build_id,
        source_hashes=source_hashes,
        entities=tuple(entities),
        counts=counts,
        scope_name="wave1",
        owned_keys=frozenset(
            key for entity in entities for key in entity.values
        ),
        scope_entity_kinds=frozenset(counts),
    )

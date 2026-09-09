from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from config import CURRENT_BUILD_ID, SCHEMA_VERSION, ProjectConfig


class SourceValidationError(ValueError):
    def __init__(self, reason_code: str, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or []


@dataclass(frozen=True)
class CatalogRecord:
    entity_id: str
    kind: str
    label: str
    values: dict[str, Any]


@dataclass(frozen=True)
class CatalogSnapshot:
    records: tuple[CatalogRecord, ...]
    entity_counts: Mapping[str, int]
    fingerprint: str
    source_hashes: Mapping[str, str]


def load_catalog(config: ProjectConfig) -> CatalogSnapshot:
    root = config.source_root.resolve()
    if not root.is_dir():
        raise SourceValidationError("source_root_missing", f"source root not found: {root}")
    verified = _verify_source_hashes(root, config.source_hashes)

    old_identity_path = "evidence/source-identity.json"
    new_identity_path = "evidence/build-25099888/source-identity.json"
    delta_path = "evidence/build-25099888/build-delta-summary.json"
    state_path = "evidence/build-25099888/state-model-summary.json"
    model_path = "evidence/build-25099888/model-source-inventory.csv"
    usage_path = "evidence/build-25099888/trigger-function-usage.csv"
    trigger_path = "evidence/build-25099888/trigger-summary.csv"
    function_path = "derived/build-25099888/decrypted_game_data/Game/Function.json"
    asset_path = "derived/build-25099888/decrypted_config/filelistinfoE.json"
    ledger_path = "toolchain/reports/evidence-ledger.md"
    il_path = "evidence/build-25099888/il-anchor-summary.json"
    old_il_path = "evidence/build-25099888/il-anchor-old-build-24413414-summary.json"

    old_identity = _read_json(root / old_identity_path)
    new_identity = _read_json(root / new_identity_path)
    delta = _read_json(root / delta_path)
    state_summary = _read_json(root / state_path)

    old_build = int(old_identity["steam"]["buildid"])
    new_build = int(new_identity["build_id"])
    if new_build != CURRENT_BUILD_ID:
        raise SourceValidationError(
            "unexpected_current_build",
            f"expected Build {CURRENT_BUILD_ID}, got {new_build}",
        )

    records: list[CatalogRecord] = []
    old_delta = delta["old_build"]
    new_delta = delta["new_build"]
    records.append(
        _record(
            short_kind="build",
            kind="fj_build_snapshot",
            build_id=old_build,
            source_id=str(old_build),
            label=f"From Jianghu {old_delta.get('game_version', 'unknown')} (Build {old_build})",
            source_path=old_identity_path,
            source_sha256=verified[old_identity_path],
            source_schema=str(old_identity["schema"]),
            ordinal=1,
            classification="build_snapshot",
            evidence_level="observed",
            record_status="historical",
            claim_boundary="Preserved static Build identity; no runtime claim.",
            specific={
                "fj_game_version": old_delta.get("game_version"),
                "fj_steam_app_id": int(old_identity["steam"]["appid"]),
                "fj_depot_id": int(old_identity["steam"]["depot"]),
                "fj_depot_manifest": str(old_identity["steam"]["depot_manifest"]),
                "fj_depot_file_count": int(old_identity["depot_sized_candidate"]["file_count"]),
                "fj_depot_bytes": int(old_identity["depot_sized_candidate"]["total_bytes"]),
                "fj_baseline_path": str(root / "baseline" / "FromJianghu"),
                "fj_appmanifest_sha256": str(old_identity["steam"]["appmanifest_sha256"]),
            },
        )
    )
    records.append(
        _record(
            short_kind="build",
            kind="fj_build_snapshot",
            build_id=new_build,
            source_id=str(new_build),
            label=f"From Jianghu {new_delta.get('game_version', 'unknown')} (Build {new_build})",
            source_path=new_identity_path,
            source_sha256=verified[new_identity_path],
            source_schema=str(new_identity["schema"]),
            ordinal=2,
            classification="build_snapshot",
            evidence_level="observed",
            record_status="current",
            claim_boundary="Preserved static Build identity; no runtime claim.",
            specific={
                "fj_game_version": new_delta.get("game_version"),
                "fj_steam_app_id": int(new_identity["appid"]),
                "fj_depot_id": int(new_identity["depot_id"]),
                "fj_depot_manifest": str(new_identity["depot_manifest"]),
                "fj_depot_file_count": _optional_int(new_delta.get("depot_file_count")),
                "fj_depot_bytes": int(new_identity["size_on_disk"]),
                "fj_baseline_path": str(new_identity["baseline_root"]),
                "fj_appmanifest_sha256": str(new_identity["appmanifest_sha256"]),
            },
        )
    )

    records.append(
        _record(
            short_kind="delta",
            kind="fj_build_delta",
            build_id=new_build,
            source_id=f"{old_build}->{new_build}",
            label=f"Build {old_build} → {new_build}",
            source_path=delta_path,
            source_sha256=verified[delta_path],
            source_schema=str(delta["schema"]),
            ordinal=1,
            classification="build_evolution",
            evidence_level="constructed_verified",
            record_status="current",
            claim_boundary="Static file/configuration delta; not runtime behavior.",
            specific={
                "fj_from_build_id": old_build,
                "fj_to_build_id": new_build,
                "fj_raw_depot_delta": delta["raw_depot_delta"],
                "fj_configuration_delta": delta["configuration_delta"],
                "fj_added_ids": {
                    "functions": delta.get("function_ids_added", []),
                    "triggers": delta.get("trigger_ids_added", []),
                },
                "fj_removed_ids": {
                    "functions": delta.get("function_ids_removed", []),
                    "triggers": delta.get("trigger_ids_removed", []),
                },
            },
        )
    )

    init_order = {
        name: index
        for index, name in enumerate(state_summary.get("model_initialization_order", []), 1)
    }
    model_rows = _read_csv(root / model_path)
    _require_unique(model_rows, "model_class", model_path)
    for ordinal, row in enumerate(sorted(model_rows, key=lambda item: item["model_class"].casefold()), 1):
        model_class = _required_text(row, "model_class", model_path)
        records.append(
            _record(
                short_kind="model",
                kind="fj_model_snapshot",
                build_id=new_build,
                source_id=model_class,
                label=model_class,
                source_path=model_path,
                source_sha256=verified[model_path],
                source_schema="fromjianghu.model-source-inventory/v1",
                ordinal=ordinal,
                classification="state_owner",
                evidence_level="constructed_verified",
                record_status="current",
                claim_boundary="Static lifecycle candidate; runtime instantiation remains unproven.",
                specific={
                    "fj_model_class": model_class,
                    "fj_model_name": row.get("model_name") or None,
                    "fj_game_data_type": row.get("game_data_type") or None,
                    "fj_user_data_type": row.get("user_data_type") or None,
                    "fj_has_load_game_data": _bool(row, "has_load_game_data", model_path),
                    "fj_has_load_user_data": _bool(row, "has_load_user_data", model_path),
                    "fj_has_after_load_user_data": _bool(row, "has_after_load_user_data", model_path),
                    "fj_has_save_game": _bool(row, "has_save_game", model_path),
                    "fj_save_call_count": _int(row, "save_call_count", model_path),
                    "fj_has_update": _bool(row, "has_update", model_path),
                    "fj_has_late_update": _bool(row, "has_late_update", model_path),
                    "fj_random_call_count": _int(row, "random_call_count", model_path),
                    "fj_event_listener_count": _int(row, "event_listener_count", model_path),
                    "fj_event_broadcast_count": _int(row, "event_broadcast_count", model_path),
                    "fj_dictionary_field_count": _int(row, "dictionary_field_count", model_path),
                    "fj_hashset_field_count": _int(row, "hashset_field_count", model_path),
                    "fj_initialization_order": init_order.get(model_class),
                },
            )
        )

    usage_rows = _read_csv(root / usage_path)
    _require_unique(usage_rows, "function_type", usage_path)
    usage = {row["function_type"]: row for row in usage_rows}
    function_payload = _read_json(root / function_path)
    function_map = function_payload.get("FunctionConfigMap")
    if not isinstance(function_map, dict):
        raise SourceValidationError("invalid_source_shape", "FunctionConfigMap must be an object")
    unknown_usage = sorted(set(usage) - set(function_map), key=str.casefold)
    if unknown_usage:
        raise SourceValidationError(
            "unknown_function_usage",
            "function usage contains undefined IDs",
            [{"function_id": item} for item in unknown_usage],
        )
    for ordinal, function_id in enumerate(sorted(function_map, key=lambda item: (item.casefold(), item)), 1):
        item = function_map[function_id]
        if not isinstance(item, dict):
            raise SourceValidationError("invalid_source_shape", f"function {function_id} is not an object")
        row = usage.get(function_id, {})
        parameters = [
            {
                "arg_type": str(param.get("ArgType", "")),
                "attributes": int(param.get("Attributes", 0)),
            }
            for param in item.get("ParamList", [])
        ]
        records.append(
            _record(
                short_kind="function",
                kind="fj_function_snapshot",
                build_id=new_build,
                source_id=function_id,
                label=f"{function_id} — {item.get('Name', '')}".rstrip(" —"),
                source_path=function_path,
                source_sha256=verified[function_path],
                source_schema="fromjianghu.function-config/v0.6.16",
                ordinal=ordinal,
                classification="declarative_function",
                evidence_level="observed_derived_decode",
                record_status="current",
                claim_boundary="Static declarative vocabulary/use; runtime reachability is unknown.",
                specific={
                    "fj_function_id": function_id,
                    "fj_function_enum_id": int(item["EnumId"]),
                    "fj_function_name": item.get("Name") or None,
                    "fj_return_type": item.get("ReturnType") or None,
                    "fj_function_catalog": item.get("Catalog") or None,
                    "fj_hidden_in_mod": bool(item.get("HideInMod", False)),
                    "fj_obsolete": bool(item.get("Obsolete", False)),
                    "fj_custom_event_evaluation": bool(item.get("UseCustomEventEvaluation", False)),
                    "fj_custom_event_registration": bool(item.get("UseCustomEventRegistration", False)),
                    "fj_function_parameters": parameters,
                    "fj_parameter_count": len(parameters),
                    "fj_usage_total": _int_default(row.get("total")),
                    "fj_usage_event": _int_default(row.get("event")),
                    "fj_usage_condition": _int_default(row.get("condition")),
                    "fj_usage_action": _int_default(row.get("action")),
                    "fj_usage_root": {
                        "event": _int_default(row.get("event_root")),
                        "condition": _int_default(row.get("condition_root")),
                        "action": _int_default(row.get("action_root")),
                    },
                    "fj_usage_nested": _int_default(row.get("nested")),
                },
            )
        )

    trigger_rows = _read_csv(root / trigger_path)
    _require_unique(trigger_rows, "trigger_id", trigger_path)
    for ordinal, row in enumerate(sorted(trigger_rows, key=lambda item: (item["trigger_id"].casefold(), item["trigger_id"])), 1):
        trigger_id = _required_text(row, "trigger_id", trigger_path)
        records.append(
            _record(
                short_kind="trigger",
                kind="fj_trigger_snapshot",
                build_id=new_build,
                source_id=trigger_id,
                label=trigger_id,
                source_path=trigger_path,
                source_sha256=verified[trigger_path],
                source_schema="fromjianghu.trigger-summary/v1",
                ordinal=ordinal,
                classification="declarative_trigger",
                evidence_level="constructed_verified",
                record_status="current",
                claim_boundary="Static trigger structure; runtime arrival and reachability are unknown.",
                specific={
                    "fj_trigger_id": trigger_id,
                    "fj_trigger_catalog": row.get("catalog") or None,
                    "fj_trigger_enabled": _bool(row, "enabled", trigger_path),
                    "fj_trigger_auto_disable": _bool(row, "auto_disable", trigger_path),
                    "fj_trigger_ignored": _bool(row, "ignored", trigger_path),
                    "fj_event_counts": {
                        "root": _int(row, "event_root_count", trigger_path),
                        "recursive": _int(row, "event_recursive_count", trigger_path),
                    },
                    "fj_condition_counts": {
                        "root": _int(row, "condition_root_count", trigger_path),
                        "recursive": _int(row, "condition_recursive_count", trigger_path),
                    },
                    "fj_action_counts": {
                        "root": _int(row, "action_root_count", trigger_path),
                        "recursive": _int(row, "action_recursive_count", trigger_path),
                    },
                    "fj_recursive_node_count": _int(row, "recursive_node_count", trigger_path),
                    "fj_max_function_depth": _int(row, "max_function_depth", trigger_path),
                },
            )
        )

    assets = _read_json(root / asset_path)
    if not isinstance(assets, dict):
        raise SourceValidationError("invalid_source_shape", "asset catalog root must be an object")
    folded_assets: dict[str, str] = {}
    for name in assets:
        folded = name.casefold()
        if folded in folded_assets:
            raise SourceValidationError(
                "casefold_source_id_collision",
                f"asset names collide after case-folding: {folded_assets[folded]} / {name}",
            )
        folded_assets[folded] = name
    for ordinal, name in enumerate(sorted(assets, key=lambda item: (item.casefold(), item)), 1):
        source_value = assets[name]
        if not isinstance(source_value, str):
            raise SourceValidationError("invalid_source_shape", f"asset value is not text: {name}")
        records.append(
            _record(
                short_kind="asset",
                kind="fj_asset_snapshot",
                build_id=new_build,
                source_id=name,
                label=name,
                source_path=asset_path,
                source_sha256=verified[asset_path],
                source_schema="fromjianghu.asset-catalog/v0.6.16",
                ordinal=ordinal,
                classification="logical_asset",
                evidence_level="observed_derived_decode",
                record_status="current",
                claim_boundary="Catalog-to-bundle filename mapping; Unity object rendering is untested.",
                specific={
                    "fj_asset_name": name,
                    "fj_asset_source_path": source_value,
                    "fj_asset_extension": Path(name).suffix.casefold(),
                    "fj_bundle_filename": name.casefold() + ".unity3d",
                },
            )
        )

    ledger_rows = _read_ledger(root / ledger_path)
    _require_unique(ledger_rows, "claim_id", ledger_path)
    for ordinal, row in enumerate(ledger_rows, 1):
        claim_id = row["claim_id"]
        number_match = re.fullmatch(r"FJ-(\d+)", claim_id)
        if number_match is None:
            raise SourceValidationError("invalid_claim_id", f"invalid claim ID: {claim_id}")
        claim_build = old_build if int(number_match.group(1)) <= 15 else new_build
        status = row["status"].casefold()
        records.append(
            _record(
                short_kind="claim",
                kind="fj_evidence_claim",
                build_id=claim_build,
                source_id=claim_id,
                label=f"{claim_id}: {row['claim'][:100]}",
                source_path=ledger_path,
                source_sha256=verified[ledger_path],
                source_schema="fromjianghu.evidence-ledger/v1",
                ordinal=ordinal,
                classification="evidence_claim",
                evidence_level=status,
                record_status="current" if claim_build == new_build else "historical",
                claim_boundary="Evidence-ledger claim; preserve its stated confidence and falsifier.",
                specific={
                    "fj_claim_id": claim_id,
                    "fj_claim_status": status,
                    "fj_claim_artifact": row["artifact"],
                    "fj_claim_method": row["method"],
                    "fj_claim_text": row["claim"],
                    "fj_claim_inference_falsifier": row["inference_falsifier"],
                    "fj_writeback": row["writeback"],
                },
            )
        )

    for summary_path, fallback_build, status in (
        (old_il_path, old_build, "historical"),
        (il_path, new_build, "current"),
    ):
        summary = _read_json(root / summary_path)
        anchor_build = int(summary.get("build_id", fallback_build))
        for ordinal, item in enumerate(summary.get("records", []), 1):
            label = _required_mapping_text(item, "label", summary_path)
            records.append(
                _record(
                    short_kind="il",
                    kind="fj_il_anchor",
                    build_id=anchor_build,
                    source_id=label,
                    label=f"Build {anchor_build}: {label}",
                    source_path=summary_path,
                    source_sha256=verified[summary_path],
                    source_schema=str(summary["schema"]),
                    ordinal=ordinal,
                    classification="il_provenance_anchor",
                    evidence_level="constructed_verified",
                    record_status=status,
                    claim_boundary="MethodDef-bound static IL witness; not runtime execution.",
                    specific={
                        "fj_anchor_label": label,
                        "fj_method_token": item.get("token"),
                        "fj_method_rid": _optional_int(item.get("rid")),
                        "fj_method_rva": item.get("rva"),
                        "fj_method_file_offset": item.get("file_offset"),
                        "fj_method_code_size": _optional_int(item.get("code_size")),
                        "fj_il_output_sha256": item.get("sha256"),
                        "fj_il_witnesses": item.get("witnesses", {}),
                    },
                )
            )

    records.sort(key=lambda record: record.entity_id)
    _validate_record_set(records, config.expected_entity_counts)
    fingerprint = _catalog_fingerprint(records, verified)
    records = [
        replace_current_build_catalog_metadata(
            record,
            fingerprint=fingerprint,
            entity_counts=dict(config.expected_entity_counts),
        )
        for record in records
    ]
    return CatalogSnapshot(
        records=tuple(records),
        entity_counts=dict(config.expected_entity_counts),
        fingerprint=fingerprint,
        source_hashes=verified,
    )


def _verify_source_hashes(root: Path, expected: Mapping[str, str]) -> dict[str, str]:
    if not expected:
        raise SourceValidationError("source_contract_empty", "source hash contract is empty")
    verified: dict[str, str] = {}
    root_prefix = str(root).casefold().rstrip("\\/") + "\\"
    for relative, expected_hash in sorted(expected.items()):
        normalized = relative.replace("\\", "/")
        path = (root / Path(normalized)).resolve()
        if not (str(path).casefold() == str(root).casefold() or str(path).casefold().startswith(root_prefix)):
            raise SourceValidationError("unsafe_source_path", f"source path escapes root: {relative}")
        if not path.is_file():
            raise SourceValidationError(
                "source_file_missing",
                f"source file not found: {relative}",
                [{"path": normalized}],
            )
        actual = _sha256(path)
        if actual != str(expected_hash).casefold():
            raise SourceValidationError(
                "source_hash_mismatch",
                f"source SHA-256 mismatch: {relative}",
                [{"path": normalized, "expected": str(expected_hash).casefold(), "actual": actual}],
            )
        verified[normalized] = actual
    return verified


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SourceValidationError("duplicate_json_key", f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicates)
    except SourceValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceValidationError("source_read_error", f"cannot read {path}: {exc}") from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SourceValidationError("source_read_error", f"cannot read {path}: {exc}") from exc


def _read_ledger(path: Path) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not re.match(r"^\|\s*FJ-\d+\s*\|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            raise SourceValidationError("invalid_ledger_row", f"ledger row has {len(cells)} cells")
        rows.append(dict(zip(
            ("claim_id", "status", "artifact", "method", "claim", "inference_falsifier", "writeback"),
            cells,
        )))
    if not rows:
        raise SourceValidationError("empty_ledger", "evidence ledger contains no FJ claims")
    return rows


def _record(
    *,
    short_kind: str,
    kind: str,
    build_id: int,
    source_id: str,
    label: str,
    source_path: str,
    source_sha256: str,
    source_schema: str,
    ordinal: int,
    classification: str,
    evidence_level: str,
    record_status: str,
    claim_boundary: str,
    specific: Mapping[str, Any],
) -> CatalogRecord:
    entity_id = stable_entity_id(short_kind, build_id, source_id)
    values = {
        "fj_record_key": source_id,
        "fj_classification": classification,
        "fj_source_build_id": build_id,
        "fj_source_schema": source_schema,
        "fj_source_path": source_path.replace("\\", "/"),
        "fj_source_sha256": source_sha256,
        "fj_evidence_level": evidence_level,
        "fj_claim_boundary": claim_boundary,
        "fj_record_status": record_status,
        "fj_runtime_status": "not_started",
        "fj_source_ordinal": ordinal,
        **{key: value for key, value in specific.items() if value is not None},
    }
    digest_payload = {"entity_id": entity_id, "kind": kind, "label": label, "values": values}
    values["fj_source_record_sha256"] = hashlib.sha256(_canonical(digest_payload)).hexdigest()
    return CatalogRecord(entity_id=entity_id, kind=kind, label=label, values=values)


def stable_entity_id(short_kind: str, build_id: int, source_id: str) -> str:
    if short_kind == "build":
        return f"fj-build-{build_id}"
    digest = hashlib.sha256(_canonical([short_kind, build_id, source_id])).hexdigest()[:20]
    return f"fj-{short_kind}-{build_id}-{digest}"


def replace_current_build_catalog_metadata(
    record: CatalogRecord,
    *,
    fingerprint: str,
    entity_counts: dict[str, int],
) -> CatalogRecord:
    if record.entity_id != f"fj-build-{CURRENT_BUILD_ID}":
        return record
    return CatalogRecord(
        entity_id=record.entity_id,
        kind=record.kind,
        label=record.label,
        values={
            **record.values,
            "fj_catalog_schema_version": SCHEMA_VERSION,
            "fj_catalog_fingerprint": fingerprint,
            "fj_entity_counts": entity_counts,
        },
    )


def _catalog_fingerprint(records: list[CatalogRecord], source_hashes: Mapping[str, str]) -> str:
    payload = {
        "schema": SCHEMA_VERSION,
        "source_hashes": dict(sorted(source_hashes.items())),
        "records": [
            {
                "entity_id": record.entity_id,
                "kind": record.kind,
                "label": record.label,
                "values": record.values,
            }
            for record in records
        ],
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validate_record_set(records: list[CatalogRecord], expected_counts: Mapping[str, int]) -> None:
    counts: dict[str, int] = {}
    ids: set[str] = set()
    for record in records:
        if record.entity_id in ids:
            raise SourceValidationError("duplicate_entity_id", f"duplicate entity ID: {record.entity_id}")
        ids.add(record.entity_id)
        counts[record.kind] = counts.get(record.kind, 0) + 1
    expected = dict(expected_counts)
    if counts != expected:
        raise SourceValidationError(
            "entity_count_mismatch",
            "classified entity counts differ from the source contract",
            [{"expected": expected, "actual": counts}],
        )


def _require_unique(rows: list[dict[str, str]], key: str, source_path: str) -> None:
    seen: set[str] = set()
    for row in rows:
        value = _required_text(row, key, source_path)
        if value in seen:
            raise SourceValidationError(
                "duplicate_source_id",
                f"duplicate {key} {value!r} in {source_path}",
            )
        seen.add(value)


def _required_text(row: Mapping[str, Any], key: str, source_path: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceValidationError("invalid_source_field", f"{source_path}: invalid {key}")
    return value.strip()


def _required_mapping_text(row: Mapping[str, Any], key: str, source_path: str) -> str:
    return _required_text(row, key, source_path)


def _bool(row: Mapping[str, Any], key: str, source_path: str) -> bool:
    value = str(row.get(key, "")).casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    raise SourceValidationError("invalid_source_field", f"{source_path}: invalid boolean {key}")


def _int(row: Mapping[str, Any], key: str, source_path: str) -> int:
    try:
        return int(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceValidationError("invalid_source_field", f"{source_path}: invalid integer {key}") from exc


def _int_default(value: Any) -> int:
    return 0 if value in (None, "") else int(value)


def _optional_int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)

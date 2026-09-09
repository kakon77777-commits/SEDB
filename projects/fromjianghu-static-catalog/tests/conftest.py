from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_SRC = PROJECT_DIR.parents[1] / "current" / "src"
for path in (str(PROJECT_DIR), str(SEDB_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source_fixture(tmp_path):
    root = tmp_path / "FromJianghu-research"
    _write_json(
        root / "evidence/source-identity.json",
        {
            "schema": "fromjianghu.source-identity/v1",
            "steam": {
                "appid": 1058770,
                "buildid": 24413414,
                "depot": 1058771,
                "depot_manifest": "old-manifest",
                "size_on_disk": 100,
                "appmanifest_sha256": "a" * 64,
            },
            "depot_sized_candidate": {"file_count": 8, "total_bytes": 100},
            "runtime_status": "not_run",
        },
    )
    _write_json(
        root / "evidence/build-25099888/source-identity.json",
        {
            "schema": "fromjianghu.source-identity/v2",
            "appid": 1058770,
            "build_id": 25099888,
            "depot_id": 1058771,
            "depot_manifest": "new-manifest",
            "size_on_disk": 200,
            "appmanifest_sha256": "b" * 64,
            "baseline_root": str(root / "baseline/build-25099888/FromJianghu"),
        },
    )
    _write_json(
        root / "evidence/build-25099888/build-delta-summary.json",
        {
            "schema": "fromjianghu.build-delta-summary/v1",
            "old_build": {"build_id": 24413414, "game_version": "0.6.15"},
            "new_build": {"build_id": 25099888, "game_version": "0.6.16"},
            "raw_depot_delta": {"added": 2, "removed": 0, "content_changed": 1},
            "configuration_delta": {"function_configs_old": 0, "function_configs_new": 1},
            "function_ids_added": ["FuncA"],
            "function_ids_removed": [],
            "trigger_ids_added": ["trigger-a"],
            "trigger_ids_removed": [],
        },
    )
    _write_json(
        root / "evidence/build-25099888/state-model-summary.json",
        {
            "schema": "fromjianghu.state-model-summary/v1",
            "model_class_count": 1,
            "function_config_count": 1,
            "trigger_count": 1,
            "logical_asset_count": 1,
        },
    )
    _write_csv(
        root / "evidence/build-25099888/model-source-inventory.csv",
        [
            "model_class", "source_file", "model_name", "game_data_type",
            "user_data_type", "has_load_game_data", "has_load_user_data",
            "has_after_load_user_data", "has_save_game", "save_call_count",
            "has_update", "has_late_update", "random_call_count",
            "event_listener_count", "event_broadcast_count",
            "dictionary_field_count", "hashset_field_count",
        ],
        [{
            "model_class": "ModelA", "source_file": "ModelA.cs",
            "model_name": "A", "game_data_type": "GameA",
            "user_data_type": "UserA", "has_load_game_data": "True",
            "has_load_user_data": "True", "has_after_load_user_data": "True",
            "has_save_game": "True", "save_call_count": "1",
            "has_update": "False", "has_late_update": "False",
            "random_call_count": "2", "event_listener_count": "1",
            "event_broadcast_count": "3", "dictionary_field_count": "4",
            "hashset_field_count": "1",
        }],
    )
    _write_csv(
        root / "evidence/build-25099888/trigger-function-usage.csv",
        [
            "function_type", "defined", "return_type", "catalog",
            "hidden_in_mod", "obsolete", "total", "event", "condition",
            "action", "event_root", "condition_root", "action_root", "nested",
        ],
        [{
            "function_type": "FuncA", "defined": "True", "return_type": "Null",
            "catalog": "Test", "hidden_in_mod": "False", "obsolete": "False",
            "total": "3", "event": "1", "condition": "1", "action": "1",
            "event_root": "1", "condition_root": "0", "action_root": "1",
            "nested": "1",
        }],
    )
    _write_csv(
        root / "evidence/build-25099888/trigger-summary.csv",
        [
            "trigger_id", "enabled", "auto_disable", "ignored", "catalog",
            "event_root_count", "event_recursive_count", "condition_root_count",
            "condition_recursive_count", "action_root_count",
            "action_recursive_count", "recursive_node_count", "max_function_depth",
        ],
        [{
            "trigger_id": "trigger-a", "enabled": "True",
            "auto_disable": "False", "ignored": "False", "catalog": "Test",
            "event_root_count": "1", "event_recursive_count": "1",
            "condition_root_count": "1", "condition_recursive_count": "2",
            "action_root_count": "1", "action_recursive_count": "3",
            "recursive_node_count": "6", "max_function_depth": "2",
        }],
    )
    _write_json(
        root / "derived/build-25099888/decrypted_game_data/Game/Function.json",
        {
            "FunctionConfigMap": {
                "FuncA": {
                    "EnumId": 7,
                    "Name": "功能甲",
                    "ReturnType": "Null",
                    "Catalog": "Test",
                    "HideInMod": False,
                    "Obsolete": False,
                    "UseCustomEventEvaluation": False,
                    "UseCustomEventRegistration": False,
                    "ParamList": [{"ArgType": "Value", "Attributes": 0}],
                }
            }
        },
    )
    _write_json(
        root / "derived/build-25099888/decrypted_config/filelistinfoE.json",
        {"AssetA.png": "/asseta.png"},
    )
    ledger = root / "toolchain/reports/evidence-ledger.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "| ID | Status | Artifact and fingerprint | Method / output | Claim | "
        "Inference, confidence, and falsifier | Write-back |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FJ-001 | observed | artifact-a | method-a | claim-a | falsifier-a | forbidden |\n",
        encoding="utf-8",
    )
    _write_json(
        root / "evidence/build-25099888/il-anchor-summary.json",
        {
            "schema": "fromjianghu.il-anchor-summary/v1",
            "assembly_csharp_sha256": "c" * 64,
            "records": [{
                "label": "AnchorA", "token": "0x06000001", "rid": 1,
                "rva": "0x00001000", "file_offset": "0x00000200",
                "code_size": 10, "sha256": "d" * 64,
                "witnesses": {"call-a": True},
            }],
        },
    )
    _write_json(
        root / "evidence/build-25099888/il-anchor-old-build-24413414-summary.json",
        {
            "schema": "fromjianghu.il-anchor-summary/v1",
            "build_id": 24413414,
            "assembly_csharp_sha256": "e" * 64,
            "records": [{
                "label": "OldAnchor", "token": "0x06000002", "rid": 2,
                "rva": "0x00002000", "file_offset": "0x00000400",
                "code_size": 20, "sha256": "f" * 64,
                "witnesses": {"call-old": True},
            }],
        },
    )

    files = sorted(path for path in root.rglob("*") if path.is_file())
    hashes = {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in files
    }
    expected_counts = {
        "fj_build_snapshot": 2,
        "fj_build_delta": 1,
        "fj_model_snapshot": 1,
        "fj_function_snapshot": 1,
        "fj_trigger_snapshot": 1,
        "fj_asset_snapshot": 1,
        "fj_evidence_claim": 1,
        "fj_il_anchor": 2,
    }
    contract = tmp_path / "fixture-contract.json"
    _write_json(
        contract,
        {"source_hashes": hashes, "expected_entity_counts": expected_counts},
    )
    return {
        "root": root,
        "db": tmp_path / "catalog.sqlite",
        "contract": contract,
        "hashes": hashes,
        "expected_counts": expected_counts,
    }

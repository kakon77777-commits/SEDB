from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest

from gameplay.character import analyze_character_coverage
from gameplay.combat import analyze_combat_progression
from gameplay.common import (
    Claim,
    GameplayDataError,
    StaticDataset,
    StaticRecord,
    load_verified_dataset,
)
from gameplay.events import (
    analyze_choice_consequence,
    analyze_event_network,
    analyze_time_pacing,
)
from gameplay.export import export_static_reports
from gameplay.relationships import analyze_relationship_routes
from cli import main
from config import ProjectConfig


def test_observed_claim_rejects_runtime_and_fun_upgrades():
    with pytest.raises(ValueError, match="runtime claim upgrade"):
        Claim(
            "OBSERVED",
            "This node is runtime-unreachable.",
            ("Event:100",),
        )
    with pytest.raises(ValueError, match="gameplay acceptance upgrade"):
        Claim(
            "OBSERVED",
            "The static graph proves fun.",
            ("Event.xlsx",),
        )


def test_claim_class_and_evidence_are_required():
    claim = Claim(
        "INFERRED",
        "Branches may converge quickly.",
        ("EventSelection", "EventResult"),
    )
    assert claim.claim_class == "INFERRED"
    with pytest.raises(ValueError, match="unsupported claim class"):
        Claim("CERTAIN", "invalid", ("source",))
    with pytest.raises(ValueError, match="evidence is required"):
        Claim("OBSERVED", "A measured count.", ())


def _record(record_id, kind, label, **values):
    return StaticRecord(record_id, kind, label, values)


def _edge(record_id, source, source_table, field, target, target_table, status="resolved"):
    return _record(
        record_id,
        "wanxiang_reference_edge_snapshot",
        f"{source_table}.{field}",
        edge_source_entity_id=source,
        edge_source_table=source_table,
        edge_source_field=field,
        edge_target_entity_id=target,
        edge_target_table=target_table,
        edge_resolution_status=status,
    )


def _static_dataset():
    records = (
        _record("char:1", "wanxiang_character_identity", "甲", name_zh="甲"),
        _record(
            "hero:1",
            "wanxiang_character_form_snapshot",
            "甲 [1]",
            hero_id=1,
            identity_entity_id="char:1",
            source_table="Hero",
            source_record_id=1,
            source_row_payload={"Desc": "完整背景"},
            skill_ids=[10],
            property_ids=[20],
        ),
        _record(
            "hero:2",
            "wanxiang_character_form_snapshot",
            "乙 [2]",
            hero_id=2,
            source_table="Hero",
            source_record_id=2,
            source_row_payload={"Desc": None},
            skill_ids=[],
            property_ids=[],
        ),
        _record(
            "asset:1",
            "wanxiang_visual_asset_snapshot",
            "Image 1",
            resource_numeric_id=1,
            extraction_status="EXTRACTED",
        ),
        _record("map:201", "wanxiang_table_row_snapshot", "Map 201", source_table="Map", source_record_id=201, source_row_payload={"Name": "江湖"}),
        _record("event:100", "wanxiang_table_row_snapshot", "Event 100", source_table="Event", source_record_id=100, source_row_payload={"ResultId": 500, "CostTime": 1, "Times": 1, "OnceInTurn": True, "Priority": 2, "Weight": 10, "Map": 201}),
        _record("event:101", "wanxiang_table_row_snapshot", "Event 101", source_table="Event", source_record_id=101, source_row_payload={"ResultId": 501, "CostTime": 2, "Times": -1, "OnceInTurn": False, "Priority": 1, "Weight": 5, "Map": 201}),
        _record("event:102", "wanxiang_table_row_snapshot", "Event 102", source_table="Event", source_record_id=102, source_row_payload={"ResultId": 501, "CostTime": 3, "Times": 2, "OnceInTurn": False, "Priority": 1, "Weight": 5, "Map": 201}),
        _record("result:500", "wanxiang_table_row_snapshot", "Result 500", source_table="EventResult", source_record_id=500, source_row_payload={}),
        _record("result:501", "wanxiang_table_row_snapshot", "Result 501", source_table="EventResult", source_record_id=501, source_row_payload={}),
        _record("dialog:300", "wanxiang_table_row_snapshot", "Dialog 300", source_table="EventDialog", source_record_id=300, source_row_payload={"Desc": "对话"}),
        _record("selection:200", "wanxiang_table_row_snapshot", "Selection 200", source_table="EventSelection", source_record_id=200, selection_options={"options": [{"slot": 0, "event_id": 101, "can_execute": True}, {"slot": 1, "event_id": 102, "can_execute": True}]}),
        _record("property:20", "wanxiang_table_row_snapshot", "Property 20", source_table="Property", source_record_id=20, source_row_payload={"Name": "好感"}),
        _record("relation:1", "wanxiang_table_row_snapshot", "Relation 1", source_table="Relation", source_record_id=1, source_row_payload={"RepeatDesc": "可重复"}, guide_steps={"guide_steps": [{"slot": 0, "event_ids": "101"}, {"slot": 1, "event_ids": "999"}]}),
        _record("skill:10", "wanxiang_table_row_snapshot", "Skill 10", source_table="Skill", source_record_id=10, source_row_payload={"Cost": 3, "LaunchRate": 50, "SuccessRate": 80, "FormulaId": 40, "EffectId0": 50}),
        _record("formula:40", "wanxiang_table_row_snapshot", "Formula 40", source_table="Formula", source_record_id=40, source_row_payload={"BaseValue": 10}),
        _record("effect:50", "wanxiang_table_row_snapshot", "Effect 50", source_table="Effect", source_record_id=50, source_row_payload={"Name": "剑光"}),
        _record("battle:60", "wanxiang_table_row_snapshot", "Battle 60", source_table="Battle", source_record_id=60, source_row_payload={"FixedHero0": 1, "SuccessEventId": 101, "FailedEventId": 102}),
        _record("difficulty:0", "wanxiang_table_row_snapshot", "Difficulty 0", source_table="Difficulty", source_record_id=0, source_row_payload={"Hp": 0, "Damage": 0, "DebuffResist": 0}),
        _record("difficulty:1", "wanxiang_table_row_snapshot", "Difficulty 1", source_table="Difficulty", source_record_id=1, source_row_payload={"Hp": 20, "Damage": 20, "DebuffResist": 0}),
        _edge("edge:1", "event:100", "Event", "LogicId", "dialog:300", "EventDialog"),
        _edge("edge:2", "selection:200", "EventSelection", "EventId0", "event:101", "Event"),
        _edge("edge:3", "selection:200", "EventSelection", "EventId1", "event:102", "Event"),
        _edge("edge:4", "relation:1", "Relation", "PropertyId", "property:20", "Property"),
        _edge("edge:5", "relation:1", "Relation", "GuidEvent0", "event:101", "Event"),
        _edge("edge:6", "relation:1", "Relation", "GuidEvent1", None, "Event", "missing_target"),
        _edge("edge:7", "skill:10", "Skill", "FormulaId", "formula:40", "Formula"),
        _edge("edge:8", "skill:10", "Skill", "EffectId0", "effect:50", "Effect"),
        _edge("edge:9", "battle:60", "Battle", "SuccessEventId", "event:101", "Event"),
        _edge("edge:10", "battle:60", "Battle", "FailedEventId", "event:102", "Event"),
    )
    return StaticDataset(
        build_id=25006280,
        catalog_fingerprint="F" * 64,
        rule_version="wanxiang-reference-rules/v1",
        records=records,
    )


def test_six_static_analyses_reconcile_hand_checked_fixture_metrics():
    dataset = _static_dataset()
    reports = (
        analyze_character_coverage(dataset),
        analyze_event_network(dataset),
        analyze_choice_consequence(dataset),
        analyze_time_pacing(dataset),
        analyze_relationship_routes(dataset),
        analyze_combat_progression(dataset),
    )

    by_name = {report["analysis_name"]: report for report in reports}
    assert by_name["character-coverage"]["metrics"]["forms"] == 2
    assert by_name["character-coverage"]["metrics"]["forms_with_description"] == 1
    assert by_name["character-coverage"]["metrics"]["forms_with_extracted_asset"] == 1
    assert by_name["character-coverage"]["metrics"]["forms_with_identity"] == 1
    assert by_name["character-coverage"]["metrics"]["duplicate_hero_ids"] == 0
    assert by_name["event-network"]["metrics"]["resolved_edges"] == 9
    assert by_name["event-network"]["metrics"]["missing_edges"] == 1
    assert by_name["event-network"]["metrics"]["event_graph_resolved_edges"] == 5
    assert by_name["event-network"]["details"]["typed_edges"]["Event.LogicId->EventDialog:resolved"] == 1
    assert by_name["choice-consequence"]["metrics"]["selections"] == 1
    assert by_name["choice-consequence"]["metrics"]["one_hop_result_convergence"] == 1
    assert by_name["choice-consequence"]["metrics"]["distinct_event_destinations"] == 2
    assert by_name["time-pacing"]["metrics"]["events"] == 3
    assert by_name["time-pacing"]["metrics"]["cost_time_average"] == 2.0
    assert by_name["time-pacing"]["details"]["priority_distribution"] == {"1": 2, "2": 1}
    assert by_name["relationship-routes"]["metrics"]["routes"] == 1
    assert by_name["relationship-routes"]["metrics"]["missing_event_targets"] == 1
    assert by_name["relationship-routes"]["metrics"]["resolved_property_targets"] == 1
    assert by_name["relationship-routes"]["metrics"]["resolved_event_targets"] == 1
    assert by_name["combat-progression"]["metrics"]["skills"] == 1
    assert by_name["combat-progression"]["metrics"]["battles"] == 1
    assert by_name["combat-progression"]["metrics"]["difficulty_profiles"] == 2
    assert by_name["combat-progression"]["metrics"]["resolved_formula_links"] == 1
    assert by_name["combat-progression"]["metrics"]["resolved_effect_links"] == 1
    for report in reports:
        assert {claim.claim_class for claim in report["claims"]} == {
            "OBSERVED",
            "INFERRED",
            "UNKNOWN",
            "FALSIFYING_TEST",
        }
        assert json.loads(
            json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True)
        ) == report["metrics"]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _materialize_verified_database(tmp_path):
    dataset = _static_dataset()
    database = tmp_path / "catalog.sqlite"
    namespace = "wanxiang_character_canon"
    rows = []
    table_counts = {}
    for record in dataset.records:
        values = dict(record.values)
        values["source_build_id"] = dataset.build_id
        if values.get("source_table"):
            values.setdefault("source_row_sha256", "A" * 64)
            table = values["source_table"]
            table_counts[table] = table_counts.get(table, 0) + 1
        if record.kind == "wanxiang_reference_edge_snapshot":
            values["edge_rule_version"] = dataset.rule_version
        rows.append((record.record_id, record.kind, record.label, values))

    build_values = {
        "source_build_id": dataset.build_id,
        "catalog_source_fingerprint": "C" * 64,
        "catalog_table_counts": table_counts,
        "catalog_total_rows": sum(table_counts.values()),
    }
    rows.append(
        (
            f"wx-build-{dataset.build_id}",
            "wanxiang_build_snapshot",
            f"Wanxiang Build {dataset.build_id}",
            build_values,
        )
    )
    field_keys = sorted({key for *_, values in rows for key in values})
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE entities(id TEXT PRIMARY KEY, kind TEXT, label TEXT);
            CREATE TABLE fields(id TEXT PRIMARY KEY, key TEXT, namespace TEXT);
            CREATE TABLE cells(
                entity_id TEXT,
                field_id TEXT,
                value_json TEXT,
                source TEXT,
                PRIMARY KEY(entity_id, field_id)
            );
            CREATE TABLE task_views(id TEXT PRIMARY KEY, name TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO fields(id,key,namespace) VALUES(?,?,?)",
            [(f"field:{key}", key, namespace) for key in field_keys],
        )
        connection.executemany(
            "INSERT INTO entities(id,kind,label) VALUES(?,?,?)",
            [(entity_id, kind, label) for entity_id, kind, label, _ in rows],
        )
        connection.executemany(
            "INSERT INTO cells(entity_id,field_id,value_json,source) VALUES(?,?,?,?)",
            [
                (
                    entity_id,
                    f"field:{key}",
                    json.dumps(value, ensure_ascii=False, sort_keys=True),
                    "test:verified-catalog",
                )
                for entity_id, _, _, values in rows
                for key, value in values.items()
            ],
        )

    with sqlite3.connect(database) as connection:
        counts = {
            "entities": connection.execute(
                "SELECT COUNT(*) FROM entities"
            ).fetchone()[0],
            "cells": connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0],
            "fields": connection.execute("SELECT COUNT(*) FROM fields").fetchone()[0],
            "views": connection.execute(
                "SELECT COUNT(*) FROM task_views"
            ).fetchone()[0],
        }
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(
        json.dumps(
            {
                "schema": "wanxiang-full-catalog-acceptance/v1",
                "status": "FULL_STATIC_DATABASE_ACCEPTED",
                "build_id": dataset.build_id,
                "source": {
                    "catalog_fingerprint": "F" * 64,
                    "reference_rule_version": dataset.rule_version,
                    "tables": len(table_counts),
                    "source_rows": sum(table_counts.values()),
                    "event_dialog_rows": table_counts["EventDialog"],
                },
                "database": {
                    "path": str(database.resolve()),
                    "sha256": _sha256(database),
                    **counts,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config = ProjectConfig(
        source_root=tmp_path / "source",
        database_path=database,
        build_id=dataset.build_id,
        namespace=namespace,
        expected_entity_counts={},
    )
    return config, acceptance, table_counts


def test_verified_loader_reconciles_integrity_fingerprint_and_source_counts(tmp_path):
    config, acceptance, table_counts = _materialize_verified_database(tmp_path)
    before = _sha256(config.database_path)

    dataset = load_verified_dataset(config, acceptance_path=acceptance)

    assert dataset.build_id == 25006280
    assert dataset.catalog_fingerprint == "F" * 64
    assert dataset.catalog_source_fingerprint == "C" * 64
    assert dataset.database_sha256 == before
    assert dataset.source_table_counts == table_counts
    assert len(dataset.records) == len(_static_dataset().records)
    assert _sha256(config.database_path) == before


def test_verified_loader_rejects_accepted_source_count_drift(tmp_path):
    config, acceptance, _ = _materialize_verified_database(tmp_path)
    payload = json.loads(acceptance.read_text(encoding="utf-8"))
    payload["source"]["source_rows"] += 1
    acceptance.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(GameplayDataError, match="accepted source row count") as exc:
        load_verified_dataset(config, acceptance_path=acceptance)

    assert exc.value.reason_code == "accepted_source_count_mismatch"


def test_export_writes_six_json_six_markdown_and_hashed_manifest_deterministically(
    tmp_path,
):
    dataset = replace(
        _static_dataset(),
        catalog_source_fingerprint="C" * 64,
        database_sha256="D" * 64,
        database_path=str(tmp_path / "catalog.sqlite"),
        source_table_counts={"Event": 3, "Hero": 2},
        accepted_at="2026-08-30T21:53:42+08:00",
        source_root=str(tmp_path / "research"),
        all_excel_root=str(tmp_path / "research" / "baseline" / "AllExcel"),
    )
    output_root = tmp_path / "reports"

    first = export_static_reports(dataset, output_root)
    second = export_static_reports(dataset, output_root)

    assert first.sha256_by_path == second.sha256_by_path
    assert first.catalog_fingerprint == "F" * 64
    assert len(first.report_paths) == 12
    assert len(list(output_root.glob("*.md"))) == 6
    assert len(
        [path for path in output_root.glob("*.json") if path.name != "manifest.json"]
    ) == 6
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "wanxiang-static-gameplay-manifest/v1"
    assert len(manifest["reports"]) == 6
    assert len(manifest["sha256_by_path"]) == 12
    for relative_path, expected_sha in manifest["sha256_by_path"].items():
        assert _sha256(output_root / relative_path) == expected_sha

    report = json.loads(
        (output_root / "character-coverage.json").read_text(encoding="utf-8")
    )
    assert report["build_id"] == 25006280
    assert report["database"]["sha256"] == "D" * 64
    assert report["catalog"]["fingerprint"] == "F" * 64
    assert report["reference_rule_version"] == "wanxiang-reference-rules/v1"
    assert {claim["claim_class"] for claim in report["claims"]} == {
        "OBSERVED",
        "INFERRED",
        "UNKNOWN",
        "FALSIFYING_TEST",
    }
    markdown = (output_root / "character-coverage.md").read_text(encoding="utf-8")
    for claim_class in ("OBSERVED", "INFERRED", "UNKNOWN", "FALSIFYING_TEST"):
        assert f"## {claim_class}" in markdown
    assert "Source tables" in markdown
    assert "Database SHA-256" in markdown
    assert "Immutable AllExcel root" in markdown


def test_gameplay_report_cli_returns_reconciled_report_hashes(tmp_path, capsys):
    config, acceptance, _ = _materialize_verified_database(tmp_path)
    output_root = tmp_path / "cli-reports"

    exit_code = main(
        [
            "--source-root",
            str(config.source_root),
            "--db",
            str(config.database_path),
            "--acceptance",
            str(acceptance),
            "gameplay-report",
            "all",
            "--output-root",
            str(output_root),
        ],
        base_config=config,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "created"
    assert payload["report_count"] == 6
    assert payload["file_count"] == 12
    assert payload["catalog_fingerprint"] == "F" * 64
    for relative_path, expected_sha in payload["sha256_by_path"].items():
        assert _sha256(output_root / relative_path) == expected_sha

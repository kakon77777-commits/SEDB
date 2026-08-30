from __future__ import annotations

import hashlib
import json
import os
from collections import Counter

import pytest

from catalog_fixtures import build_catalog_fixture
from catalog_source import (
    CatalogRow,
    CatalogRows,
    compose_full_selection,
    compose_full_catalog,
    load_catalog_rows,
)
from source import SnapshotSelection, SourceEntity
from reference_rules import EVENT_LOGIC_TARGETS, resolve_event_logic_target
from reference_graph import build_reference_edges, normalize_repeated_operations


def test_event_logic_type_uses_documented_enum_only():
    assert EVENT_LOGIC_TARGETS == {
        0: "EventDialog",
        1: "EventSelection",
        2: "EventNormal",
        3: "Battle",
        4: "EventPuzzle",
        5: "EventDice",
    }
    assert resolve_event_logic_target(0) == "EventDialog"
    assert resolve_event_logic_target(5) == "EventDice"
    assert resolve_event_logic_target(99) is None
    assert resolve_event_logic_target(None) is None


def test_repeated_operation_tables_normalize_ordered_non_sentinel_slots():
    condition = normalize_repeated_operations(
        "Condition",
        {
            "ConditionType0": 4,
            "ConditionSubType0": -1,
            "ConditionOpt0": 0,
            "ConditionValue0": 9999,
            "ConditionType1": -1,
            "ConditionSubType1": -1,
            "ConditionOpt1": -1,
            "ConditionValue1": -1,
            "OR": True,
        },
    )
    result = normalize_repeated_operations(
        "EventResult",
        {
            "ResultType0": 2,
            "ResultSubType0": 3,
            "ResultOpt0": 1,
            "Result0Value0": 10,
            "Result1Value0": 20,
            "ConditionId0": 99,
            "TalentType0": None,
            "ResultType1": -1,
        },
    )
    selection = normalize_repeated_operations(
        "EventSelection",
        {
            "Condition0": 10,
            "Selection0": "选择甲",
            "EventId0": 100,
            "CanExec0": True,
            "TipText0": "提示甲",
            "SelectionTw0": "選擇甲",
            "TipTextTw0": "提示甲",
            "Condition16": 16,
            "Selection16": "选择十七",
            "EventId16": 116,
            "CanExec16": False,
            "TipText16": None,
            "SelectionTw16": "選擇十七",
            "TipTextTw16": None,
            "Condition1": -1,
            "EventId1": -1,
        },
    )
    relation = normalize_repeated_operations(
        "Relation",
        {
            "GuidDesc0": "第一步",
            "GuidDescTw0": "第一步",
            "GuidEvent0": "100&101",
            "GuidDesc1": None,
            "GuidEvent1": -1,
        },
    )

    assert condition == {
        "conditions": [
            {
                "slot": 0,
                "type": 4,
                "subtype": -1,
                "operator": 0,
                "value": 9999,
            }
        ],
        "or": True,
    }
    assert result == {
        "results": [
            {
                "slot": 0,
                "type": 2,
                "subtype": 3,
                "operator": 1,
                "value0": 10,
                "value1": 20,
                "condition_id": 99,
                "talent_type": None,
            }
        ]
    }
    assert [item["slot"] for item in selection["options"]] == [0, 16]
    assert selection["options"][1]["condition_id"] == 16
    assert selection["options"][1]["event_id"] == 116
    assert relation == {
        "guide_steps": [
            {
                "slot": 0,
                "description": "第一步",
                "description_tw": "第一步",
                "event_ids": "100&101",
            }
        ]
    }
    assert normalize_repeated_operations("Event", {"Id": 1}) == {}


def _row(table, source_id, payload, row_number):
    values = {"Id": source_id, **payload}
    payload_json = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return CatalogRow(
        table=table,
        source_id=source_id,
        row_number=row_number,
        workbook_path=f"wanxiang/ModDocs/AllExcel/{table}.xlsx",
        workbook_sha256=(table[0].encode().hex().upper() * 64)[:64],
        payload=values,
        payload_json=payload_json,
        source_row_sha256=hashlib.sha256(payload_json.encode("utf-8")).hexdigest().upper(),
    )


def _edge_fixture_rows():
    rows = (
        _row("Birth", 101, {"Name": "荆湘"}, 5),
        _row(
            "Hero",
            1001,
            {
                "Name": "万轻舟",
                "Type": 0,
                "Birth": 101,
                "ParentId": -1,
                "SkillId0": 10,
                "SkillId1": -1,
                "SkillId2": None,
                "SkillId3": None,
                "Property0": 20,
                "Property1": -1,
                "Property2": None,
                "Property3": None,
                "Property4": None,
                "Property5": None,
                "ExtraHeroId": -1,
                "StoryId": 500,
            },
            6,
        ),
        _row("Property", 20, {"Name": "好感"}, 5),
        _row(
            "Skill",
            10,
            {
                "Name": "剑法",
                "conditionId": 30,
                "FormulaId": 40,
                "EffectId0": 50,
                "EffectId1": -1,
                "ExtraFormulaId": -1,
                "ExtraEffectId0": -1,
                "ExtraEffectId1": -1,
            },
            5,
        ),
        _row("Condition", 30, {"ConditionType0": 4}, 5),
        _row("SkillCondition", 30, {"Type": 4}, 5),
        _row("Formula", 40, {"BaseValue": 1}, 5),
        _row("Effect", 50, {"Name": "剑光"}, 5),
        _row("Map", 201, {"Name": "江湖", "ParentId": -1}, 5),
        _row(
            "EventResult",
            60,
            {"ConditionId0": 30, "ConditionId1": -1},
            5,
        ),
        _row(
            "EventDialog",
            70,
            {"Name": "万轻舟", "NextDialogId": -1, "NextEventId": 100},
            5,
        ),
        _row(
            "Event",
            100,
            {
                "Name": "相遇",
                "Map": 201,
                "ConditionId": 30,
                "ResultId": 60,
                "LogicType": 0,
                "LogicId": 70,
            },
            5,
        ),
        _row(
            "Relation",
            1,
            {
                "Name": "万轻舟",
                "Birth": 101,
                "PropertyId": 20,
                "GuidEvent0": "100&999",
            },
            5,
        ),
    )
    return CatalogRows(
        table_counts={},
        source_hashes={},
        rows=rows,
        runtime_candidates=(),
        source_fingerprint="F" * 64,
    )


def test_direct_reference_graph_is_resolved_without_name_inference():
    edges = build_reference_edges(25006280, _edge_fixture_rows())

    assert len(edges) == 17
    assert len({edge.entity_id for edge in edges}) == 17
    assert [edge.entity_id for edge in edges] == sorted(
        edge.entity_id for edge in edges
    )
    statuses = [edge.values["edge_resolution_status"] for edge in edges]
    assert statuses.count("resolved") == 15
    assert statuses.count("missing_target") == 2
    assert statuses.count("unknown_semantics") == 0
    missing = {
        (edge.values["edge_target_table"], edge.values["edge_target_source_id"])
        for edge in edges
        if edge.values["edge_resolution_status"] == "missing_target"
    }
    assert missing == {("Story", 500), ("Event", "999")}
    guide_edges = [
        edge for edge in edges if edge.values["edge_source_field"] == "GuidEvent0"
    ]
    assert [edge.values["edge_slot"] for edge in guide_edges] == [0, 1]
    assert edges == build_reference_edges(25006280, _edge_fixture_rows())


def test_unknown_event_logic_emits_unknown_semantics_and_sentinels_emit_nothing():
    catalog = CatalogRows(
        table_counts={},
        source_hashes={},
        rows=(
            _row(
                "Event",
                200,
                {
                    "Map": -1,
                    "ConditionId": "nil",
                    "ResultId": None,
                    "LogicType": 99,
                    "LogicId": 888,
                },
                5,
            ),
        ),
        runtime_candidates=(),
        source_fingerprint="F" * 64,
    )

    edges = build_reference_edges(25006280, catalog)

    assert len(edges) == 1
    assert edges[0].values["edge_resolution_status"] == "unknown_semantics"
    assert edges[0].values["edge_source_field"] == "LogicId"
    assert "edge_target_entity_id" not in edges[0].values


def test_full_selection_includes_deterministic_reference_edges(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    catalog = load_catalog_rows(fixture.contract)
    build = SourceEntity(
        entity_id="wx-build-25006280",
        kind="wanxiang_build_snapshot",
        label="Wanxiang Build 25006280",
        values={"source_build_id": 25006280, "source_sha256": "WAVE1"},
        cell_source="wanxiang:wave1-build",
    )
    form = SourceEntity(
        entity_id="wx-build-25006280-hero-1001",
        kind="wanxiang_character_form_snapshot",
        label="万轻舟 [1001]",
        values={
            "source_build_id": 25006280,
            "source_row": 5,
            "hero_id": 1001,
            "id_name": "万轻舟1",
            "name_zh": "万轻舟",
            "name_tw": "萬輕舟",
            "title": "南天玉柱",
            "title_tw": "南天玉柱",
            "birth_id": 101,
            "faction_text": "1002",
            "image_path": "Roles/Image/1001",
            "card_path": "Roles/Card/1001",
            "parent_id": -1,
        },
        cell_source="wanxiang:wave1-form",
    )
    wave1 = SnapshotSelection(
        build_id=25006280,
        source_hashes={"wave1": "A" * 64},
        entities=(build, form),
        counts={"wanxiang_build_snapshot": 1, "wanxiang_character_form_snapshot": 1},
        scope_name="wave1",
        owned_keys=frozenset(key for entity in (build, form) for key in entity.values),
        scope_entity_kinds=frozenset({build.kind, form.kind}),
    )

    full = compose_full_selection(wave1, catalog, include_edges=True)

    assert full.counts["wanxiang_reference_edge_snapshot"] == 7
    assert len(full.entities) == 14
    assert full == compose_full_selection(wave1, catalog, include_edges=True)


def test_full_selection_materializes_normalized_operation_blocks():
    rows = (
        _row(
            "Condition",
            1,
            {
                "ConditionType0": 4,
                "ConditionSubType0": -1,
                "ConditionOpt0": 0,
                "ConditionValue0": 9999,
                "OR": False,
            },
            5,
        ),
        _row(
            "EventResult",
            2,
            {
                "ResultType0": 2,
                "ResultSubType0": 3,
                "ResultOpt0": 1,
                "Result0Value0": 10,
                "Result1Value0": 20,
                "ConditionId0": 1,
            },
            5,
        ),
        _row(
            "EventSelection",
            3,
            {
                "Condition0": 1,
                "Selection0": "选择",
                "EventId0": 100,
                "CanExec0": True,
            },
            5,
        ),
        _row(
            "Relation",
            4,
            {"GuidDesc0": "第一步", "GuidEvent0": "100&101"},
            5,
        ),
    )
    catalog = CatalogRows(
        table_counts={row.table: 1 for row in rows},
        source_hashes={"manifest:current-verification.manifest.json": "M" * 64},
        rows=rows,
        runtime_candidates=(),
        source_fingerprint="F" * 64,
    )
    build = SourceEntity(
        entity_id="wx-build-25006280",
        kind="wanxiang_build_snapshot",
        label="Wanxiang Build 25006280",
        values={"source_build_id": 25006280},
        cell_source="wave1",
    )
    wave1 = SnapshotSelection(
        build_id=25006280,
        source_hashes={},
        entities=(build,),
        counts={"wanxiang_build_snapshot": 1},
        owned_keys=frozenset({"source_build_id"}),
        scope_entity_kinds=frozenset({"wanxiang_build_snapshot"}),
    )

    full = compose_full_selection(wave1, catalog, include_edges=False)
    by_table = {
        entity.values["source_table"]: entity
        for entity in full.entities
        if "source_table" in entity.values
    }

    assert by_table["Condition"].values["condition_operations"]["conditions"]
    assert by_table["EventResult"].values["event_result_operations"]["results"]
    assert by_table["EventSelection"].values["selection_options"]["options"]
    assert by_table["Relation"].values["guide_steps"]["guide_steps"]


@pytest.mark.skipif(
    os.environ.get("WANXIANG_CANON_LIVE") != "1",
    reason="set WANXIANG_CANON_LIVE=1 for real reference graph acceptance",
)
def test_real_reference_graph_count_and_full_selection_are_exact():
    from catalog_config import default_catalog_contract
    from config import default_config

    catalog = load_catalog_rows(default_catalog_contract())
    first = build_reference_edges(25006280, catalog)
    second = build_reference_edges(25006280, catalog)
    full = compose_full_catalog(default_config(), include_edges=True)

    assert first == second
    assert len(first) == 40075
    assert Counter(
        edge.values["edge_resolution_status"] for edge in first
    ) == {"resolved": 31117, "missing_target": 8958}
    assert sum(
        1
        for edge in first
        if edge.values["edge_rule_id"].startswith("event.logic-type-")
    ) == 3589
    assert full.counts["wanxiang_reference_edge_snapshot"] == 40075
    assert len(full.entities) == 71753
    assert sum(
        entity.values.get("source_table") == "Condition"
        and "condition_operations" in entity.values
        for entity in full.entities
    ) == 2924
    assert sum(
        entity.values.get("source_table") == "EventResult"
        and "event_result_operations" in entity.values
        for entity in full.entities
    ) == 1627
    assert sum(
        entity.values.get("source_table") == "EventSelection"
        and "selection_options" in entity.values
        for entity in full.entities
    ) == 155
    assert sum(
        entity.values.get("source_table") == "Relation"
        and "guide_steps" in entity.values
        for entity in full.entities
    ) == 50

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

import pytest

from catalog_identity import table_row_entity_id
from catalog_fixtures import build_catalog_fixture, write_xlsx_fixture
from catalog_source import (
    CatalogSourceError,
    compose_catalog_entities,
    compose_full_selection,
    load_catalog_rows,
)
from source import SnapshotSelection, SourceEntity


def test_row_ids_preserve_scalar_type_and_null_row_identity():
    numeric = table_row_entity_id(
        25006280,
        "Event",
        1,
        row_number=5,
        workbook_sha256="A" * 64,
    )
    text = table_row_entity_id(
        25006280,
        "Event",
        "1",
        row_number=5,
        workbook_sha256="A" * 64,
    )
    null = table_row_entity_id(
        25006280,
        "Formula",
        None,
        row_number=792,
        workbook_sha256="B" * 64,
    )

    assert numeric != text
    assert null.startswith("wx-build-25006280-row-formula-r792-")
    assert numeric == table_row_entity_id(
        25006280,
        "event",
        1,
        row_number=99,
        workbook_sha256="C" * 64,
    )
    assert null != table_row_entity_id(
        25006280,
        "Formula",
        None,
        row_number=793,
        workbook_sha256="B" * 64,
    )


def test_source_entity_uses_per_cell_source_before_fallback():
    entity = SourceEntity(
        entity_id="entity-1",
        kind="fixture",
        label="Fixture",
        values={"old": 1, "new": 2},
        cell_source="fixture:default",
        cell_sources={"new": "fixture:Hero.xlsx#row=5"},
    )

    assert entity.source_for("old") == "fixture:default"
    assert entity.source_for("new") == "fixture:Hero.xlsx#row=5"


def test_snapshot_selection_carries_explicit_ownership_scope():
    selection = SnapshotSelection(
        build_id=25006280,
        source_hashes={},
        entities=(),
        counts={},
        scope_name="full_catalog",
        owned_keys=frozenset({"source_row_payload"}),
        scope_entity_kinds=frozenset({"wanxiang_table_row_snapshot"}),
    )

    assert selection.scope_name == "full_catalog"
    assert selection.owned_keys == frozenset({"source_row_payload"})
    assert selection.scope_entity_kinds == frozenset(
        {"wanxiang_table_row_snapshot"}
    )


def test_manifest_gated_catalog_rows_preserve_complete_payload(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in fixture.root.rglob("*")
        if path.is_file()
    }

    catalog = load_catalog_rows(fixture.contract)

    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in fixture.root.rglob("*")
        if path.is_file()
    }
    assert catalog.table_counts == {"Hero": 3, "EventDialog": 2, "Formula": 1}
    assert len(catalog.rows) == 6
    dialog = next(row for row in catalog.rows if row.table == "EventDialog")
    assert dialog.payload["Desc"] == "完整对话甲"
    assert dialog.source_row_sha256
    assert len(catalog.source_fingerprint) == 64
    assert len(catalog.source_hashes) == 4
    assert catalog.runtime_candidates == ()
    assert before == after


def _rewrite_manifest(fixture, payload):
    fixture.contract.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return replace(
        fixture.contract,
        manifest_sha256=hashlib.sha256(
            fixture.contract.manifest_path.read_bytes()
        ).hexdigest().upper(),
    )


def _refresh_workbook_record(fixture, table):
    payload = json.loads(
        fixture.contract.manifest_path.read_text(encoding="utf-8")
    )
    workbook = fixture.contract.workbook_path(table)
    data = workbook.read_bytes()
    member = fixture.contract.manifest_member(table)
    record = next(
        record for record in payload["records"] if record["relativePath"] == member
    )
    record["length"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest().upper()
    return _rewrite_manifest(fixture, payload)


def test_source_manifest_hash_drift_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    fixture.contract.manifest_path.write_bytes(
        fixture.contract.manifest_path.read_bytes() + b"\n"
    )

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(fixture.contract)

    assert error.value.reason_code == "source_manifest_hash_mismatch"


def test_unsupported_manifest_schema_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    payload = json.loads(fixture.contract.manifest_path.read_text(encoding="utf-8"))
    payload["schema"] = "unsupported/v9"
    contract = _rewrite_manifest(fixture, payload)

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "source_manifest_schema_unsupported"


def test_missing_manifest_member_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    payload = json.loads(fixture.contract.manifest_path.read_text(encoding="utf-8"))
    payload["records"] = [
        record
        for record in payload["records"]
        if record["relativePath"] != fixture.contract.manifest_member("Formula")
    ]
    contract = _rewrite_manifest(fixture, payload)

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "manifest_member_missing"


def test_duplicate_manifest_member_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    payload = json.loads(fixture.contract.manifest_path.read_text(encoding="utf-8"))
    payload["records"].append(dict(payload["records"][0]))
    contract = _rewrite_manifest(fixture, payload)

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "source_manifest_duplicate_member"


def test_workbook_hash_drift_is_reason_coded_before_parse(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    fixture.contract.workbook_path("Hero").write_bytes(
        fixture.contract.workbook_path("Hero").read_bytes() + b"drift"
    )

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(fixture.contract)

    assert error.value.reason_code == "workbook_hash_mismatch"


def test_table_count_mismatch_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    headers = ("Id", "Name", "Desc", "DescTw", "NextDialogId", "NextEventId")
    write_xlsx_fixture(
        fixture.contract.workbook_path("EventDialog"),
        relationship_target="worksheets/sheet1.xml",
        headers=headers,
        metadata_rows=(
            tuple("STRING" for _ in headers),
            tuple(None for _ in headers),
            tuple(f"{header} description" for header in headers),
        ),
        data_rows=((10, "万轻舟", "只剩一行", "只剩一行", -1, -1),),
    )
    contract = _refresh_workbook_record(fixture, "EventDialog")

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "table_count_mismatch"


def test_duplicate_non_null_source_id_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    headers = (
        "Id", "IdName", "Name", "Birth", "Type", "Title",
        "CardPath", "Image", "ParentId",
    )
    write_xlsx_fixture(
        fixture.contract.workbook_path("Hero"),
        relationship_target="worksheets/sheet1.xml",
        headers=headers,
        metadata_rows=(
            tuple("STRING" for _ in headers),
            tuple(None for _ in headers),
            tuple(f"{header} description" for header in headers),
        ),
        data_rows=(
            (1001, "万轻舟1", "万轻舟", 101, 0, "甲", None, None, -1),
            (1001, "万轻舟2", "万轻舟", 101, 0, "乙", None, None, -1),
            (-1, "无角色", "无角色", 101, None, None, None, None, -1),
        ),
    )
    contract = _refresh_workbook_record(fixture, "Hero")

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "duplicate_table_source_id"


def test_runtime_candidate_count_mismatch_is_reason_coded(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    contract = replace(fixture.contract, runtime_candidate_count=1)

    with pytest.raises(CatalogSourceError) as error:
        load_catalog_rows(contract)

    assert error.value.reason_code == "runtime_candidate_count_mismatch"


def _fixture_wave1_entities(*, name="万轻舟"):
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
            "name_zh": name,
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
    return (build, form)


def test_catalog_entities_enrich_form_and_represent_every_row_once(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    catalog = load_catalog_rows(fixture.contract)

    entities = compose_catalog_entities(
        25006280,
        _fixture_wave1_entities(),
        catalog,
    )

    form = next(
        entity for entity in entities
        if entity.entity_id == "wx-build-25006280-hero-1001"
    )
    assert form.values["source_row_payload"]["Desc"] == "完整人物背景"
    assert form.values["skill_ids"] == [10, 11]
    assert form.values["property_ids"] == [1, 2]
    assert form.values["ji_values"] == [{"id": 7, "value": 70}]
    assert form.source_for("source_row_payload") == (
        "wanxiang:wanxiang/ModDocs/AllExcel/Hero.xlsx#row=5"
    )
    assert sum(
        entity.kind == "wanxiang_treasure_snapshot" for entity in entities
    ) == 1
    assert sum(
        entity.kind == "wanxiang_hero_sentinel_snapshot" for entity in entities
    ) == 1
    assert sum("source_table" in entity.values for entity in entities) == 6
    build = next(entity for entity in entities if entity.kind == "wanxiang_build_snapshot")
    assert build.values["catalog_total_rows"] == 6
    assert build.values["runtime_candidate_files"] == []
    assert build.values["source_sha256"] == "WAVE1"


def test_reduced_and_full_hero_disagreement_blocks_catalog(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    catalog = load_catalog_rows(fixture.contract)

    with pytest.raises(CatalogSourceError) as error:
        compose_catalog_entities(
            25006280,
            _fixture_wave1_entities(name="错误名字"),
            catalog,
        )

    assert error.value.reason_code == "hero_registry_reconciliation_conflict"


def test_full_selection_recounts_entities_and_owns_catalog_fields(tmp_path):
    fixture = build_catalog_fixture(tmp_path)
    catalog = load_catalog_rows(fixture.contract)
    wave1_entities = _fixture_wave1_entities()
    wave1 = SnapshotSelection(
        build_id=25006280,
        source_hashes={"wave1.json": "A" * 64},
        entities=wave1_entities,
        counts={
            "wanxiang_build_snapshot": 1,
            "wanxiang_character_form_snapshot": 1,
        },
        scope_name="wave1",
        owned_keys=frozenset(
            key for entity in wave1_entities for key in entity.values
        ),
        scope_entity_kinds=frozenset(
            {"wanxiang_build_snapshot", "wanxiang_character_form_snapshot"}
        ),
    )

    full = compose_full_selection(wave1, catalog, include_edges=False)

    assert len(full.entities) == 7
    assert full.counts == {
        "wanxiang_build_snapshot": 1,
        "wanxiang_character_form_snapshot": 1,
        "wanxiang_hero_sentinel_snapshot": 1,
        "wanxiang_table_row_snapshot": 3,
        "wanxiang_treasure_snapshot": 1,
    }
    assert sum("source_table" in entity.values for entity in full.entities) == 6
    assert full.scope_name == "full_catalog"
    assert "source_row_payload" in full.owned_keys
    assert full.scope_entity_kinds == frozenset(full.counts)
    assert len(full.source_hashes) == 5
    assert full == compose_full_selection(wave1, catalog, include_edges=False)


@pytest.mark.skipif(
    os.environ.get("WANXIANG_CANON_LIVE") != "1",
    reason="set WANXIANG_CANON_LIVE=1 for real full-catalog selection",
)
def test_real_full_catalog_selection_has_exact_pre_edge_topology():
    from catalog_source import compose_full_catalog
    from config import default_config

    source_root = default_config().source_root

    def tree_signature():
        files = tuple(path for path in source_root.rglob("*") if path.is_file())
        return (
            len(files),
            sum(path.stat().st_size for path in files),
            tuple(
                (str(path.relative_to(source_root)), path.stat().st_mtime_ns)
                for path in sorted(files)
            ),
        )

    before = tree_signature()
    selection = compose_full_catalog(default_config(), include_edges=False)
    after = tree_signature()

    assert len(selection.entities) == 31678
    assert selection.counts == {
        "wanxiang_build_snapshot": 1,
        "wanxiang_character_form_snapshot": 228,
        "wanxiang_character_identity": 165,
        "wanxiang_hero_sentinel_snapshot": 1,
        "wanxiang_methodology_reference": 2,
        "wanxiang_source_gap_snapshot": 8,
        "wanxiang_table_row_snapshot": 29669,
        "wanxiang_treasure_snapshot": 41,
        "wanxiang_visual_asset_snapshot": 1391,
        "wanxiang_visual_candidate_snapshot": 172,
    }
    assert sum("source_table" in entity.values for entity in selection.entities) == 29939
    assert sum(
        entity.values.get("source_table") == "EventDialog"
        for entity in selection.entities
    ) == 17210
    forms = [
        entity for entity in selection.entities
        if entity.kind == "wanxiang_character_form_snapshot"
    ]
    assert len(forms) == 228
    assert all(entity.values.get("source_table") == "Hero" for entity in forms)
    build = next(
        entity for entity in selection.entities
        if entity.kind == "wanxiang_build_snapshot"
    )
    assert len(build.values["runtime_candidate_files"]) == 52
    assert before == after

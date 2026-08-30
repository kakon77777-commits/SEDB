from __future__ import annotations

from pathlib import Path

import pytest

from backup import BackupError, create_verified_backup
from catalog_fixtures import build_catalog_fixture
from catalog_source import compose_full_selection, load_catalog_rows
from config import ProjectConfig
from source import SnapshotSelection, SourceEntity
from sedb.entities import EntityService
from store import CanonStore, StorageError


def _wave1_selection() -> SnapshotSelection:
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
    entities = (build, form)
    return SnapshotSelection(
        build_id=25006280,
        source_hashes={"wave1.json": "A" * 64},
        entities=entities,
        counts={
            "wanxiang_build_snapshot": 1,
            "wanxiang_character_form_snapshot": 1,
        },
        scope_name="wave1",
        owned_keys=frozenset(key for entity in entities for key in entity.values),
        scope_entity_kinds=frozenset(
            {"wanxiang_build_snapshot", "wanxiang_character_form_snapshot"}
        ),
    )


def prepared_catalog_store(tmp_path: Path):
    fixture = build_catalog_fixture(tmp_path / "source")
    wave1 = _wave1_selection()
    full = compose_full_selection(
        wave1,
        load_catalog_rows(fixture.contract),
        include_edges=False,
    )
    config = ProjectConfig(
        source_root=tmp_path / "source",
        database_path=tmp_path / "catalog.sqlite",
        expected_entity_counts=wave1.counts,
    )
    return CanonStore.open(config), wave1, full


def test_wave1_scope_ignores_later_catalog_cells(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(full))

    rerun = store.plan(wave1)

    assert rerun.conflicts == ()
    assert rerun.missing_from_source == ()
    assert len(rerun.unchanged) == len(wave1.entities)


def test_missing_catalog_cells_are_enrichment_not_conflict(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))

    plan = store.plan(full)

    assert plan.conflicts == ()
    assert plan.missing_from_source == ()
    assert plan.enrich
    assert not plan.blocked


def test_apply_inserts_new_entities_and_enriches_with_exact_cell_sources(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))

    plan = store.plan(full)
    result = store.apply(plan)
    rerun = store.plan(full)
    form = EntityService(store.db).get_entity(
        "wx-build-25006280-hero-1001"
    )

    assert result.created_entities == 5
    assert result.enriched_entities == 2
    assert result.created_cells > 0
    assert rerun.new == ()
    assert rerun.enrich == ()
    assert rerun.conflicts == ()
    assert form["cells"]["name_zh"]["source"] == "wanxiang:wave1-form"
    assert form["cells"]["source_row_payload"]["source"] == (
        "wanxiang:wanxiang/ModDocs/AllExcel/Hero.xlsx#row=5"
    )


def test_changed_existing_cell_source_blocks_even_when_value_matches(tmp_path):
    store, wave1, _ = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    EntityService(store.db).set_cell(
        "wx-build-25006280-hero-1001",
        "name_zh",
        "万轻舟",
        source="tampered:source-only",
    )

    plan = store.plan(wave1)

    assert plan.blocked
    difference_fields = {
        difference.field
        for conflict in plan.conflicts
        for difference in conflict.differences
    }
    assert "name_zh.source" in difference_fields


def test_stale_enrichment_blocks_before_any_new_entity_insert(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    plan = store.plan(full)
    first = plan.enrich[0]
    cell = first.cells[0]
    EntityService(store.db).set_cell(
        first.entity_id,
        cell.key,
        cell.value,
        source=cell.source,
    )

    with pytest.raises(StorageError) as error:
        store.apply(plan)

    assert error.value.reason_code == "stale_enrichment"
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == len(wave1.entities)


def test_existing_catalog_entity_missing_from_full_selection_blocks(tmp_path):
    store, _, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(full))
    removed = next(
        entity for entity in full.entities
        if entity.kind == "wanxiang_table_row_snapshot"
    )
    reduced = SnapshotSelection(
        build_id=full.build_id,
        source_hashes=full.source_hashes,
        entities=tuple(entity for entity in full.entities if entity != removed),
        counts=full.counts,
        scope_name=full.scope_name,
        owned_keys=full.owned_keys,
        scope_entity_kinds=full.scope_entity_kinds,
    )

    plan = store.plan(reduced)

    assert plan.blocked
    assert removed.entity_id in plan.missing_from_source


def test_catalog_enrichment_preserves_curated_cells(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    EntityService(store.db).set_cell(
        "wx-build-25006280-hero-1001",
        "curator_notes",
        "保留的人工作註",
        source="curator:test",
    )

    store.apply(store.plan(full))
    form = EntityService(store.db).get_entity(
        "wx-build-25006280-hero-1001"
    )

    assert form["values"]["curator_notes"] == "保留的人工作註"
    assert form["cells"]["curator_notes"]["source"] == "curator:test"


def test_enrichment_readback_failure_rolls_back_new_and_added_cells(
    tmp_path, monkeypatch
):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    plan = store.plan(full)

    def fail_readback(*_args, **_kwargs):
        raise StorageError("readback_failure", "injected catalog failure")

    monkeypatch.setattr(store, "_verify_readback", fail_readback)
    with pytest.raises(StorageError) as error:
        store.apply(plan)

    assert error.value.reason_code == "readback_failure"
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == len(wave1.entities)
    form = EntityService(store.db).get_entity(
        "wx-build-25006280-hero-1001"
    )
    assert "source_row_payload" not in form["values"]


def test_verified_backup_is_recoverable_and_never_overwritten(tmp_path):
    store, wave1, _ = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    target = tmp_path / "local-backups" / "wave1.sqlite"

    result = create_verified_backup(store.config, target)

    assert result.path == target
    assert result.integrity == "ok"
    assert result.entity_count == len(wave1.entities)
    assert result.cell_count == store.db.scalar("SELECT COUNT(*) FROM cells")
    assert result.length == target.stat().st_size
    assert len(result.sha256) == 64
    assert result.wal_checkpoint == (0, 0, 0)
    with pytest.raises(BackupError) as error:
        create_verified_backup(store.config, target)
    assert error.value.reason_code == "backup_exists"


def test_backup_refuses_database_with_sidecars(tmp_path):
    store, wave1, _ = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    wal = Path(str(store.config.database_path) + "-wal")
    wal.write_bytes(b"synthetic stale WAL")
    target = tmp_path / "local-backups" / "wave1.sqlite"

    with pytest.raises(BackupError) as error:
        create_verified_backup(store.config, target)

    assert error.value.reason_code == "database_checkpoint_failure"
    assert not target.exists()

from __future__ import annotations

from dataclasses import replace

import pytest

from config import ProjectConfig, VIEW_SPECS
from sedb.db import Database
from sedb.fields import FieldService
from sedb.views import ViewService
from source import CatalogSnapshot, load_catalog
from store import CatalogStore, SchemaConflictError, StorageError


def config(data):
    return ProjectConfig(
        source_root=data["root"],
        database_path=data["db"],
        source_hashes=data["hashes"],
        expected_entity_counts=data["expected_counts"],
    )


def test_schema_is_idempotent_and_creates_classification_views(source_fixture):
    store = CatalogStore.open(config(source_fixture))

    first = store.ensure_schema()
    second = store.ensure_schema()

    assert first.fields_created == 92
    assert first.views_created == 8
    assert second.fields_created == 0
    assert second.fields_reused == 92
    assert second.views_created == 0
    assert [row["name"] for row in ViewService(store.db).list_views()] == sorted(
        spec.name for spec in VIEW_SPECS
    )


def test_read_only_plan_rejects_existing_schema_conflict(source_fixture):
    cfg = config(source_fixture)
    snapshot = load_catalog(cfg)
    db = Database(cfg.database_path)
    wrong = FieldService(db).create_field(
        key="fj_record_key",
        label="Wrong label",
        value_type="integer",
        description="Wrong definition",
        namespace=cfg.namespace,
    )

    with pytest.raises(SchemaConflictError) as exc:
        CatalogStore.read_only_plan(cfg, snapshot)

    assert exc.value.reason_code == "schema_conflict"
    assert FieldService(db).get_field(wrong["id"])["label"] == "Wrong label"
    assert len(FieldService(db).list_fields(limit=10000)) == 1


def test_apply_and_replay_are_atomic_and_idempotent(source_fixture):
    cfg = config(source_fixture)
    snapshot = load_catalog(cfg)
    store = CatalogStore.open(cfg)
    store.ensure_schema()

    first = store.apply(store.plan(snapshot))
    replay = store.plan(snapshot)

    assert first.created_entities == 10
    assert first.created_cells > 10
    assert replay.new == ()
    assert len(replay.unchanged) == 10
    assert replay.blocked is False
    assert store.stats()["entities_by_kind"] == source_fixture["expected_counts"]
    assert store.stats()["integrity"] == "ok"


def test_existing_source_owned_difference_blocks_the_whole_batch(source_fixture):
    cfg = config(source_fixture)
    snapshot = load_catalog(cfg)
    store = CatalogStore.open(cfg)
    store.ensure_schema()
    store.apply(store.plan(snapshot))
    original = snapshot.records[0]
    changed = replace(
        original,
        label="changed label",
        values={**original.values, "fj_record_status": "changed"},
    )
    changed_snapshot = CatalogSnapshot(
        records=(changed, *snapshot.records[1:]),
        entity_counts=snapshot.entity_counts,
        fingerprint=snapshot.fingerprint,
        source_hashes=snapshot.source_hashes,
    )

    plan = store.plan(changed_snapshot)

    assert plan.blocked is True
    assert plan.conflicts[0].entity_id == original.entity_id
    assert {item.field for item in plan.conflicts[0].differences} == {
        "entity.label",
        "fj_record_status",
    }
    with pytest.raises(StorageError) as exc:
        store.apply(plan)
    assert exc.value.reason_code == "blocked_plan"
    assert store.stats()["entities"] == 10


def test_injected_cell_failure_rolls_back_entities_and_cells(
    source_fixture,
    monkeypatch,
):
    cfg = config(source_fixture)
    snapshot = load_catalog(cfg)
    store = CatalogStore.open(cfg)
    store.ensure_schema()
    original = store._insert_cells

    def fail_after_one(conn, rows):
        original(conn, rows[:1])
        raise OSError("injected cell failure")

    monkeypatch.setattr(store, "_insert_cells", fail_after_one)

    with pytest.raises(StorageError) as exc:
        store.apply(store.plan(snapshot))

    assert exc.value.reason_code == "storage_failure"
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == 0
    assert store.db.scalar("SELECT COUNT(*) FROM cells") == 0
    assert store.integrity_check() == "ok"


def test_classification_summary_uses_stored_source_cells(source_fixture):
    cfg = config(source_fixture)
    snapshot = load_catalog(cfg)
    store = CatalogStore.open(cfg)
    store.ensure_schema()
    store.apply(store.plan(snapshot))

    summary = store.classify()

    assert summary["by_kind"] == source_fixture["expected_counts"]
    assert summary["function_catalogs"] == {"Test": 1}
    assert summary["trigger_catalogs"] == {"Test": 1}
    assert summary["asset_extensions"] == {".png": 1}
    assert summary["claim_statuses"] == {"observed": 1}
    assert summary["runtime_statuses"] == {"not_started": 10}

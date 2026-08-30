from __future__ import annotations

from dataclasses import replace

import pytest

from config import NAMESPACE
from fixtures import build_snapshot_fixture
from schema import FIELD_SPECS, VIEW_SPECS
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService
from source import SnapshotSelection, load_snapshot
from store import CanonStore, SchemaConflictError, StorageError


def prepared(tmp_path):
    fixture = build_snapshot_fixture(tmp_path / "source")
    config = replace(fixture.config, database_path=tmp_path / "canon.sqlite")
    selection = load_snapshot(config)
    store = CanonStore.open(config)
    return config, selection, store


def test_schema_first_run_creates_all_fields_and_views_second_reuses(tmp_path):
    _, _, store = prepared(tmp_path)

    first = store.ensure_schema()
    second = store.ensure_schema()

    assert first.fields_created == len(FIELD_SPECS)
    assert first.fields_reused == 0
    assert first.views_created == len(VIEW_SPECS)
    assert first.views_reused == 0
    assert first.integrity == "ok"
    assert second.fields_created == 0
    assert second.fields_reused == len(FIELD_SPECS)
    assert second.views_created == 0
    assert second.views_reused == len(VIEW_SPECS)
    views = {view["name"]: view for view in ViewService(store.db).list_views()}
    assert set(views) == {spec.name for spec in VIEW_SPECS}
    for spec in VIEW_SPECS:
        actual = ViewService(store.db).get_view(views[spec.name]["id"])
        assert tuple(field["key"] for field in actual["fields"]) == spec.field_keys


def test_schema_conflict_never_creates_other_owned_fields_or_views(tmp_path):
    config, _, _ = prepared(tmp_path)
    db = Database(config.database_path)
    first = FIELD_SPECS[0]
    FieldService(db).create_field(
        key=first.key,
        label=first.label,
        value_type="text",
        description="wrong description",
        namespace="foreign_namespace",
    )
    store = CanonStore.open(config)

    with pytest.raises(SchemaConflictError) as error:
        store.ensure_schema()

    assert error.value.reason_code == "schema_conflict"
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert db.scalar("SELECT COUNT(*) FROM task_views") == 0


def test_conflicting_view_order_is_rejected_without_schema_mutation(tmp_path):
    _, _, store = prepared(tmp_path)
    store.ensure_schema()
    view = ViewService(store.db).list_views()[0]
    with store.db.connect() as conn:
        conn.execute("DELETE FROM task_view_fields WHERE view_id=?", (view["id"],))
        field_ids = {
            row["key"]: row["id"]
            for row in conn.execute("SELECT id,key FROM fields").fetchall()
        }
        spec = next(item for item in VIEW_SPECS if item.name == view["name"])
        conn.executemany(
            "INSERT INTO task_view_fields(view_id,field_id,ordinal) VALUES(?,?,?)",
            [
                (view["id"], field_ids[key], ordinal)
                for ordinal, key in enumerate(reversed(spec.field_keys))
            ],
        )
    fields_before = store.db.scalar("SELECT COUNT(*) FROM fields")
    views_before = store.db.scalar("SELECT COUNT(*) FROM task_views")

    with pytest.raises(SchemaConflictError):
        store.ensure_schema()

    assert store.db.scalar("SELECT COUNT(*) FROM fields") == fields_before
    assert store.db.scalar("SELECT COUNT(*) FROM task_views") == views_before


def test_empty_database_plans_every_entity_as_new_in_stable_order(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()

    plan = store.plan(selection)

    assert len(plan.new) == len(selection.entities)
    assert plan.unchanged == ()
    assert plan.conflicts == ()
    assert plan.missing_from_source == ()
    assert plan.blocked is False
    assert [entity.entity_id for entity in plan.new] == sorted(
        entity.entity_id for entity in selection.entities
    )
    assert len(plan.source_fingerprint) == 64


def test_plan_fingerprint_is_independent_of_selection_input_order(tmp_path):
    _, selection, store = prepared(tmp_path)
    reverse_selection = SnapshotSelection(
        build_id=selection.build_id,
        source_hashes=dict(reversed(tuple(selection.source_hashes.items()))),
        entities=tuple(reversed(selection.entities)),
        counts=selection.counts,
    )

    forward = store.plan(selection)
    reverse = store.plan(reverse_selection)

    assert forward.source_fingerprint == reverse.source_fingerprint
    assert tuple(entity.entity_id for entity in forward.new) == tuple(
        entity.entity_id for entity in reverse.new
    )


def test_apply_is_atomic_and_exact_rerun_is_no_op(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()

    result = store.apply(store.plan(selection))
    rerun = store.plan(selection)

    assert result.created_entities == len(selection.entities)
    assert result.created_cells > result.created_entities
    assert result.integrity == "ok"
    assert store.integrity_check() == "ok"
    assert rerun.new == ()
    assert rerun.conflicts == ()
    assert rerun.missing_from_source == ()
    assert rerun.blocked is False
    assert len(rerun.unchanged) == len(selection.entities)
    no_op = store.apply(rerun)
    assert no_op.created_entities == 0
    assert no_op.created_cells == 0


def test_changed_owned_cell_produces_source_conflict(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(selection))
    build = next(
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_build_snapshot"
    )
    EntityService(store.db).set_cell(
        build.entity_id,
        "snapshot_status",
        "TAMPERED",
        source="test:tamper",
    )

    plan = store.plan(selection)

    assert plan.blocked is True
    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].entity_id == build.entity_id
    assert plan.conflicts[0].reason_code == "source_conflict"
    assert any(
        difference.field == "snapshot_status"
        for difference in plan.conflicts[0].differences
    )


def test_existing_target_build_entity_missing_from_selection_blocks(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(selection))
    methodology = next(
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_methodology_reference"
    )
    reduced = SnapshotSelection(
        build_id=selection.build_id,
        source_hashes=selection.source_hashes,
        entities=tuple(
            entity for entity in selection.entities if entity != methodology
        ),
        counts=selection.counts,
    )

    plan = store.plan(reduced)

    assert plan.blocked is True
    assert plan.missing_from_source == (methodology.entity_id,)


def test_curated_cells_are_preserved_and_ignored_by_source_plan(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(selection))
    identity = next(
        entity
        for entity in selection.entities
        if entity.kind == "wanxiang_character_identity"
    )
    EntityService(store.db).set_cell(
        identity.entity_id,
        "curator_notes",
        "human-reviewed note",
        source="curator:test",
    )

    plan = store.plan(selection)
    result = store.apply(plan)
    stored = EntityService(store.db).get_entity(identity.entity_id)

    assert plan.blocked is False
    assert identity.entity_id in plan.unchanged
    assert result.created_entities == 0
    assert stored["values"]["curator_notes"] == "human-reviewed note"
    assert stored["cells"]["curator_notes"]["source"] == "curator:test"


def test_blocked_plan_cannot_mutate_database(tmp_path):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(selection))
    entity = selection.entities[0]
    EntityService(store.db).set_cell(
        entity.entity_id,
        "record_status",
        "TAMPERED",
        source="test:tamper",
    )
    blocked = store.plan(selection)
    before = store.db.scalar("SELECT COUNT(*) FROM entities")

    with pytest.raises(StorageError) as error:
        store.apply(blocked)

    assert error.value.reason_code == "blocked_plan"
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == before


def test_readback_failure_rolls_back_complete_entity_and_cell_batch(
    tmp_path, monkeypatch
):
    _, selection, store = prepared(tmp_path)
    store.ensure_schema()
    plan = store.plan(selection)

    def fail_readback(*_args, **_kwargs):
        raise StorageError("readback_failure", "injected readback failure")

    monkeypatch.setattr(store, "_verify_readback", fail_readback)

    with pytest.raises(StorageError) as error:
        store.apply(plan)

    assert error.value.reason_code == "readback_failure"
    assert store.db.scalar("SELECT COUNT(*) FROM entities") == 0
    assert store.db.scalar("SELECT COUNT(*) FROM cells") == 0


def test_stats_reports_project_counts_without_counting_foreign_namespace(tmp_path):
    config, selection, store = prepared(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(selection))
    foreign = EntityService(store.db).create_entity(
        entity_id="foreign-record",
        kind="foreign",
        label="Foreign",
    )
    assert foreign["id"] == "foreign-record"

    stats = store.stats()

    assert stats["project_entities"] == len(selection.entities)
    assert stats["by_kind"] == selection.counts
    assert stats["database_entities"] == len(selection.entities) + 1
    assert stats["namespace"] == NAMESPACE
    assert stats["integrity"] == "ok"

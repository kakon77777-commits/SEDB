import pytest

from conftest import paper
from config import CELL_SOURCE, FIELD_SPECS, ProjectConfig, TASK_VIEW_NAME
from sedb.db import Database
from sedb.fields import FieldService
from sedb.views import ViewService
from source import load_month
from store import CorpusStore, SchemaConflictError, StorageError


def cfg(tmp_path):
    return ProjectConfig(tmp_path / "papers.json", tmp_path / "corpus.sqlite")


def selection(write_registry, items, month="2026-04"):
    return load_month(write_registry(items), month)


def seed_paper(store, record):
    entity = store.entities.create_entity(
        entity_id=record.paper_id,
        label=record.label,
        kind=store.config.entity_kind,
    )
    for key, value in record.values.items():
        store.entities.set_cell(entity["id"], key, value, source=CELL_SOURCE)


def test_init_is_idempotent_and_creates_exact_view(tmp_path):
    store = CorpusStore.open(cfg(tmp_path))

    first = store.ensure_schema()
    second = store.ensure_schema()

    assert first.fields_created == 11
    assert first.view_created is True
    assert second.fields_created == 0
    assert second.fields_reused == 11
    assert second.view_created is False
    views = ViewService(store.db).list_views()
    assert [view["name"] for view in views] == [TASK_VIEW_NAME]
    view = ViewService(store.db).get_view(views[0]["id"])
    assert [field["key"] for field in view["fields"]] == [
        spec.key for spec in FIELD_SPECS
    ]


def test_field_schema_conflict_does_not_overwrite_or_create_other_fields(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    existing = FieldService(db).create_field(
        key="paper_id",
        label="Wrong",
        value_type="integer",
        description="Wrong",
        namespace="other",
    )

    with pytest.raises(SchemaConflictError) as exc:
        CorpusStore.open(config).ensure_schema()

    assert exc.value.reason_code == "schema_conflict"
    loaded = FieldService(db).get_field(existing["id"])
    assert loaded["label"] == "Wrong"
    assert loaded["value_type"] == "integer"
    assert len(FieldService(db).list_fields(limit=10000)) == 1


def test_normalized_key_collision_is_schema_conflict(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    existing = FieldService(db).create_field(
        key="paper-id",
        label="Legacy paper id",
        namespace=config.namespace,
    )

    with pytest.raises(SchemaConflictError) as exc:
        CorpusStore.open(config).ensure_schema()

    assert exc.value.details[0]["reason"] == "normalized_key_collision"
    assert FieldService(db).get_field(existing["id"])["key"] == "paper-id"
    assert len(FieldService(db).list_fields(limit=10000)) == 1


def test_task_view_schema_conflict_does_not_create_owned_fields(tmp_path):
    config = cfg(tmp_path)
    db = Database(config.database_path)
    FieldService(db).create_field(key="foreign", label="Foreign")
    ViewService(db).create_view(TASK_VIEW_NAME, ["foreign"])

    with pytest.raises(SchemaConflictError):
        CorpusStore.open(config).ensure_schema()

    assert [
        field["key"] for field in FieldService(db).list_fields(limit=10000)
    ] == ["foreign"]


def test_empty_stats_are_sparse_and_integrity_is_ok(tmp_path):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()

    stats = store.stats()

    assert stats["fields"] == 11
    assert stats["paper_entities"] == 0
    assert stats["cells"] == 0
    assert stats["density"] == 0.0
    assert stats["integrity"] == "ok"


def test_new_and_unchanged_are_deterministic(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(
        write_registry,
        [paper("lm-000001"), paper("lm-000002")],
    )

    first = store.plan(selected)
    seed_paper(store, selected.papers[0])
    second = store.plan(selected)

    assert [item.paper_id for item in first.new] == ["lm-000001", "lm-000002"]
    assert [item.paper_id for item in second.new] == ["lm-000002"]
    assert second.unchanged == ("lm-000001",)


def test_conflict_and_new_block_the_plan(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(
        write_registry,
        [paper("lm-000001", title="Old")],
    )
    seed_paper(store, original.papers[0])
    changed = selection(
        write_registry,
        [
            paper(
                "lm-000001",
                title="New",
                hash="sha256:" + "b" * 64,
            ),
            paper("lm-000002"),
        ],
    )

    plan = store.plan(changed)

    assert plan.blocked is True
    assert [item.paper_id for item in plan.new] == ["lm-000002"]
    assert plan.conflicts[0].paper_id == "lm-000001"
    assert {diff.field for diff in plan.conflicts[0].differences} == {
        "entity.label",
        "title",
        "sha256",
    }


def test_missing_from_source_blocks_new_records(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, original.papers[0])
    current = selection(write_registry, [paper("lm-000002")])

    plan = store.plan(current)

    assert plan.blocked is True
    assert [item.paper_id for item in plan.new] == ["lm-000002"]
    assert [item.paper_id for item in plan.missing_from_source] == ["lm-000001"]


def test_month_reassignment_is_global_identity_conflict(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    april = selection(
        write_registry,
        [paper("lm-000001", month="2026-04")],
        "2026-04",
    )
    seed_paper(store, april.papers[0])
    may = selection(
        write_registry,
        [paper("lm-000001", month="2026-05")],
        "2026-05",
    )

    plan = store.plan(may)

    assert plan.conflicts[0].reason_code == "month_reassignment"
    assert plan.conflicts[0].differences[0].field == "month"


def test_future_non_owned_cell_is_ignored(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, selected.papers[0])
    store.fields.create_field(
        key="theory_family",
        label="Theory family",
        namespace="future",
    )
    store.entities.set_cell(
        "lm-000001",
        "theory_family",
        "MWT",
        source="future:proposal",
    )

    plan = store.plan(selected)

    assert plan.unchanged == ("lm-000001",)
    assert plan.blocked is False


def test_apply_creates_exact_entities_and_nonblank_cells(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(
        write_registry,
        [
            paper("lm-000001", created=None),
            paper("lm-000002"),
        ],
    )
    plan = store.plan(selected)

    result = store.apply(plan)

    assert result.created_entities == 2
    assert result.created_cells == sum(
        len(record.values) for record in selected.papers
    )
    assert store.entities.get_entity("lm-000001")["cells"].get(
        "created_date"
    ) is None
    assert store.integrity_check() == "ok"


def test_apply_refuses_a_blocked_plan_before_writing(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    original = selection(write_registry, [paper("lm-000001")])
    seed_paper(store, original.papers[0])
    changed = selection(
        write_registry,
        [paper("lm-000001", title="Changed"), paper("lm-000002")],
    )

    with pytest.raises(StorageError) as exc:
        store.apply(store.plan(changed))

    assert exc.value.reason_code == "blocked_plan"
    with pytest.raises(KeyError):
        store.entities.get_entity("lm-000002")


def test_injected_cell_failure_rolls_back_whole_batch(
    tmp_path,
    write_registry,
    monkeypatch,
):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(
        write_registry,
        [paper("lm-000001"), paper("lm-000002")],
    )
    original = store._insert_cells

    def fail_after_one(conn, rows):
        original(conn, rows[:1])
        raise OSError("injected write failure")

    monkeypatch.setattr(store, "_insert_cells", fail_after_one)

    with pytest.raises(StorageError) as exc:
        store.apply(store.plan(selected))

    assert exc.value.reason_code == "storage_failure"
    assert store.stats()["paper_entities"] == 0
    assert store.db.scalar("SELECT COUNT(*) FROM cells") == 0
    assert store.integrity_check() == "ok"


def test_rerun_after_apply_is_no_op_plan(tmp_path, write_registry):
    store = CorpusStore.open(cfg(tmp_path))
    store.ensure_schema()
    selected = selection(write_registry, [paper("lm-000001")])
    store.apply(store.plan(selected))

    rerun = store.plan(selected)

    assert rerun.new == ()
    assert rerun.unchanged == ("lm-000001",)
    assert rerun.blocked is False

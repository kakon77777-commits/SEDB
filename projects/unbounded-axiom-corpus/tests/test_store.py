import pytest

from config import FIELD_SPECS, ProjectConfig, TASK_VIEW_NAME
from sedb.db import Database
from sedb.fields import FieldService
from sedb.views import ViewService
from store import CorpusStore, SchemaConflictError


def cfg(tmp_path):
    return ProjectConfig(tmp_path / "papers.json", tmp_path / "corpus.sqlite")


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

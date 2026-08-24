from __future__ import annotations

import pytest

from schema import CATEGORY_SEEDS, CatalogStore, EVENT_KINDS, FIELD_SPECS


def test_schema_and_seed_categories_are_idempotent(tmp_path) -> None:
    database_path = tmp_path / "catalog.sqlite"

    first = CatalogStore.open(database_path)
    first.ensure_schema()
    second = CatalogStore.open(database_path)
    second.ensure_schema()

    assert len(second.fields.list_fields(limit=10_000)) == len(FIELD_SPECS)
    assert len(second.find("category")) == len(CATEGORY_SEEDS)
    theory = second.get_record("category:theory")
    assert theory["values"]["category_state"] == "active"
    assert second.find("category", stable_key="theory") == [theory]


def test_event_entities_are_write_once(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    event = store.create_record(
        "copy_event",
        "copy refused",
        {"outcome": "refused", "failure_reason": "collision"},
        entity_id="copy-event:test",
    )

    assert event["values"]["outcome"] == "refused"
    with pytest.raises(ValueError, match="already exists"):
        store.create_record(
            "copy_event",
            "rewrite",
            {"outcome": "copied"},
            entity_id="copy-event:test",
        )
    with pytest.raises(ValueError, match="immutable event"):
        store.update_current(
            "copy-event:test", {"outcome": "copied"}, source="test"
        )


def test_current_records_can_be_updated_without_changing_event_policy(
    tmp_path,
) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    component = store.create_record(
        "component",
        "paper.md",
        {"sha256": "old", "verification_state": "unverified"},
    )

    updated = store.update_current(
        component["id"],
        {"sha256": "new", "verification_state": "verified"},
        source="test",
    )

    assert updated["values"]["sha256"] == "new"
    assert updated["values"]["verification_state"] == "verified"
    assert "component" not in EVENT_KINDS


def test_relation_and_task_views_are_seeded_once(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    source = store.create_record("package", "source", {"stable_key": "source"})
    anchor = store.create_record(
        "temporal_anchor",
        "anchor",
        {"temporal_status": "registered"},
    )

    relation = store.create_relation(
        source["id"], "category:theory", "classified_as", anchor["id"]
    )
    store.ensure_schema()

    assert relation["values"]["source_record_id"] == source["id"]
    assert relation["values"]["target_record_id"] == "category:theory"
    assert relation["values"]["temporal_anchor_id"] == anchor["id"]
    names = [view["name"] for view in store.views.list_views()]
    assert len(names) == len(set(names)) == 9


def test_unknown_fields_are_rejected_before_entity_creation(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()

    with pytest.raises(KeyError, match="field not found"):
        store.create_record("package", "bad", {"not_registered": "x"})

    assert store.find("package") == []


def test_catalog_database_integrity_is_ok(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()

    assert store.integrity_check() == "ok"


def test_bulk_create_is_atomic_and_matches_single_record_shape(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()

    created = store.create_records_bulk(
        [
            {
                "entity_id": "package:bulk",
                "kind": "package",
                "label": "Bulk package",
                "values": {"title": "Bulk package", "version": 1},
                "source": "test",
            },
            {
                "entity_id": "component:bulk",
                "kind": "component",
                "label": "paper.md",
                "values": {
                    "title": "paper.md",
                    "parent_package_id": "package:bulk",
                    "sha256": "abc",
                },
                "source": "test",
            },
        ]
    )

    assert [record["id"] for record in created] == [
        "package:bulk",
        "component:bulk",
    ]
    assert created[1]["values"]["parent_package_id"] == "package:bulk"

    with pytest.raises(ValueError, match="duplicate record id in batch"):
        store.create_records_bulk(
            [
                {
                    "entity_id": "package:duplicate",
                    "kind": "package",
                    "label": "one",
                    "values": {},
                },
                {
                    "entity_id": "package:duplicate",
                    "kind": "package",
                    "label": "two",
                    "values": {},
                },
            ]
        )
    assert not store._entity_exists("package:duplicate")


def test_bulk_current_update_is_atomic_and_refuses_event_kind(tmp_path) -> None:
    store = CatalogStore.open(tmp_path / "catalog.sqlite")
    store.ensure_schema()
    package = store.create_record("package", "p", {"title": "old"})
    event = store.create_record("copy_event", "event", {"outcome": "refused"})

    with pytest.raises(ValueError, match="immutable event"):
        store.update_current_bulk(
            [
                (package["id"], {"title": "new"}, "test"),
                (event["id"], {"outcome": "copied"}, "test"),
            ]
        )

    assert store.get_record(package["id"])["values"]["title"] == "old"

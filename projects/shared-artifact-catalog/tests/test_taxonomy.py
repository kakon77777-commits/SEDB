from __future__ import annotations

import pytest

from schema import CatalogStore
from taxonomy import (
    UserApprovalRequired,
    add_classification,
    add_classifications_bulk,
    propose_category,
    register_additive_category,
    register_additive_relation_type,
    register_category_alias,
    require_user_gate,
    search_records,
    show_record,
)


@pytest.fixture
def store(tmp_path) -> CatalogStore:
    result = CatalogStore.open(tmp_path / "catalog.sqlite")
    result.ensure_schema()
    return result


@pytest.fixture
def anchor(store: CatalogStore) -> str:
    return store.create_record(
        "temporal_anchor",
        "taxonomy batch",
        {
            "stable_key": "taxonomy-test-anchor",
            "temporal_status": "registered",
            "ctcl_instant_id": "ctcl:instant:test",
            "ctcl_local": "2026-08-24T20:00:00+08:00",
        },
        entity_id="temporal-anchor:taxonomy-test",
    )["id"]


def test_ai_proposal_does_not_create_active_category(
    store: CatalogStore,
) -> None:
    proposal = propose_category(
        store,
        key="simulation_trace",
        definition="Recorded simulation trajectories",
        examples=["trace.json"],
        insufficiency_reason="research_data is too broad",
        proposer_claim="AI-X",
        host_task_id=None,
    )

    assert proposal["values"]["decision"] == "pending"
    assert proposal["values"]["host_task_id"] == "unresolved"
    assert store.find("category", stable_key="simulation_trace") == []


def test_registrar_can_add_category_and_classify_component_twice(
    store: CatalogStore, anchor: str
) -> None:
    category = register_additive_category(
        store,
        "simulation_trace",
        "Simulation trace",
        "Recorded simulation trajectories",
        "category:research_data",
        "catalog-registrar",
        anchor,
    )
    component = store.create_record(
        "component",
        "trace.json",
        {
            "stable_key": "trace",
            "title": "World simulation trace",
            "content_languages": ["zxx"],
        },
    )

    add_classification(
        store, component["id"], category["id"], "catalog-registrar", anchor
    )
    add_classification(
        store,
        component["id"],
        "category:research_evidence",
        "catalog-registrar",
        anchor,
    )

    relations = store.find(
        "relation",
        source_record_id=component["id"],
        relation_type="classified_as",
    )
    assert len(relations) == 2
    assert category["values"]["parent_category_id"] == "category:research_data"
    assert len(store.find("registration_decision", decision="accepted")) == 1


def test_registrar_can_add_alias_and_relation_type(
    store: CatalogStore, anchor: str
) -> None:
    alias = register_category_alias(
        store,
        "paper",
        "category:theory",
        "catalog-registrar",
        anchor,
    )
    relation_type = register_additive_relation_type(
        store,
        "documents",
        "Documents",
        "Source documents target",
        "catalog-registrar",
        anchor,
    )

    assert alias["values"]["category_state"] == "alias"
    assert alias["values"]["alias_target_id"] == "category:theory"
    assert relation_type["values"]["stable_key"] == "documents"
    with pytest.raises(ValueError, match="already registered"):
        register_additive_relation_type(
            store,
            "documents",
            "Documents again",
            "Duplicate",
            "catalog-registrar",
            anchor,
        )


@pytest.mark.parametrize(
    "operation",
    [
        "merge",
        "rename",
        "deprecate",
        "delete",
        "routing_change",
        "bulk_reclassify",
    ],
)
def test_meaning_changing_operations_require_user_gate(
    operation: str,
) -> None:
    with pytest.raises(UserApprovalRequired, match=operation):
        require_user_gate(operation)


def test_search_filters_by_text_category_and_language(
    store: CatalogStore, anchor: str
) -> None:
    component = store.create_record(
        "component",
        "world.md",
        {
            "title": "Geometric world theory",
            "summary": "A bounded world model",
            "content_languages": ["zh-Hant", "en"],
            "content_identity": "same-content",
        },
    )
    duplicate = store.create_record(
        "component",
        "copy.md",
        {
            "title": "Duplicate occurrence",
            "content_languages": ["zh-Hant"],
            "content_identity": "same-content",
        },
    )
    add_classification(
        store,
        component["id"],
        "category:theory",
        "catalog-registrar",
        anchor,
    )

    results = search_records(
        store, "world", category="theory", language="zh-Hant"
    )
    wrong_language = search_records(
        store, "world", category="theory", language="ja"
    )
    detail = show_record(store, component["id"])

    assert [item["id"] for item in results] == [component["id"]]
    assert wrong_language == []
    assert len(detail["outbound_relations"]) == 1
    assert [item["id"] for item in detail["duplicate_occurrences"]] == [
        duplicate["id"]
    ]


def test_duplicate_classification_is_idempotent(
    store: CatalogStore, anchor: str
) -> None:
    component = store.create_record("component", "paper.md", {"title": "Paper"})

    first = add_classification(
        store,
        component["id"],
        "category:theory",
        "catalog-registrar",
        anchor,
    )
    second = add_classification(
        store,
        component["id"],
        "category:theory",
        "catalog-registrar",
        anchor,
    )

    assert first["id"] == second["id"]
    assert len(store.find("relation", relation_type="classified_as")) == 1


def test_invalid_anchor_leaves_no_registered_category(
    store: CatalogStore,
) -> None:
    with pytest.raises(KeyError, match="entity not found"):
        register_additive_category(
            store,
            "orphan_category",
            "Orphan category",
            "Must not survive an invalid anchor.",
            "",
            "catalog-registrar",
            "temporal-anchor:missing",
        )

    assert store.find("category", stable_key="orphan_category") == []


def test_bulk_classification_creates_each_missing_relation_once(
    store: CatalogStore, anchor: str
) -> None:
    specs = [
        {
            "entity_id": f"component:bulk-{index}",
            "kind": "component",
            "label": f"component-{index}",
            "values": {"title": f"component-{index}"},
        }
        for index in range(100)
    ]
    store.create_records_bulk(specs, return_records=False)
    pairs = [
        (f"component:bulk-{index}", category)
        for index in range(100)
        for category in ("category:theory", "category:documentation")
    ]

    first = add_classifications_bulk(
        store, pairs, "catalog-registrar", anchor
    )
    second = add_classifications_bulk(
        store, pairs, "catalog-registrar", anchor
    )

    assert first == 200
    assert second == 0
    assert len(store.find("relation", relation_type="classified_as")) == 200

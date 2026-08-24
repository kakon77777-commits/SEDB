from __future__ import annotations

import re
from typing import Any

from schema import CatalogStore
from temporal import get_effective_temporal_anchor


SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
USER_GATED_OPERATIONS = frozenset(
    {
        "merge",
        "rename",
        "deprecate",
        "delete",
        "routing_change",
        "bulk_reclassify",
    }
)


class UserApprovalRequired(PermissionError):
    pass


def _validate_key(key: str) -> str:
    normalized = key.strip().lower().replace("-", "_")
    if not SAFE_KEY.fullmatch(normalized):
        raise ValueError(
            "taxonomy key must use lowercase letters, numbers, and underscores"
        )
    return normalized


def _require_anchor(store: CatalogStore, anchor_id: str) -> dict:
    anchor = store.get_record(anchor_id)
    if anchor["kind"] != "temporal_anchor":
        raise ValueError(f"not a temporal anchor: {anchor_id}")
    return anchor


def propose_category(
    store: CatalogStore,
    *,
    key: str,
    definition: str,
    examples: list[str],
    insufficiency_reason: str,
    proposer_claim: str = "",
    host_task_id: str | None = None,
    parent_category_id: str = "",
) -> dict:
    stable_key = _validate_key(key)
    if not definition.strip() or not examples or not insufficiency_reason.strip():
        raise ValueError(
            "definition, examples, and insufficiency reason are required"
        )
    return store.create_record(
        "classification_proposal",
        f"Propose category {stable_key}",
        {
            "stable_key": stable_key,
            "title": stable_key.replace("_", " ").title(),
            "definition": definition.strip(),
            "examples": [str(item) for item in examples],
            "insufficiency_reason": insufficiency_reason.strip(),
            "proposer_claim": proposer_claim.strip(),
            "host_task_id": (host_task_id or "unresolved").strip()
            or "unresolved",
            "parent_category_id": parent_category_id.strip(),
            "decision": "pending",
        },
        source="artifact-catalog:taxonomy",
    )


def propose_relation_type(
    store: CatalogStore,
    *,
    key: str,
    definition: str,
    examples: list[str],
    insufficiency_reason: str,
    proposer_claim: str = "",
    host_task_id: str | None = None,
) -> dict:
    proposal = propose_category(
        store,
        key=key,
        definition=definition,
        examples=examples,
        insufficiency_reason=insufficiency_reason,
        proposer_claim=proposer_claim,
        host_task_id=host_task_id,
    )
    return store.create_record(
        "relation_type_proposal",
        f"Propose relation type {proposal['values']['stable_key']}",
        {
            **proposal["values"],
            "source_record_id": proposal["id"],
        },
        source="artifact-catalog:taxonomy",
    )


def _decision(
    store: CatalogStore,
    target_id: str,
    registrar: str,
    anchor_id: str,
    reason: str,
) -> dict:
    _require_anchor(store, anchor_id)
    return store.create_record(
        "registration_decision",
        f"Accept additive registration {target_id}",
        {
            "source_record_id": target_id,
            "decision": "accepted",
            "decision_reason": reason,
            "registrar": registrar,
            "temporal_anchor_id": anchor_id,
        },
        source="artifact-catalog:taxonomy",
    )


def _ensure_unique_taxonomy_key(store: CatalogStore, key: str) -> None:
    if store.find("category", stable_key=key) or store.find(
        "relation_type", stable_key=key
    ):
        raise ValueError(f"taxonomy key already registered: {key}")


def register_additive_category(
    store: CatalogStore,
    key: str,
    label: str,
    definition: str,
    parent_category_id: str,
    registrar: str,
    anchor_id: str,
) -> dict:
    stable_key = _validate_key(key)
    _require_anchor(store, anchor_id)
    _ensure_unique_taxonomy_key(store, stable_key)
    if parent_category_id:
        parent = store.get_record(parent_category_id)
        if parent["kind"] != "category":
            raise ValueError("parent category id does not name a category")
    category = store.create_record(
        "category",
        label.strip(),
        {
            "stable_key": stable_key,
            "title": label.strip(),
            "definition": definition.strip(),
            "parent_category_id": parent_category_id,
            "category_state": "active",
            "registrar": registrar.strip(),
            "temporal_anchor_id": anchor_id,
        },
        entity_id=f"category:{stable_key}",
        source="artifact-catalog:taxonomy",
    )
    _decision(
        store,
        category["id"],
        registrar,
        anchor_id,
        "additive category registration",
    )
    return category


def register_category_alias(
    store: CatalogStore,
    key: str,
    target_category_id: str,
    registrar: str,
    anchor_id: str,
) -> dict:
    stable_key = _validate_key(key)
    _require_anchor(store, anchor_id)
    _ensure_unique_taxonomy_key(store, stable_key)
    target = store.get_record(target_category_id)
    if target["kind"] != "category":
        raise ValueError("alias target is not a category")
    alias = store.create_record(
        "category",
        f"Alias {stable_key}",
        {
            "stable_key": stable_key,
            "title": stable_key.replace("_", " ").title(),
            "definition": f"Alias of {target_category_id}",
            "alias_target_id": target_category_id,
            "category_state": "alias",
            "registrar": registrar.strip(),
            "temporal_anchor_id": anchor_id,
        },
        entity_id=f"category-alias:{stable_key}",
        source="artifact-catalog:taxonomy",
    )
    _decision(
        store,
        alias["id"],
        registrar,
        anchor_id,
        "additive category alias registration",
    )
    return alias


def register_additive_relation_type(
    store: CatalogStore,
    key: str,
    label: str,
    definition: str,
    registrar: str,
    anchor_id: str,
) -> dict:
    stable_key = _validate_key(key)
    _require_anchor(store, anchor_id)
    _ensure_unique_taxonomy_key(store, stable_key)
    relation_type = store.create_record(
        "relation_type",
        label.strip(),
        {
            "stable_key": stable_key,
            "title": label.strip(),
            "definition": definition.strip(),
            "category_state": "active",
            "registrar": registrar.strip(),
            "temporal_anchor_id": anchor_id,
        },
        entity_id=f"relation-type:{stable_key}",
        source="artifact-catalog:taxonomy",
    )
    _decision(
        store,
        relation_type["id"],
        registrar,
        anchor_id,
        "additive relation type registration",
    )
    return relation_type


def _resolve_category(store: CatalogStore, category: str) -> dict:
    if category.startswith("category:") or category.startswith(
        "category-alias:"
    ):
        record = store.get_record(category)
    else:
        matches = store.find("category", stable_key=_validate_key(category))
        if len(matches) != 1:
            raise KeyError(f"category not found or ambiguous: {category}")
        record = matches[0]
    if record["kind"] != "category":
        raise ValueError("classification target is not a category")
    if record["values"].get("category_state") == "alias":
        return store.get_record(record["values"]["alias_target_id"])
    return record


def add_classification(
    store: CatalogStore,
    record_id: str,
    category: str,
    registrar: str,
    anchor_id: str,
) -> dict:
    store.get_record(record_id)
    category_record = _resolve_category(store, category)
    _require_anchor(store, anchor_id)
    existing = store.find(
        "relation",
        source_record_id=record_id,
        target_record_id=category_record["id"],
        relation_type="classified_as",
    )
    if existing:
        return existing[0]
    return store.create_relation(
        record_id,
        category_record["id"],
        "classified_as",
        anchor_id,
        source=f"artifact-catalog:taxonomy:{registrar}",
    )


def require_user_gate(operation: str) -> None:
    if operation in USER_GATED_OPERATIONS:
        raise UserApprovalRequired(
            f"user approval required for taxonomy operation: {operation}"
        )


def _category_sources(store: CatalogStore, category: str) -> set[str]:
    category_id = _resolve_category(store, category)["id"]
    return {
        relation["values"]["source_record_id"]
        for relation in store.find(
            "relation",
            target_record_id=category_id,
            relation_type="classified_as",
        )
    }


def _text_haystack(record: dict) -> str:
    values = record["values"]
    parts: list[str] = [record["id"], record["label"]]
    for key in ("title", "summary", "source_relpath"):
        parts.append(str(values.get(key, "")))
    parts.extend(str(item) for item in values.get("keywords", []))
    return "\n".join(parts).casefold()


def search_records(
    store: CatalogStore,
    query: str,
    *,
    category: str | None = None,
    language: str | None = None,
) -> list[dict]:
    needle = query.strip().casefold()
    category_sources = (
        _category_sources(store, category) if category else None
    )
    results: list[dict] = []
    for kind in ("package", "component"):
        for record in store.find(kind):
            if needle and needle not in _text_haystack(record):
                continue
            if category_sources is not None and record["id"] not in category_sources:
                continue
            if language:
                values = record["values"]
                languages = set(values.get("content_languages", [])) | set(
                    values.get("interface_languages", [])
                )
                if language not in languages:
                    continue
            results.append(record)
    return sorted(results, key=lambda item: (item["label"].casefold(), item["id"]))


def show_record(store: CatalogStore, record_id: str) -> dict[str, Any]:
    record = store.get_record(record_id)
    outbound = store.find("relation", source_record_id=record_id)
    inbound = store.find("relation", target_record_id=record_id)
    identity = record["values"].get("content_identity")
    duplicates = []
    if identity:
        duplicates = [
            item
            for item in store.find("component", content_identity=identity)
            if item["id"] != record_id
        ]
    version_events = sorted(
        store.find(
            f"{record['kind']}_version_event", source_record_id=record_id
        ),
        key=lambda item: (item["created_at"], item["id"]),
    )
    latest_anchor = None
    if version_events:
        anchor_id = version_events[-1]["values"].get("temporal_anchor_id")
        if anchor_id:
            latest_anchor = get_effective_temporal_anchor(store, anchor_id)
    return {
        **record,
        "outbound_relations": outbound,
        "inbound_relations": inbound,
        "duplicate_occurrences": sorted(
            duplicates, key=lambda item: (item["label"].casefold(), item["id"])
        ),
        "latest_version_anchor": latest_anchor,
    }

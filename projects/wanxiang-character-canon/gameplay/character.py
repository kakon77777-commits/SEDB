from __future__ import annotations

from collections import Counter

from gameplay.common import StaticDataset, standard_claims


def _text_blob(payload: dict) -> str:
    return "\n".join(str(value) for value in payload.values() if isinstance(value, str))


def _mention_count(names: tuple[str, ...], texts: tuple[str, ...]) -> int:
    searchable = tuple(name for name in names if len(name.strip()) >= 2)
    if not searchable:
        return 0
    return sum(any(name in text for name in searchable) for text in texts)


def analyze_character_coverage(dataset: StaticDataset) -> dict:
    forms = dataset.by_kind("wanxiang_character_form_snapshot")
    identities = dataset.by_kind("wanxiang_character_identity")
    identity_ids = {record.record_id for record in identities}
    assets = dataset.by_kind("wanxiang_visual_asset_snapshot")
    extracted_assets = Counter(
        record.values.get("resource_numeric_id")
        for record in assets
        if record.values.get("extraction_status") == "EXTRACTED"
        and record.values.get("resource_numeric_id") is not None
    )
    event_payloads = tuple(
        record.values.get("source_row_payload") or {}
        for record in dataset.table("Event")
    )
    relation_payloads = tuple(
        record.values.get("source_row_payload") or {}
        for record in dataset.table("Relation")
    )
    dialog_payloads = tuple(
        record.values.get("source_row_payload") or {}
        for record in dataset.table("EventDialog")
    )
    event_texts = tuple(_text_blob(payload) for payload in event_payloads)
    relation_texts = tuple(_text_blob(payload) for payload in relation_payloads)
    dialog_texts = tuple(_text_blob(payload) for payload in dialog_payloads)
    hero_ids = Counter(
        form.values.get("hero_id")
        for form in forms
        if form.values.get("hero_id") is not None
    )
    details = []
    for form in forms:
        payload = form.values.get("source_row_payload") or {}
        hero_id = form.values.get("hero_id")
        names = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (
                    payload.get("Name"),
                    payload.get("NameTw"),
                    payload.get("IdName"),
                )
                if isinstance(value, str) and value.strip()
            )
        )
        dialog_portrait = f"Roles/Image/{hero_id}" if hero_id is not None else ""
        details.append(
            {
                "entity_id": form.record_id,
                "hero_id": hero_id,
                "identity_entity_id": form.values.get("identity_entity_id"),
                "name": payload.get("Name") or form.label,
                "has_description": bool(payload.get("Desc") or payload.get("BaseDesc")),
                "skill_count": len(form.values.get("skill_ids") or ()),
                "property_count": len(form.values.get("property_ids") or ()),
                "extracted_asset_count": extracted_assets.get(hero_id, 0),
                "event_text_mentions": _mention_count(names, event_texts),
                "relation_text_mentions": _mention_count(names, relation_texts),
                "dialog_text_mentions": _mention_count(names, dialog_texts),
                "dialog_portrait_rows": sum(
                    payload.get("Image") == dialog_portrait
                    for payload in dialog_payloads
                ) if dialog_portrait else 0,
            }
        )
    details.sort(key=lambda item: (str(item["hero_id"]), item["entity_id"]))
    metrics = {
        "forms": len(forms),
        "identities": len(identities),
        "forms_with_identity": sum(
            item["identity_entity_id"] in identity_ids for item in details
        ),
        "duplicate_hero_ids": sum(count > 1 for count in hero_ids.values()),
        "forms_with_description": sum(item["has_description"] for item in details),
        "forms_with_skills": sum(item["skill_count"] > 0 for item in details),
        "forms_with_properties": sum(item["property_count"] > 0 for item in details),
        "forms_with_extracted_asset": sum(
            item["extracted_asset_count"] > 0 for item in details
        ),
        "forms_with_event_text_mentions": sum(
            item["event_text_mentions"] > 0 for item in details
        ),
        "forms_with_relation_text_mentions": sum(
            item["relation_text_mentions"] > 0 for item in details
        ),
        "forms_with_dialog_text_mentions": sum(
            item["dialog_text_mentions"] > 0 for item in details
        ),
        "forms_with_dialog_portrait_rows": sum(
            item["dialog_portrait_rows"] > 0 for item in details
        ),
    }
    return {
        "analysis_name": "character-coverage",
        "source_tables": ["Hero", "Event", "EventDialog", "Relation"],
        "metrics": metrics,
        "details": {"forms": details},
        "claims": standard_claims(
            observed=f"The static catalog contains {len(forms)} Hero forms.",
            inferred="Uneven metadata, exact-name mention, portrait, and asset coverage may create uneven redesign effort.",
            unknown="Text matches do not establish narrative importance; runtime prominence and player attachment remain unmeasured.",
            falsifying_test="Observe representative routes and compare screen time with static coverage.",
            evidence=("Hero", "Event", "EventDialog", "Relation", "Visual Asset Map"),
        ),
    }

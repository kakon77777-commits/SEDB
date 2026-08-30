from __future__ import annotations

from collections import Counter

from gameplay.common import StaticDataset, standard_claims


def analyze_relationship_routes(dataset: StaticDataset) -> dict:
    routes = dataset.table("Relation")
    records = dataset.record_index()
    edges = [
        edge for edge in dataset.edges()
        if edge.values.get("edge_source_table") == "Relation"
    ]
    guide_steps = sum(
        len((route.values.get("guide_steps") or {}).get("guide_steps", []))
        for route in routes
    )
    missing_events = sum(
        edge.values.get("edge_target_table") == "Event"
        and edge.values.get("edge_resolution_status") == "missing_target"
        for edge in edges
    )
    target_counts = Counter(
        edge.values.get("edge_target_entity_id")
        for edge in edges
        if edge.values.get("edge_target_entity_id")
    )
    resolved_property_targets = sum(
        edge.values.get("edge_target_table") == "Property"
        and edge.values.get("edge_resolution_status") == "resolved"
        for edge in edges
    )
    resolved_event_targets = sum(
        edge.values.get("edge_target_table") == "Event"
        and edge.values.get("edge_resolution_status") == "resolved"
        for edge in edges
    )
    missing_property_targets = sum(
        edge.values.get("edge_target_table") == "Property"
        and edge.values.get("edge_resolution_status") == "missing_target"
        for edge in edges
    )
    edges_by_route: dict[str, list] = {}
    for edge in edges:
        edges_by_route.setdefault(
            edge.values.get("edge_source_entity_id"), []
        ).append(edge)
    route_details = []
    for route in routes:
        route_edges = edges_by_route.get(route.record_id, [])
        guide = (route.values.get("guide_steps") or {}).get("guide_steps", [])
        resolved_events = [
            records.get(edge.values.get("edge_target_entity_id"))
            for edge in route_edges
            if edge.values.get("edge_target_table") == "Event"
            and edge.values.get("edge_resolution_status") == "resolved"
        ]
        resolved_events = [record for record in resolved_events if record is not None]
        event_payloads = [
            record.values.get("source_row_payload") or {}
            for record in resolved_events
        ]
        prose = "\n".join(
            str(step.get("description") or "") for step in guide
        )
        route_details.append(
            {
                "entity_id": route.record_id,
                "source_record_id": route.values.get("source_record_id"),
                "guide_steps": len(guide),
                "resolved_event_targets": len(resolved_events),
                "missing_event_targets": sum(
                    edge.values.get("edge_target_table") == "Event"
                    and edge.values.get("edge_resolution_status") == "missing_target"
                    for edge in route_edges
                ),
                "resolved_property_targets": sum(
                    edge.values.get("edge_target_table") == "Property"
                    and edge.values.get("edge_resolution_status") == "resolved"
                    for edge in route_edges
                ),
                "events_with_map": sum(
                    payload.get("Map") not in (None, -1, "nil")
                    for payload in event_payloads
                ),
                "events_with_condition": sum(
                    payload.get("ConditionId") not in (None, -1, "nil")
                    for payload in event_payloads
                ),
                "battle_logic_events": sum(
                    payload.get("LogicType") == 3 for payload in event_payloads
                ),
                "guide_prose_has_time_cue": any(
                    token in prose for token in ("年", "月", "歲", "岁")
                ),
                "has_repeat_description": bool(
                    (route.values.get("source_row_payload") or {}).get("RepeatDesc")
                ),
            }
        )
    route_details.sort(key=lambda item: str(item["source_record_id"]))
    metrics = {
        "routes": len(routes),
        "guide_steps": guide_steps,
        "repeatable_fallback_rows": sum(
            bool((route.values.get("source_row_payload") or {}).get("RepeatDesc"))
            for route in routes
        ),
        "missing_event_targets": missing_events,
        "missing_property_targets": missing_property_targets,
        "resolved_event_targets": resolved_event_targets,
        "resolved_property_targets": resolved_property_targets,
        "shared_resolved_targets": sum(count > 1 for count in target_counts.values()),
        "routes_with_time_cues_in_guide_prose": sum(
            item["guide_prose_has_time_cue"] for item in route_details
        ),
        "routes_with_battle_logic_events": sum(
            item["battle_logic_events"] > 0 for item in route_details
        ),
    }
    return {
        "analysis_name": "relationship-routes",
        "source_tables": ["Relation", "Property", "Event"],
        "metrics": metrics,
        "details": {
            "routes": route_details,
            "time_cue_boundary": "PROSE_EVIDENCE_ONLY_NOT_A_STRUCTURED_CONDITION",
        },
        "claims": standard_claims(
            observed=f"The catalog contains {len(routes)} Relation rows and {guide_steps} normalized guide steps.",
            inferred="Shared event/property targets may couple routes through authored state.",
            unknown="Cross-character runtime effects and checklist feel remain unmeasured.",
            falsifying_test="Trace one relationship route and inspect effects on another route in an isolated save.",
            evidence=("Relation", "Property", "Event", dataset.rule_version),
        ),
    }

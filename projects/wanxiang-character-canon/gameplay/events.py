from __future__ import annotations

from collections import Counter
from statistics import fmean

from gameplay.common import StaticDataset, standard_claims


EVENT_GRAPH_TABLES = {
    "Event",
    "EventDialog",
    "EventSelection",
    "EventNormal",
    "EventPuzzle",
    "EventDice",
    "Battle",
}


def _distribution(values) -> dict[str, int]:
    return dict(
        sorted(
            ((str(key), count) for key, count in Counter(values).items()),
            key=lambda item: item[0],
        )
    )


def _tarjan(nodes: set[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            components.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return sorted(components, key=lambda component: component[0])


def analyze_event_network(dataset: StaticDataset) -> dict:
    edges = dataset.edges()
    resolved = [
        edge for edge in edges
        if edge.values.get("edge_resolution_status") == "resolved"
    ]
    missing = [
        edge for edge in edges
        if edge.values.get("edge_resolution_status") == "missing_target"
    ]
    records = dataset.record_index()
    nodes = {
        record.record_id
        for record in dataset.records
        if record.values.get("source_table") in EVENT_GRAPH_TABLES
    }
    adjacency = {node: set() for node in nodes}
    indegree = Counter({node: 0 for node in nodes})
    typed_edges = Counter()
    graph_edge_count = 0
    for edge in resolved:
        values = edge.values
        typed_edges[
            f"{values.get('edge_source_table')}.{values.get('edge_source_field')}"
            f"->{values.get('edge_target_table')}:resolved"
        ] += 1
        source = edge.values.get("edge_source_entity_id")
        target = edge.values.get("edge_target_entity_id")
        if source in nodes and target in nodes and target in records:
            if target not in adjacency[source]:
                adjacency[source].add(target)
                indegree[target] += 1
                graph_edge_count += 1
    for edge in missing:
        values = edge.values
        typed_edges[
            f"{values.get('edge_source_table')}.{values.get('edge_source_field')}"
            f"->{values.get('edge_target_table')}:missing_target"
        ] += 1
    components = _tarjan(nodes, adjacency)
    cycle_components = [
        component
        for component in components
        if len(component) > 1
        or (len(component) == 1 and component[0] in adjacency[component[0]])
    ]
    outdegree = {node: len(adjacency[node]) for node in nodes}
    top_outdegree = sorted(
        ({"entity_id": node, "degree": degree} for node, degree in outdegree.items()),
        key=lambda item: (-item["degree"], item["entity_id"]),
    )[:20]
    top_indegree = sorted(
        ({"entity_id": node, "degree": degree} for node, degree in indegree.items()),
        key=lambda item: (-item["degree"], item["entity_id"]),
    )[:20]
    metrics = {
        "nodes": len(nodes),
        "resolved_edges": len(resolved),
        "missing_edges": len(missing),
        "event_graph_resolved_edges": graph_edge_count,
        "event_graph_missing_edges": sum(
            edge.values.get("edge_source_entity_id") in nodes
            and edge.values.get("edge_target_table") in EVENT_GRAPH_TABLES
            for edge in missing
        ),
        "static_root_candidates": sum(indegree[node] == 0 for node in nodes),
        "terminal_nodes": sum(not adjacency[node] for node in nodes),
        "isolated_nodes": sum(indegree[node] == 0 and not adjacency[node] for node in nodes),
        "strongly_connected_components": len(components),
        "cycle_components": len(cycle_components),
    }
    return {
        "analysis_name": "event-network",
        "source_tables": sorted(EVENT_GRAPH_TABLES),
        "metrics": metrics,
        "details": {
            "typed_edges": dict(sorted(typed_edges.items())),
            "component_size_distribution": _distribution(
                len(component) for component in components
            ),
            "cycle_component_sample": cycle_components[:20],
            "top_indegree": top_indegree,
            "top_outdegree": top_outdegree,
        },
        "claims": standard_claims(
            observed=f"The static reference graph contains {len(resolved)} resolved edges and {len(missing)} missing targets.",
            inferred="Dense authored links may support reactivity, but static density does not establish runtime frequency.",
            unknown="Entry selection, guards, RNG order, and live reachability remain unknown.",
            falsifying_test="Trace one isolated save through event selection and compare runtime transitions with static edges.",
            evidence=("Event", "Reference Resolution", dataset.rule_version),
        ),
    }


def analyze_choice_consequence(dataset: StaticDataset) -> dict:
    selections = dataset.table("EventSelection")
    events = dataset.source_id_index("Event")
    option_count = 0
    enabled_count = 0
    repeated_destinations = 0
    convergence = 0
    condition_gated = 0
    missing_destinations = 0
    destination_ids = set()
    option_distribution = Counter()
    convergence_details = []
    for selection in selections:
        options = (selection.values.get("selection_options") or {}).get("options", [])
        destinations = [option.get("event_id") for option in options if option.get("event_id") not in (None, -1, "nil")]
        option_count += len(options)
        option_distribution[len(options)] += 1
        enabled_count += sum(option.get("can_execute") is not False for option in options)
        condition_gated += sum(
            option.get("condition_id") not in (None, -1, "nil")
            for option in options
        )
        repeated_destinations += len(destinations) - len(set(destinations))
        destination_ids.update(destinations)
        missing_destinations += sum(
            destination not in events for destination in destinations
        )
        result_ids = [
            (events.get(destination).values.get("source_row_payload") or {}).get("ResultId")
            for destination in destinations
            if events.get(destination) is not None
        ]
        result_ids = [value for value in result_ids if value not in (None, -1, "nil")]
        if len(set(destinations)) >= 2 and result_ids and len(set(result_ids)) < len(set(destinations)):
            convergence += 1
            convergence_details.append(
                {
                    "selection_entity_id": selection.record_id,
                    "source_record_id": selection.values.get("source_record_id"),
                    "destinations": sorted(set(destinations), key=str),
                    "result_ids": sorted(set(result_ids), key=str),
                }
            )
    metrics = {
        "selections": len(selections),
        "options": option_count,
        "enabled_options": enabled_count,
        "condition_gated_options": condition_gated,
        "distinct_event_destinations": len(destination_ids),
        "missing_event_destinations": missing_destinations,
        "repeated_destinations": repeated_destinations,
        "one_hop_result_convergence": convergence,
    }
    return {
        "analysis_name": "choice-consequence",
        "source_tables": ["EventSelection", "Event", "EventResult"],
        "metrics": metrics,
        "details": {
            "option_count_distribution": _distribution(
                value for value, count in option_distribution.items() for _ in range(count)
            ),
            "one_hop_convergence_sample": convergence_details[:50],
        },
        "claims": standard_claims(
            observed=f"The static catalog contains {len(selections)} selection records and {option_count} authored options.",
            inferred="Shared immediate Result IDs can indicate short-horizon authored convergence.",
            unknown="Player-visible availability and durable downstream divergence remain unknown.",
            falsifying_test="Replay two choices from the same isolated save and compare later eligible events and state.",
            evidence=("EventSelection", "Event", "EventResult"),
        ),
    }


def analyze_time_pacing(dataset: StaticDataset) -> dict:
    events = dataset.table("Event")
    payloads = [record.values.get("source_row_payload") or {} for record in events]
    costs = [payload.get("CostTime") for payload in payloads if isinstance(payload.get("CostTime"), (int, float)) and not isinstance(payload.get("CostTime"), bool)]
    map_density = Counter(payload.get("Map") for payload in payloads if payload.get("Map") not in (None, -1, "nil"))
    priorities = [
        payload.get("Priority")
        for payload in payloads
        if payload.get("Priority") not in (None, "nil")
    ]
    weights = [
        payload.get("Weight")
        for payload in payloads
        if payload.get("Weight") not in (None, "nil")
    ]
    logic_types = [
        payload.get("LogicType")
        for payload in payloads
        if payload.get("LogicType") not in (None, "nil")
    ]
    condition_payloads = [
        record.values.get("source_row_payload") or {}
        for record in dataset.table("Condition")
    ]
    condition_types = [
        payload.get(f"ConditionType{slot}")
        for payload in condition_payloads
        for slot in range(10)
        if payload.get(f"ConditionType{slot}") not in (None, -1, "nil")
    ]
    metrics = {
        "events": len(events),
        "events_with_cost_time": len(costs),
        "cost_time_average": float(fmean(costs)) if costs else 0.0,
        "cost_time_min": min(costs) if costs else None,
        "cost_time_max": max(costs) if costs else None,
        "once_in_turn": sum(payload.get("OnceInTurn") is True for payload in payloads),
        "repeatable_times": sum(payload.get("Times") == -1 for payload in payloads),
        "events_with_map": sum(
            payload.get("Map") not in (None, -1, "nil") for payload in payloads
        ),
        "events_with_condition": sum(
            payload.get("ConditionId") not in (None, -1, "nil")
            for payload in payloads
        ),
        "map_event_density": _distribution(
            value for value, count in map_density.items() for _ in range(count)
        ),
    }
    return {
        "analysis_name": "time-pacing",
        "source_tables": ["Event", "Condition", "Map"],
        "metrics": metrics,
        "details": {
            "cost_time_distribution": _distribution(costs),
            "priority_distribution": _distribution(priorities),
            "weight_distribution": _distribution(weights),
            "logic_type_distribution": _distribution(logic_types),
            "condition_type_distribution": _distribution(condition_types),
            "condition_type_semantics": "UNKNOWN_NUMERIC_ENUMS_NOT_UPGRADED_TO_YEAR_OR_MONTH",
        },
        "claims": standard_claims(
            observed=f"The static Event table contains {len(events)} rows with explicit cost and repetition fields.",
            inferred="Cost and repetition distributions provide tuning surfaces for authored pacing.",
            unknown="Actual waiting, choice pressure, and event frequency are not measured statically.",
            falsifying_test="Record action/time/resource deltas across ordinary isolated turns.",
            evidence=("Event", "Condition", "Map"),
        ),
    }

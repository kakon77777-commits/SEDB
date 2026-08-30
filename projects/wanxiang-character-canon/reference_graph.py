from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from catalog_identity import (
    canonical_source_id,
    reference_edge_entity_id,
)
from catalog_source import CatalogRow, CatalogRows, catalog_row_entity_id
from reference_rules import (
    DIRECT_REFERENCE_RULES,
    EVENT_LOGIC_METADATA_EVIDENCE,
    RULE_VERSION,
    ReferenceRule,
    resolve_event_logic_target,
)
from source import SourceEntity


class ReferenceGraphError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class ReferenceEdge:
    source_entity_id: str
    source_table: str
    source_field: str
    slot: int
    raw_value: Any
    target_table: str | None
    target_source_id: Any
    target_entity_id: str | None
    resolution_status: str
    rule_id: str
    evidence: str


def _is_sentinel(value: Any) -> bool:
    return value is None or value == -1 or value == "-1" or (
        isinstance(value, str) and value.strip().lower() == "nil"
    )


def normalize_repeated_operations(
    table: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if table == "Condition":
        conditions = []
        for slot in range(10):
            condition_type = payload.get(f"ConditionType{slot}")
            if _is_sentinel(condition_type):
                continue
            conditions.append(
                {
                    "slot": slot,
                    "type": condition_type,
                    "subtype": payload.get(f"ConditionSubType{slot}"),
                    "operator": payload.get(f"ConditionOpt{slot}"),
                    "value": payload.get(f"ConditionValue{slot}"),
                }
            )
        return {"conditions": conditions, "or": bool(payload.get("OR"))}
    if table == "EventResult":
        results = []
        for slot in range(10):
            result_type = payload.get(f"ResultType{slot}")
            if _is_sentinel(result_type):
                continue
            results.append(
                {
                    "slot": slot,
                    "type": result_type,
                    "subtype": payload.get(f"ResultSubType{slot}"),
                    "operator": payload.get(f"ResultOpt{slot}"),
                    "value0": payload.get(f"Result0Value{slot}"),
                    "value1": payload.get(f"Result1Value{slot}"),
                    "condition_id": payload.get(f"ConditionId{slot}"),
                    "talent_type": payload.get(f"TalentType{slot}"),
                }
            )
        return {"results": results}
    if table == "EventSelection":
        options = []
        for slot in range(20):
            condition_id = payload.get(f"Condition{slot}")
            selection = payload.get(f"Selection{slot}")
            event_id = payload.get(f"EventId{slot}")
            if all(_is_sentinel(value) for value in (condition_id, selection, event_id)):
                continue
            options.append(
                {
                    "slot": slot,
                    "condition_id": condition_id,
                    "selection": selection,
                    "event_id": event_id,
                    "can_execute": payload.get(f"CanExec{slot}"),
                    "tip_text": payload.get(f"TipText{slot}"),
                    "selection_tw": payload.get(f"SelectionTw{slot}"),
                    "tip_text_tw": payload.get(f"TipTextTw{slot}"),
                }
            )
        return {"options": options}
    if table == "Relation":
        guide_steps = []
        for slot in range(10):
            description = payload.get(f"GuidDesc{slot}")
            event_ids = payload.get(f"GuidEvent{slot}")
            if _is_sentinel(description) and _is_sentinel(event_ids):
                continue
            guide_steps.append(
                {
                    "slot": slot,
                    "description": description,
                    "description_tw": payload.get(f"GuidDescTw{slot}"),
                    "event_ids": event_ids,
                }
            )
        return {"guide_steps": guide_steps}
    return {}


def _target_index(build_id: int, catalog: CatalogRows) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for row in catalog.rows:
        if row.source_id is None:
            continue
        if row.table == "Hero" and row.payload.get("Type") != 0:
            continue
        key = (row.table, canonical_source_id(row.source_id))
        if key in index:
            raise ReferenceGraphError("duplicate_target_identity", str(key))
        index[key] = catalog_row_entity_id(build_id, row)
    return index


def _typed_target_id(
    value: Any,
    target_table: str,
    index: dict[tuple[str, str], str],
) -> Any:
    try:
        if (target_table, canonical_source_id(value)) in index:
            return value
    except ValueError:
        return value
    if isinstance(value, str) and re.fullmatch(r"[-+]?\d+", value.strip()):
        numeric = int(value)
        if (target_table, canonical_source_id(numeric)) in index:
            return numeric
    return value


def _edge(
    *,
    source_entity_id: str,
    source_table: str,
    source_field: str,
    slot: int,
    raw_value: Any,
    target_table: str | None,
    target_source_id: Any,
    rule_id: str,
    evidence: str,
    index: dict[tuple[str, str], str],
) -> ReferenceEdge:
    if target_table is None:
        return ReferenceEdge(
            source_entity_id,
            source_table,
            source_field,
            slot,
            raw_value,
            None,
            target_source_id,
            None,
            "unknown_semantics",
            rule_id,
            evidence,
        )
    typed_id = _typed_target_id(target_source_id, target_table, index)
    target_entity_id = index.get((target_table, canonical_source_id(typed_id)))
    return ReferenceEdge(
        source_entity_id,
        source_table,
        source_field,
        slot,
        raw_value,
        target_table,
        typed_id,
        target_entity_id,
        "resolved" if target_entity_id is not None else "missing_target",
        rule_id,
        evidence,
    )


def _values(value: Any, split_ampersand: bool) -> tuple[Any, ...]:
    if _is_sentinel(value):
        return ()
    if not split_ampersand or not isinstance(value, str):
        return (value,)
    values = tuple(part.strip() for part in value.split("&") if part.strip())
    if len(values) != len(set(values)):
        raise ReferenceGraphError("duplicate_multi_reference", value)
    return values


def _direct_edges(
    build_id: int,
    row: CatalogRow,
    rule: ReferenceRule,
    index: dict[tuple[str, str], str],
) -> list[ReferenceEdge]:
    source_entity_id = catalog_row_entity_id(build_id, row)
    edges = []
    for field in sorted(row.payload):
        if re.fullmatch(rule.field_pattern, field) is None:
            continue
        raw = row.payload.get(field)
        for slot, target_id in enumerate(_values(raw, rule.split_ampersand)):
            edges.append(
                _edge(
                    source_entity_id=source_entity_id,
                    source_table=row.table,
                    source_field=field,
                    slot=slot,
                    raw_value=raw,
                    target_table=rule.target_table,
                    target_source_id=target_id,
                    rule_id=rule.rule_id,
                    evidence=rule.evidence,
                    index=index,
                )
            )
    return edges


def _event_logic_edge(
    build_id: int,
    row: CatalogRow,
    index: dict[tuple[str, str], str],
) -> ReferenceEdge | None:
    raw_id = row.payload.get("LogicId")
    if _is_sentinel(raw_id):
        return None
    logic_type = row.payload.get("LogicType")
    target_table = resolve_event_logic_target(logic_type)
    return _edge(
        source_entity_id=catalog_row_entity_id(build_id, row),
        source_table="Event",
        source_field="LogicId",
        slot=0,
        raw_value=raw_id,
        target_table=target_table,
        target_source_id=raw_id,
        rule_id=f"event.logic-type-{logic_type}",
        evidence=EVENT_LOGIC_METADATA_EVIDENCE,
        index=index,
    )


def _edge_entity(build_id: int, edge: ReferenceEdge, row: CatalogRow) -> SourceEntity:
    values = {
        "source_build_id": build_id,
        "record_status": "STATIC_REFERENCE",
        "edge_source_entity_id": edge.source_entity_id,
        "edge_source_table": edge.source_table,
        "edge_source_field": edge.source_field,
        "edge_slot": edge.slot,
        "edge_raw_value": edge.raw_value,
        "edge_target_table": edge.target_table,
        "edge_target_source_id": edge.target_source_id,
        "edge_target_entity_id": edge.target_entity_id,
        "edge_resolution_status": edge.resolution_status,
        "edge_rule_id": edge.rule_id,
        "edge_rule_version": RULE_VERSION,
        "edge_evidence_level": edge.evidence,
        "edge_claim_boundary": "STATIC_LINK_ONLY_RUNTIME_REACHABILITY_NOT_PROVEN",
    }
    values = {key: value for key, value in values.items() if value is not None}
    entity_id = reference_edge_entity_id(
        edge.source_entity_id,
        edge.source_field,
        edge.slot,
        edge.target_table,
        edge.target_source_id,
    )
    return SourceEntity(
        entity_id=entity_id,
        kind="wanxiang_reference_edge_snapshot",
        label=f"{edge.source_table}.{edge.source_field} -> {edge.target_table or 'unknown'}",
        values=values,
        cell_source=f"wanxiang:{row.workbook_path}#row={row.row_number}",
    )


def build_reference_edges(
    build_id: int,
    catalog: CatalogRows,
) -> tuple[SourceEntity, ...]:
    index = _target_index(build_id, catalog)
    row_by_source = {
        catalog_row_entity_id(build_id, row): row for row in catalog.rows
    }
    edges: list[ReferenceEdge] = []
    for row in catalog.rows:
        if row.table == "Hero" and row.payload.get("Type") != 0:
            continue
        for rule in DIRECT_REFERENCE_RULES:
            if rule.source_table == row.table:
                edges.extend(_direct_edges(build_id, row, rule, index))
        if row.table == "Event":
            logic_edge = _event_logic_edge(build_id, row, index)
            if logic_edge is not None:
                edges.append(logic_edge)
    entities = [
        _edge_entity(build_id, edge, row_by_source[edge.source_entity_id])
        for edge in edges
    ]
    entities.sort(key=lambda entity: entity.entity_id)
    if len({entity.entity_id for entity in entities}) != len(entities):
        raise ReferenceGraphError("duplicate_edge_entity_id", "reference graph")
    return tuple(entities)

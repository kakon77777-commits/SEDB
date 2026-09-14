from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

from isql_core.semantic_addressing import ExactStateRef

from .active_domain import ActiveDomainPlan
from .adapter import SEDBReadOnlyAdapter, SEDBReadOnlyAdapterError


PARTIAL_ENTITY_PROJECTION_SCHEMA = "isql-sedb.partial-entity-projection/v0.1"
PARTIAL_DOMAIN_MATERIALIZATION_SCHEMA = "isql-sedb.partial-domain-materialization/v0.1"


class FieldProjectionState(str, Enum):
    PRESENT = "present"
    BLANK = "blank"
    UNKNOWN = "unknown"
    ABSENT = "absent"
    UNLOADED = "unloaded"


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SEDBReadOnlyAdapterError("PARTIAL_PROJECTION_NOT_CANONICAL_JSON") from exc


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class ProjectionFieldRef:
    ordinal: int
    field_id: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_ORDINAL_INVALID")
        if not isinstance(self.field_id, str) or not self.field_id:
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_ID_INVALID")
        if not isinstance(self.key, str) or not self.key:
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_KEY_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {"ordinal": self.ordinal, "field_id": self.field_id, "key": self.key}


@dataclass(frozen=True, slots=True)
class PartialFieldSlot:
    field: ProjectionFieldRef
    state: FieldProjectionState
    value: object = None
    source: str | None = None
    confidence: float | None = None
    updated_at: str | None = None
    unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field, ProjectionFieldRef):
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_REF_REQUIRED")
        if not isinstance(self.state, FieldProjectionState):
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_STATE_INVALID")

        if self.state is FieldProjectionState.PRESENT:
            if self.value is None:
                raise SEDBReadOnlyAdapterError("PARTIAL_PRESENT_VALUE_REQUIRED")
            if self.updated_at is None:
                raise SEDBReadOnlyAdapterError("PARTIAL_PRESENT_TIMESTAMP_REQUIRED")
            if self.unknown_reason is not None:
                raise SEDBReadOnlyAdapterError("PARTIAL_PRESENT_UNKNOWN_REASON_FORBIDDEN")
        elif self.state is FieldProjectionState.BLANK:
            if self.value is not None:
                raise SEDBReadOnlyAdapterError("PARTIAL_BLANK_MUST_BE_NULL")
            if self.updated_at is None:
                raise SEDBReadOnlyAdapterError("PARTIAL_BLANK_TIMESTAMP_REQUIRED")
            if self.unknown_reason is not None:
                raise SEDBReadOnlyAdapterError("PARTIAL_BLANK_UNKNOWN_REASON_FORBIDDEN")
        elif self.state is FieldProjectionState.UNKNOWN:
            if self.value is not None or self.source is not None or self.confidence is not None or self.updated_at is not None:
                raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_PAYLOAD_FORBIDDEN")
            if not isinstance(self.unknown_reason, str) or not self.unknown_reason.strip():
                raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_REASON_REQUIRED")
        elif self.state in (FieldProjectionState.ABSENT, FieldProjectionState.UNLOADED):
            if any(value is not None for value in (
                self.value,
                self.source,
                self.confidence,
                self.updated_at,
                self.unknown_reason,
            )):
                raise SEDBReadOnlyAdapterError("PARTIAL_NONLOADED_PAYLOAD_FORBIDDEN")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "field": self.field.to_dict(),
            "state": self.state.value,
        }
        if self.state in (FieldProjectionState.PRESENT, FieldProjectionState.BLANK):
            payload.update({
                "value": self.value,
                "source": self.source,
                "confidence": self.confidence,
                "updated_at": self.updated_at,
            })
        elif self.state is FieldProjectionState.UNKNOWN:
            payload["unknown_reason"] = self.unknown_reason
        return payload


@dataclass(frozen=True, slots=True)
class PartialEntityProjection:
    source_exact: ExactStateRef
    view_id: str
    query_address_sha256: str
    fields: tuple[PartialFieldSlot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_exact, ExactStateRef):
            raise SEDBReadOnlyAdapterError("PARTIAL_SOURCE_EXACT_REQUIRED")
        if not isinstance(self.view_id, str) or not self.view_id:
            raise SEDBReadOnlyAdapterError("PARTIAL_VIEW_ID_INVALID")
        if not isinstance(self.query_address_sha256, str) or len(self.query_address_sha256) != 64:
            raise SEDBReadOnlyAdapterError("PARTIAL_QUERY_HASH_INVALID")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELDS_REQUIRED")
        ordinals = [slot.field.ordinal for slot in self.fields]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise SEDBReadOnlyAdapterError("PARTIAL_FIELD_ORDER_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PARTIAL_ENTITY_PROJECTION_SCHEMA,
            "source_exact": self.source_exact.to_dict(),
            "view_id": self.view_id,
            "query_address_sha256": self.query_address_sha256,
            "fields": [slot.to_dict() for slot in self.fields],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def projection_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def state_for_field(self, field_id: str) -> FieldProjectionState:
        for slot in self.fields:
            if slot.field.field_id == field_id:
                return slot.state
        raise KeyError(field_id)


@dataclass(frozen=True, slots=True)
class PartialDomainMaterialization:
    plan_sha256: str
    projections: tuple[PartialEntityProjection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan_sha256, str) or len(self.plan_sha256) != 64:
            raise SEDBReadOnlyAdapterError("PARTIAL_PLAN_HASH_INVALID")
        if not isinstance(self.projections, tuple):
            raise SEDBReadOnlyAdapterError("PARTIAL_PROJECTIONS_REQUIRED")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PARTIAL_DOMAIN_MATERIALIZATION_SCHEMA,
            "plan_sha256": self.plan_sha256,
            "projections": [projection.to_dict() for projection in self.projections],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def materialization_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _all_view_fields(adapter: SEDBReadOnlyAdapter, view_id: str) -> tuple[ProjectionFieldRef, ...]:
    with adapter._connect() as conn:
        adapter._require_schema(conn)
        view = conn.execute("SELECT id FROM task_views WHERE id=?", (view_id,)).fetchone()
        if view is None:
            raise KeyError(f"SEDB task view not found: {view_id}")
        rows = conn.execute(
            """
            SELECT tvf.ordinal,f.id,f.key
            FROM task_view_fields tvf
            JOIN fields f ON f.id=tvf.field_id
            WHERE tvf.view_id=?
            ORDER BY tvf.ordinal,f.id
            LIMIT 100001
            """,
            (view_id,),
        ).fetchall()
    if len(rows) > 100000:
        raise SEDBReadOnlyAdapterError("PARTIAL_VIEW_FIELD_METADATA_TOO_LARGE")
    return tuple(
        ProjectionFieldRef(
            ordinal=int(row["ordinal"]),
            field_id=str(row["id"]),
            key=str(row["key"]),
        )
        for row in rows
    )


def _plan_hash(plan: ActiveDomainPlan) -> str:
    return _sha256_json(plan.to_dict())


def materialize_partial_domain(
    adapter: SEDBReadOnlyAdapter,
    plan: ActiveDomainPlan,
    *,
    unknown_cells: Mapping[tuple[str, str], str] | None = None,
) -> PartialDomainMaterialization:
    if not isinstance(adapter, SEDBReadOnlyAdapter):
        raise SEDBReadOnlyAdapterError("PARTIAL_ADAPTER_REQUIRED")
    if not isinstance(plan, ActiveDomainPlan):
        raise SEDBReadOnlyAdapterError("PARTIAL_ACTIVE_DOMAIN_PLAN_REQUIRED")

    unknown_cells = {} if unknown_cells is None else dict(unknown_cells)
    selected_entity_ids = {entry.exact.entity_id for entry in plan.selected_entities}
    selected_field_ids = {field.field_id for field in plan.selected_fields}
    for key, reason in unknown_cells.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_CELL_KEY_INVALID")
        entity_id, field_id = key
        if entity_id not in selected_entity_ids or field_id not in selected_field_ids:
            raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_CELL_OUTSIDE_SELECTED_DOMAIN")
        if not isinstance(reason, str) or not reason.strip():
            raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_REASON_REQUIRED")

    all_fields = _all_view_fields(adapter, plan.view_id)
    all_ids = {field.field_id for field in all_fields}
    if not selected_field_ids.issubset(all_ids):
        raise SEDBReadOnlyAdapterError("PARTIAL_PLAN_FIELD_NOT_IN_VIEW")

    projections: list[PartialEntityProjection] = []
    for entity_plan in plan.selected_entities:
        # Correctness-first gate: D1 verifies the full current exact snapshot.
        # D3 then projects selected fields. This is not yet a proof-carrying
        # partial read and does not claim full-read bandwidth reduction.
        snapshot = adapter.read_current_exact(entity_plan.exact)
        cells_by_field = {cell.field.field_id: cell for cell in snapshot.cells}
        slots: list[PartialFieldSlot] = []

        for field in all_fields:
            if field.field_id not in selected_field_ids:
                slots.append(PartialFieldSlot(field=field, state=FieldProjectionState.UNLOADED))
                continue

            cell = cells_by_field.get(field.field_id)
            explicit_unknown = unknown_cells.get((snapshot.entity_id, field.field_id))
            if cell is not None and explicit_unknown is not None:
                raise SEDBReadOnlyAdapterError("PARTIAL_UNKNOWN_CONFLICTS_WITH_PRESENT_CELL")
            if cell is None and explicit_unknown is not None:
                slots.append(PartialFieldSlot(
                    field=field,
                    state=FieldProjectionState.UNKNOWN,
                    unknown_reason=explicit_unknown,
                ))
            elif cell is None:
                slots.append(PartialFieldSlot(field=field, state=FieldProjectionState.ABSENT))
            elif cell.value is None:
                slots.append(PartialFieldSlot(
                    field=field,
                    state=FieldProjectionState.BLANK,
                    value=None,
                    source=cell.source,
                    confidence=cell.confidence,
                    updated_at=cell.updated_at,
                ))
            else:
                slots.append(PartialFieldSlot(
                    field=field,
                    state=FieldProjectionState.PRESENT,
                    value=cell.value,
                    source=cell.source,
                    confidence=cell.confidence,
                    updated_at=cell.updated_at,
                ))

        projections.append(PartialEntityProjection(
            source_exact=entity_plan.exact,
            view_id=plan.view_id,
            query_address_sha256=plan.query_address_sha256,
            fields=tuple(slots),
        ))

    return PartialDomainMaterialization(
        plan_sha256=_plan_hash(plan),
        projections=tuple(projections),
    )

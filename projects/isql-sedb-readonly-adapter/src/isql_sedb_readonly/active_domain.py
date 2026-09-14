from __future__ import annotations

from dataclasses import dataclass

from isql_core.semantic_addressing import (
    ExactStateRef,
    SemanticAddress,
    SemanticAddressIndex,
    resolve_semantic_candidates,
)

from .adapter import SEDBReadOnlyAdapter, SEDBReadOnlyAdapterError


@dataclass(frozen=True, slots=True)
class ActiveDomainBudget:
    max_candidate_scan: int = 64
    max_entities: int = 16
    max_fields: int = 32
    max_cells: int = 256

    def __post_init__(self) -> None:
        for name, value in (
            ("max_candidate_scan", self.max_candidate_scan),
            ("max_entities", self.max_entities),
            ("max_fields", self.max_fields),
            ("max_cells", self.max_cells),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SEDBReadOnlyAdapterError(f"ACTIVE_DOMAIN_{name.upper()}_INVALID")
        if self.max_entities > self.max_candidate_scan:
            raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_ENTITY_BUDGET_EXCEEDS_SCAN")
        if self.max_candidate_scan > 10_000:
            raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_SCAN_LIMIT_TOO_LARGE")
        if self.max_fields > 10_000 or self.max_cells > 1_000_000:
            raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_RESOURCE_LIMIT_TOO_LARGE")


@dataclass(frozen=True, slots=True, order=True)
class TaskFieldSupport:
    ordinal: int
    field_id: str
    key: str
    label: str
    value_type: str
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "field_id": self.field_id,
            "key": self.key,
            "label": self.label,
            "value_type": self.value_type,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ActiveDomainEntity:
    exact: ExactStateRef
    semantic_score: float
    present_cell_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "exact": self.exact.to_dict(),
            "semantic_score": self.semantic_score,
            "present_cell_count": self.present_cell_count,
        }


@dataclass(frozen=True, slots=True)
class ActiveDomainPlan:
    view_id: str
    query_address_sha256: str
    profile_entry_count: int
    probe_count: int
    total_view_fields: int
    selected_fields: tuple[TaskFieldSupport, ...]
    selected_entities: tuple[ActiveDomainEntity, ...]
    selected_cell_count: int
    field_support_truncated: bool
    candidate_scan_truncated: bool
    entity_budget_exhausted: bool
    cell_budget_exhausted: bool
    omitted_for_cell_budget: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "isql-sedb.active-domain-plan/v0.1",
            "view_id": self.view_id,
            "query_address_sha256": self.query_address_sha256,
            "profile_entry_count": self.profile_entry_count,
            "probe_count": self.probe_count,
            "total_view_fields": self.total_view_fields,
            "selected_fields": [field.to_dict() for field in self.selected_fields],
            "selected_entities": [entity.to_dict() for entity in self.selected_entities],
            "selected_cell_count": self.selected_cell_count,
            "field_support_truncated": self.field_support_truncated,
            "candidate_scan_truncated": self.candidate_scan_truncated,
            "entity_budget_exhausted": self.entity_budget_exhausted,
            "cell_budget_exhausted": self.cell_budget_exhausted,
            "omitted_for_cell_budget": list(self.omitted_for_cell_budget),
        }


def _read_task_field_support(
    adapter: SEDBReadOnlyAdapter,
    view_id: str,
    *,
    max_fields: int,
) -> tuple[int, tuple[TaskFieldSupport, ...]]:
    if not isinstance(view_id, str) or not view_id or "\x00" in view_id:
        raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_VIEW_ID_INVALID")
    with adapter._connect() as conn:
        adapter._require_schema(conn)
        view = conn.execute("SELECT id FROM task_views WHERE id=?", (view_id,)).fetchone()
        if view is None:
            raise KeyError(f"SEDB task view not found: {view_id}")
        total = int(conn.execute(
            "SELECT COUNT(*) FROM task_view_fields WHERE view_id=?",
            (view_id,),
        ).fetchone()[0])
        rows = conn.execute(
            """
            SELECT tvf.ordinal,f.id,f.key,f.label,f.value_type,f.status
            FROM task_view_fields tvf
            JOIN fields f ON f.id=tvf.field_id
            WHERE tvf.view_id=?
            ORDER BY tvf.ordinal,f.id
            LIMIT ?
            """,
            (view_id, max_fields),
        ).fetchall()
    fields = tuple(
        TaskFieldSupport(
            ordinal=int(row["ordinal"]),
            field_id=str(row["id"]),
            key=str(row["key"]),
            label=str(row["label"]),
            value_type=str(row["value_type"]),
            status=str(row["status"]),
        )
        for row in rows
    )
    return total, fields


def _count_selected_cells(
    adapter: SEDBReadOnlyAdapter,
    entity_id: str,
    field_ids: tuple[str, ...],
) -> int:
    if not field_ids:
        return 0
    placeholders = ",".join("?" for _ in field_ids)
    sql = (
        "SELECT COUNT(*) FROM cells "
        f"WHERE entity_id=? AND field_id IN ({placeholders})"
    )
    with adapter._connect() as conn:
        count = conn.execute(sql, (entity_id, *field_ids)).fetchone()[0]
    return int(count)


def plan_active_domain(
    adapter: SEDBReadOnlyAdapter,
    query: SemanticAddress,
    index: SemanticAddressIndex,
    *,
    view_id: str,
    budget: ActiveDomainBudget = ActiveDomainBudget(),
) -> ActiveDomainPlan:
    if not isinstance(adapter, SEDBReadOnlyAdapter):
        raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_ADAPTER_REQUIRED")
    if not isinstance(budget, ActiveDomainBudget):
        raise SEDBReadOnlyAdapterError("ACTIVE_DOMAIN_BUDGET_REQUIRED")

    total_fields, fields = _read_task_field_support(
        adapter,
        view_id,
        max_fields=budget.max_fields,
    )
    field_ids = tuple(field.field_id for field in fields)

    resolved = resolve_semantic_candidates(
        query,
        index,
        top_k=budget.max_candidate_scan,
    )

    selected: list[ActiveDomainEntity] = []
    omitted_for_cell_budget: list[str] = []
    selected_cells = 0

    for candidate in resolved.candidates:
        if len(selected) >= budget.max_entities:
            break

        # Fail closed if the derived semantic index is stale relative to the
        # current SEDB state. Planning never silently substitutes a new state.
        adapter.read_current_exact(candidate.exact)

        present_cells = _count_selected_cells(
            adapter,
            candidate.exact.entity_id,
            field_ids,
        )
        if selected_cells + present_cells > budget.max_cells:
            omitted_for_cell_budget.append(candidate.exact.entity_id)
            continue

        selected.append(ActiveDomainEntity(
            exact=candidate.exact,
            semantic_score=candidate.score,
            present_cell_count=present_cells,
        ))
        selected_cells += present_cells

    candidate_scan_truncated = resolved.probe_count > len(resolved.candidates)
    entity_budget_exhausted = (
        len(selected) >= budget.max_entities
        and len(resolved.candidates) > len(selected)
    )

    return ActiveDomainPlan(
        view_id=view_id,
        query_address_sha256=resolved.query_address_sha256,
        profile_entry_count=resolved.profile_entry_count,
        probe_count=resolved.probe_count,
        total_view_fields=total_fields,
        selected_fields=fields,
        selected_entities=tuple(selected),
        selected_cell_count=selected_cells,
        field_support_truncated=total_fields > len(fields),
        candidate_scan_truncated=candidate_scan_truncated,
        entity_budget_exhausted=entity_budget_exhausted,
        cell_budget_exhausted=bool(omitted_for_cell_budget),
        omitted_for_cell_budget=tuple(omitted_for_cell_budget),
    )

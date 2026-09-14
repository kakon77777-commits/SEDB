# ISQL–SEDB Active Domain Planner v0.1

**Status:** Internal / Experimental  
**Depends on:** ISQL A2 + SEDB D1 read-only adapter  
**Mutation authority:** none

---

## 1. Purpose

D2 moves the integration from exact entity lookup to finite task-local materialization planning.

The planner combines:

$$
\boxed{
E_Q
=
\text{semantic candidate entities}
}
$$

with SEDB's existing task-view field support:

$$
\boxed{
F_Q
\subseteq
F
}
$$

and explicit resource limits:

$$
B_Q
=
(
N_{scan},N_E,N_F,N_C
).
$$

The result is a finite plan:

$$
\boxed{
D_Q
=
(E_Q^{*},F_Q^{*})
}
$$

where both entity and field support are bounded before materialization.

---

## 2. Reuse rather than replacement

D2 does not invent another SEDB task-view system.

It reads the existing:

```text
task_views
task_view_fields
```

schema and preserves `ordinal` field order.

Therefore task-local field support remains owned by SEDB; the adapter only consumes it.

---

## 3. Budget dimensions

`ActiveDomainBudget` declares:

```text
max_candidate_scan
max_entities
max_fields
max_cells
```

These limits have different meanings.

### Candidate scan

Bounds how many ranked semantic candidates may proceed from A2 into active-domain evaluation.

### Entity budget

Bounds the number of exact entities admitted to the domain.

### Field budget

Bounds task-view field support by preserving the view's existing ordinal order and truncating after `max_fields`.

### Cell budget

Bounds the number of currently present SEDB cells across admitted entities and selected fields.

---

## 4. Selection order

The planner preserves A2 semantic ranking.

For each candidate in order:

1. verify its exact current SEDB state through D1;
2. count cells present in selected task-view fields;
3. if adding the entity would exceed `max_cells`, mark it omitted for cell budget and continue;
4. otherwise admit it;
5. stop after `max_entities` entities.

This intentionally allows a lower-ranked but cheaper candidate to fit when a higher-ranked candidate exceeds the remaining resource budget.

Therefore:

$$
\boxed{
\text{Semantic Rank}
\neq
\text{Unconditional Materialization Priority}
}
$$

The actual decision is:

$$
\boxed{
\text{Relevance}
+
\text{Budget}
\rightarrow
\text{Finite Working Set}
}
$$

---

## 5. Exact-state gate

D2 never plans a stale exact candidate silently.

Before cost counting, every candidate is checked using D1:

$$
\operatorname{SHA256}(X_{current})
\stackrel{?}{=}
H_{candidate}.
$$

If not equal, planning fails closed with `SEDBExactStateMismatch`.

The semantic index may be rebuilt or a future historical-state resolver may satisfy the old exact reference.

---

## 6. Planning is not materialization

`ActiveDomainPlan` contains:

- exact entity refs;
- semantic scores;
- selected task-view fields;
- present-cell counts;
- explicit truncation/budget flags.

It does not return full entity payloads.

Thus:

$$
\boxed{
\text{Plan}(D_Q)
\neq
\operatorname{Materialize}(D_Q)
}
$$

A later layer may fetch only the planned subset while preserving exact-state verification semantics.

---

## 7. Explicit truncation

The plan records:

- `field_support_truncated`;
- `candidate_scan_truncated`;
- `entity_budget_exhausted`;
- `cell_budget_exhausted`;
- entity IDs omitted specifically for cell budget.

No resource truncation is hidden.

---

## 8. Current limitations

D2 does not yet implement:

- semantic query → dynamic field selection;
- dependency closure between entities;
- partial-state cryptographic membership proofs;
- historical exact-state resolution;
- bytes/network budget;
- latency-aware placement;
- predictive prefetch;
- physical/cloud resolver;
- write authority.

The task view is an already-declared $F_Q$ supplied by SEDB.

---

## 9. Next step

The next useful boundary is a **partial materializer**:

$$
D_Q
\rightarrow
\text{selected exact entity state}
\rightarrow
\text{selected field cells}
$$

with a clear distinction between:

```text
unloaded
unknown
absent
blank
```

That step must not call a partial projection the same thing as the full D1 exact snapshot.

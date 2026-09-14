# ISQL–SEDB Partial Materialization v0.1

**Status:** Internal / Experimental  
**Depends on:** A2 Dual Addressing + D1 Exact Read + D2 Active Domain  
**Mutation authority:** none

---

## 1. Purpose

D3 consumes a verified `ActiveDomainPlan` and creates a task-local partial projection for each selected entity.

The abstraction is:

$$
\boxed{
D_Q
\rightarrow
P_{D_Q}(X)
}
$$

with the mandatory identity rule:

$$
\boxed{
P_{D_Q}(X)
\neq
X
}
$$

unless a future protocol separately proves that the projection is complete and byte-identical to the full exact object.

D3 therefore carries two identities:

1. the source full-state exact reference $(E,H(X))$;
2. a separate SHA-256 over the partial projection bytes $H(P_{D_Q}(X))$.

These hashes are not interchangeable.

---

## 2. Five field states

D3 explicitly separates five states.

### `present`

The field is selected by D2 and a SEDB cell row exists with a non-null JSON value.

### `blank`

The field is selected and a SEDB cell row exists whose explicit JSON value is `null`.

A blank slot retains the cell's source, confidence, and update timestamp.

### `absent`

The field is selected, its definition exists in the task view, but no cell row exists for the entity.

D3 does not infer epistemic uncertainty from absence.

### `unknown`

The field is selected, no cell row exists, and an external caller provides an explicit epistemic marker with a non-empty reason.

Unknown is never inferred from `absent`.

If a real cell row exists, an explicit unknown marker conflicts with canonical data and D3 rejects the projection.

### `unloaded`

The field belongs to the SEDB task view but was not included in D2's selected field support because of the active-domain plan.

An unloaded field may have a real value in SEDB. D3 intentionally does not expose it.

Therefore:

$$
\boxed{
\text{unloaded}
\neq
\text{absent}
}
$$

and:

$$
\boxed{
\text{absent}
\neq
\text{unknown}
\neq
\text{blank}
}
$$

---

## 3. Coverage metadata

To make `unloaded` observable instead of implicit, D3 reads the task-view field registry metadata for all fields in the view and emits one state slot for every field ordinal.

Only fields selected by D2 may carry cell payload.

Unselected task-view fields are represented as `unloaded` slots with field identity metadata only.

This means a consumer can distinguish:

> this field exists in the task domain but was not loaded

from:

> this selected field has no SEDB cell.

---

## 4. Projection schema

Each partial entity projection contains:

- source `ExactStateRef`;
- task `view_id`;
- query semantic-address SHA-256;
- ordered field slots.

The schema id is:

```text
isql-sedb.partial-entity-projection/v0.1
```

A multi-entity result uses:

```text
isql-sedb.partial-domain-materialization/v0.1
```

The full active-domain plan is independently hashed and bound into the multi-entity materialization.

---

## 5. Exact-state gate

Before projecting any entity, D3 calls D1 exact verification:

$$
\operatorname{SHA256}(X_{current})
\stackrel{?}{=}
H_{plan}.
$$

A stale plan aborts before partial projection.

D3 never silently updates the source exact identity to current state.

---

## 6. Correctness-first limitation

The current D1 exact-state verifier computes the complete adapter snapshot before SHA-256 verification.

Therefore D3 currently provides:

- partial **projection output**;
- partial **task-local semantic visibility**;
- bounded active-domain payload semantics;

but does not yet prove:

- partial cryptographic verification without reading the full source snapshot;
- bandwidth proportional only to selected fields;
- storage-I/O proportional only to the active-domain projection.

In other words:

$$
\boxed{
\text{Partial Projection}
\neq
\text{Proof-Carrying Partial Read Yet}
}
$$

This non-claim is intentional.

---

## 7. Why not hash only selected cells and call that exact state

Doing so would erase the distinction between:

$$
H(X)
$$

and:

$$
H(P_{D_Q}(X)).
$$

Two different full states may share the same selected projection.

Therefore a partial hash can identify the projection artifact but cannot replace the source full-state identity.

---

## 8. Unknown markers are external epistemic inputs

Current base SEDB does not define one universal cell-level `unknown` marker for every domain.

D3 therefore accepts an optional explicit mapping:

```text
(entity_id, field_id) -> reason
```

only for selected fields with no stored cell.

This lets a future epistemic/provenance adapter provide explicit unknown state without teaching D3 to guess from absence.

---

## 9. Determinism

For a fixed:

- D2 plan;
- current exact source state;
- task-view field registry;
- explicit unknown-marker mapping;

D3 must produce byte-identical canonical projection JSON.

The projection uses deterministic UTF-8 canonical JSON and SHA-256.

---

## 10. D3 invariants

### PM-1 — Projection / Source Separation

$$
P_{D_Q}(X)\neq X.
$$

### PM-2 — Explicit Unloaded State

A field excluded by the plan is `unloaded`, never implicitly absent.

### PM-3 — Explicit Blank State

Stored JSON `null` is `blank`, not absent.

### PM-4 — Unknown Requires Evidence

Unknown requires an explicit caller-provided marker and reason.

### PM-5 — Absence Is Structural

No selected cell row means `absent` unless an explicit unknown marker exists.

### PM-6 — Stale Plan Fail-Closed

Exact-state drift aborts materialization.

### PM-7 — Read-Only

D3 performs no canonical mutation.

### PM-8 — Separate Projection Identity

The projection SHA-256 never substitutes for source exact identity.

---

## 11. Next step

The next serious systems problem is **proof-carrying partial read**.

To make actual SEDB I/O scale with the selected domain while preserving exact verifiability, a later layer needs a hierarchical state commitment such as:

- per-field / per-cell canonical digests;
- an entity Merkle-style root or equivalent canonical commitment;
- membership/non-membership proofs for selected and absent cells.

Then the desired future path becomes:

$$
\boxed{
H(X)
+
\pi_{D_Q}
+
P_{D_Q}(X)
\rightarrow
\operatorname{VerifyPartial}
}
$$

without reconstructing the entire source snapshot.

That will be the bridge from semantic partial materialization to genuinely scalable distributed-universe reads.

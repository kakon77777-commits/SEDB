# ISQL–SEDB Read-Only Adapter v0.1

**Status:** Experimental project workspace  
**Date:** 2026-09-14  
**SEDB checkpoint:** v0.4B current SQLite schema  
**ISQL dependency:** Dual Addressing A2 experimental branch  
**Mutation authority:** none

---

## Purpose

This project is the first executable proof of the internal architecture rule:

$$
\boxed{
\text{ISQL navigates}
,\qquad
\text{SEDB stores}
}
$$

The end-to-end path is:

$$
\boxed{
A_S
\rightarrow
\mathcal C
\rightarrow
(E,H)
\rightarrow
\text{SEDB current exact snapshot read}
\rightarrow
\operatorname{Verify}
}
$$

The adapter is intentionally outside `current/` so the validated SEDB v0.4B snapshot and its manifest remain untouched.

---

## Read-only boundary

The runtime opens the SEDB SQLite file using:

```text
mode=ro
PRAGMA query_only=ON
```

It does not import or call:

- `EntityService.set_cell()`;
- field mutation APIs;
- autonomy commit APIs;
- governance mutation APIs.

The adapter exposes no write method.

This is a **current-head read adapter** only. Historical event/branch state resolution is a later problem.

---

## Why JSONL export is not the exact state source

SEDB's existing JSONL exchange projection exports:

```text
id / kind / label / values
```

which is useful for interchange but intentionally omits cell provenance such as:

- source;
- confidence;
- cell update time;
- stable field id;
- field definition metadata.

Therefore D1 does not hash the exchange projection and does not call it exact SEDB state.

---

## Adapter entity snapshot

D1 defines an **adapter canonical logical snapshot**, not a new SEDB Public canonical protocol.

For one entity it includes:

### Entity binding

- `id`;
- `kind`;
- `label`;
- `created_at`;
- `updated_at`.

### Every non-empty cell

- parsed JSON value;
- source;
- confidence;
- cell update time.

### Resolved field binding

- stable field id;
- key;
- namespace;
- normalized key;
- label;
- value type;
- description;
- lifecycle status;
- field creation/update time.

Cells are ordered by stable field id. The resulting object is encoded using deterministic UTF-8 canonical JSON:

```text
sort_keys=true
compact separators
allow_nan=false
```

Exact adapter state identity is then:

$$
H(X)
=
\operatorname{SHA256}(\operatorname{CanonicalJSON}(X)).
$$

This identity means:

> the exact resolved entity snapshot under adapter schema `sedb.entity-snapshot/isql-readonly-v0.1`.

It does **not** claim to be raw SQLite page identity or a new normative SEDB object identity.

---

## Why field identity is included

A field key is not sufficient as exact binding because field governance may rename or evolve a field while retaining its stable registry object.

D1 therefore includes both:

$$
\boxed{
\text{field id}
+
\text{current field definition}
}
$$

in the entity snapshot.

Changing field meaning/provenance is allowed to change the resolved entity snapshot hash because the interpretation context of the cell changed.

---

## Stale-index behavior

The ISQL semantic index is derived and may become stale after SEDB mutation.

Suppose an index candidate carries:

$$
(E,H_t).
$$

If the current SEDB snapshot has become:

$$
H_{t+1}\neq H_t,
$$

the adapter raises `SEDBExactStateMismatch`.

It does **not** silently substitute the new current state.

Therefore:

$$
\boxed{
\text{Semantic Candidate}
\neq
\text{Permission to Ignore Exact-State Drift}
}
$$

The caller may rebuild the derived semantic index or later resolve a historical revision.

---

## End-to-end reference flow

```python
adapter = SEDBReadOnlyAdapter("sedb.sqlite3")
index = adapter.build_semantic_index({
    "entity-a": analysis_a,
    "entity-b": analysis_b,
})
query = semantic_address_from_analysis(query_analysis)
result, verified = adapter.resolve_and_read_verified(query, index, top_k=4)
```

`verified` contains only snapshots whose current canonical bytes still match the candidate's exact SHA-256 identity.

---

## What D1 proves

D1 can prove that:

1. SEDB entity state can be read without invoking any mutation service;
2. the resolved state can be deterministically projected into exact bytes;
3. ISQL A2 can build semantic candidates whose exact refs bind those bytes;
4. a candidate can be re-read from SEDB and independently verified;
5. SEDB mutation makes an old exact candidate stale rather than magically equivalent;
6. source/confidence changes are visible to exact-state identity even when the cell value remains equal.

---

## What D1 does not prove

D1 does **not** claim:

- that the adapter snapshot is Public SEDB canonical state;
- historical state resolution;
- branch-aware SEDB reads;
- physical residency proof;
- RAL integration;
- write authority;
- distributed SEDB scale;
- production concurrency semantics;
- vector or learned semantic retrieval;
- Public ISQL protocol promotion.

---

## Next step

If D1 remains green, the next useful layer is an **Active Domain Resolver** that combines:

- semantic candidate reduction;
- task-local field support $F_Q\subseteq F$;
- resource/materialization budgets;
- dependency closure.

That moves the system from exact read integration toward:

$$
\boxed{
\text{Data Ocean}
\rightarrow
\text{Finite Active Domain}
}
$$

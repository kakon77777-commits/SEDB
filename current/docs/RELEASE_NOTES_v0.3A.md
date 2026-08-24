# SEDB v0.3A Release Notes

Version: `0.3.0a1`  
Checkpoint: **Field Utility & Convergence Recommendation Kernel**  
Date: 2026-08-21  
Development mode: local-first; GitHub not updated by this checkpoint.

## Purpose

v0.3A adds deterministic operational-utility assessment to SEDB without allowing a score to silently mutate canonical field lifecycle state.

The release invariant is:

$$
\boxed{\text{Assessment}\neq\text{Lifecycle Mutation}}
$$

## Added

- `field_utility_assessments` with SQLite-level update/delete rejection;
- `field_guardrails` as append-only protect/unprotect events;
- policy `utility-v1`;
- coverage, Task View support, and pending semantic redundancy metrics;
- lifecycle-aware recommendations;
- post-convergence evidence detection;
- evidence-basis SHA-256;
- stale-assessment rejection;
- explicit apply through existing field transition/evaluation machinery;
- bounded `assess_registry()` path;
- Field Utility HTTP API;
- minimal Browser Field Utility panel;
- `examples/utility_demo.py`;
- small governance fixture and fresh 10,000-field batch-assessment fixture.

## Policy

$$
U_f
=
0.45C_f
+
0.40T_f
+
0.15(1-R_f).
$$

The score is an operational heuristic. It does not claim to measure scientific, epistemic, moral, commercial, or permanent knowledge value.

## Recommendation safety

The release distinguishes:

```text
keep
review
converge_candidate
reactivate_candidate
insufficient_evidence
```

`converge_candidate` and `reactivate_candidate` are advisory until a separate explicit apply call succeeds.

Before apply, the current evidence basis is hashed again. If it differs from the assessment basis, the assessment is stale and mutation is rejected.

## Release fixtures

### Governance fixture

`demo/sedb-utility-governance-v0.3a.sqlite`

It demonstrates all recommendation categories used by `utility-v1`, an explicit convergence apply, a protected field, a Task View supported field, a pending semantic-redundancy signal, and a converged field with post-convergence evidence.

### 10K utility fixture

`demo/sedb-utility-10k-v0.3a.sqlite`

Release environment result:

```text
fields: 10000
entities: 3
assessments: 10000
recommendations: converge_candidate = 10000
elapsed_seconds: 0.476007
```

This timing is local evidence only and must not be generalized across hardware, storage, Python builds, SQLite configurations, or workloads.

## Compatibility

Existing v0.2B databases migrate forward through idempotent schema initialization. Existing IDs, cells, aliases, definition versions, lineage, semantic candidates, reviews, and field relations are preserved.

## Deferred

v0.3A intentionally does **not** implement:

- automatic lifecycle mutation from utility scores;
- learned utility weights;
- LLM or embedding-based utility judgment;
- duplicate clustering;
- AI Field Agent autonomous proposal/fill loops;
- distributed or production multi-user concurrency.

Those remain separate later checkpoints.

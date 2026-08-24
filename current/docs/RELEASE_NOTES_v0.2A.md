# SEDB Local v0.2A — Field Governance Kernel Release Notes

Date: 2026-08-20
Package version: `0.2.0a1`
Development mode: local-first, not automatically synchronized to GitHub

## Purpose

v0.2A keeps the v0.1 sparse/unbounded field model and adds the first governance kernel needed to stop open-ended schema growth from becoming uncontrolled semantic entropy.

The new invariant is:

$$
\boxed{\text{Unbounded Field Growth}\neq\text{Ungoverned Canonical Growth}}
$$

## Implemented in v0.2A

- automatic forward migration from v0.1 SQLite files;
- deterministic field-key normalization (Unicode NFKC + case/separator normalization);
- namespace metadata for fields and proposals;
- normalized duplicate prevention for new canonical fields;
- alias registry and alias-aware field resolution;
- alias-aware sparse cell writes and Task View construction;
- proposal accept/reject decisions with reason, evaluator, evidence, outcome, and canonical target;
- duplicate proposal acceptance as `alias_existing` without creating a second canonical field;
- immutable field definition version ledger;
- versioned definition updates with mandatory reason;
- explicit `merged_into` and `split_into` lineage edges;
- merge/split guard preventing lineage-free direct terminal transitions;
- merge/split semantics that never silently migrate or duplicate sparse cell data;
- governance HTTP API;
- minimal browser proposal-governance panel;
- v0.1 regression preservation.

## Compatibility boundary

The legacy `fields.key` remains globally unique in v0.2A for safe forward migration. Namespace is already persisted and used for normalized identity/alias governance, but duplicate raw canonical keys across different namespaces are intentionally deferred.

Existing v0.1 IDs and sparse cells are preserved during migration. Existing fields receive an immutable version-1 migration snapshot.

## Explicitly deferred

- embedding/LLM semantic duplicate detection;
- automatic information-gain scoring;
- automatic proposal acceptance policy;
- automatic cell migration on merge/split;
- canonical key renaming and namespace migration;
- cross-namespace duplicate raw keys;
- field-definition conflict resolution across multiple writers;
- multi-user authentication/authorization;
- PostgreSQL/DuckDB backends;
- 100K/1M-field benchmark campaign;
- GitHub synchronization of this local checkpoint;
- public software license selection.

## Data safety rule

Merge/split lineage describes semantic identity only. It does not rewrite data:

$$
\operatorname{Merge}(f_a\to f_b)
\not\Rightarrow
C(f_a)\to C(f_b).
$$

Any future cell migration policy must be explicit, reviewable, and separately tested.

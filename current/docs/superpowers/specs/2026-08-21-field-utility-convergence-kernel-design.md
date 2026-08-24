# SEDB v0.3A Field Utility & Convergence Recommendation Kernel Design

## Goal

Extend SEDB v0.2B with deterministic, local, explainable field-utility assessment and lifecycle recommendations while preserving the invariant that an assessment cannot mutate field status automatically.

## Core invariants

1. Utility is operational evidence, not an ontological claim about a field's true knowledge value.
2. An assessment is advisory. No score may automatically converge or reactivate a field.
3. Lifecycle mutation remains an explicit second transaction through the existing `FieldService.transition(...)` path.
4. Every convergence/reactivation application must cite an immutable assessment ID and preserve its metrics in `field_evaluations`.
5. A protected field never receives `converge_candidate` while its latest guardrail is active.
6. A new empty field is `insufficient_evidence`, not automatically useless.
7. A field referenced by a Task View receives explicit task-support credit even when sparse coverage is low.
8. A pending high-similarity field-to-field semantic candidate lowers operational utility but never performs a merge/alias automatically.
9. For a currently converged field, a cell written after convergence or a Task View created after convergence can produce `reactivate_candidate`.
10. Assessments are append-only and immutable.
11. Guardrail changes are append-only; current state is the latest event for the field.
12. Applying an assessment requires its evidence basis to remain unchanged. If cells, entities, Task Views, pending semantic candidates, guardrails, or field lifecycle state changed, the assessment is stale and must be recomputed.
13. Existing v0.2B databases migrate forward without losing IDs, cells, aliases, versions, lineage, proposal decisions, semantic candidates, reviews, or relations.
14. Registry utility scans must aggregate evidence in bounded SQL passes rather than issue an independent full-database scan per field.

## Architecture

Add `UtilityService` in `src/sedb/utility.py`. It reads the existing canonical field registry, sparse cells, Task Views, field events, semantic candidates, and append-only guardrails. It writes immutable `field_utility_assessments` rows. Lifecycle changes remain owned by `FieldService`.

The flow is:

$$
\text{Field Evidence}
\rightarrow
\text{Deterministic Metrics}
\rightarrow
\text{Operational Utility}
\rightarrow
\text{Recommendation}
\rightarrow
\boxed{\text{Explicit Apply}}
\rightarrow
\text{Existing Lifecycle Transition}.
$$

No model provider, embedding, network call, or external dependency is added in v0.3A.

## Operational utility policy v1

For an eligible field $f$, define:

$$
U_f
=
0.45C_f
+
0.40T_f
+
0.15(1-R_f),
$$

where:

- $C_f$ is sparse coverage, the number of entities with a cell for $f$ divided by the total entity count;
- $T_f=1$ when at least one Task View references $f$, otherwise $0$;
- $R_f$ is the highest still-pending field-to-field semantic candidate score involving $f$, or $0$ when none exists.

The score is clamped to $[0,1]$ and stored with all component metrics. It is called **operational utility**, not knowledge value.

Policy constants for `utility-v1`:

```text
minimum_age_days = 7
converge_threshold = 0.15
review_threshold = 0.35
```

## Recommendation policy

Recommendations are one of:

```text
keep
review
converge_candidate
reactivate_candidate
insufficient_evidence
```

### Active fields

1. If the latest guardrail is protected: `keep`.
2. If there are no entities: `insufficient_evidence`.
3. If the field is younger than 7 days, has no cells, and has no Task View support: `insufficient_evidence`.
4. If the field is at least 7 days old, has zero cells, zero Task View support, is unprotected, and $U_f\leq0.15$: `converge_candidate`.
5. If $U_f<0.35$: `review`.
6. Otherwise: `keep`.

This means a rare field explicitly used by a Task View is not penalized merely because global coverage is low.

### Converged fields

Find the latest `converged` field event. If a cell was written after that time, or a Task View referencing the field was created after that time, recommend `reactivate_candidate`. Otherwise recommend `keep`.

### Terminal or non-operational statuses

Fields in `merged`, `split`, `deprecated`, or `proposed` registry status receive `keep` with a reason that lifecycle utility mutation is not applicable in v0.3A.

## Evidence basis and staleness

Each assessment stores a deterministic `basis_sha256`. The basis is serialized from canonical evidence that can affect the recommendation:

- field ID/status/updated time;
- total entity count;
- field cell count and latest cell timestamp;
- Task View reference count and latest referencing-view timestamp;
- maximum pending semantic redundancy score and candidate IDs;
- latest guardrail event ID/state;
- latest convergence event timestamp;
- policy version.

When applying an actionable assessment, `UtilityService` recomputes the basis from current data using the stored policy version. A mismatch rejects the application with a stale-assessment error.

## Tables

### `field_utility_assessments`

Append-only rows:

```text
id TEXT PRIMARY KEY
field_id TEXT
policy_version TEXT
field_status TEXT
score REAL
recommendation TEXT
reason TEXT
metrics_json TEXT
evidence_json TEXT
policy_json TEXT
basis_sha256 TEXT
as_of TEXT
created_at TEXT
```

SQLite triggers reject `UPDATE` and `DELETE` so an assessment cannot be rewritten after creation.

### `field_guardrails`

Append-only guardrail events:

```text
id INTEGER PRIMARY KEY AUTOINCREMENT
field_id TEXT
protected INTEGER
reason TEXT
evaluator TEXT
created_at TEXT
```

The latest row for a field is its current protection state. Both protect and unprotect actions require a non-empty reason.

## Utility service API

```python
UtilityService(db).assess_field(field_ref, evaluator="system:utility", as_of=None)
UtilityService(db).assess_registry(statuses=("active", "converged"), limit_fields=1000, offset=0, evaluator="system:utility", as_of=None)
UtilityService(db).get_assessment(assessment_id)
UtilityService(db).list_assessments(field_ref, limit=100)
UtilityService(db).set_guardrail(field_ref, protected, reason, evaluator="")
UtilityService(db).get_guardrail(field_ref)
UtilityService(db).list_guardrail_history(field_ref)
UtilityService(db).apply_assessment(assessment_id, reason, evaluator="")
```

`assess_registry` gathers aggregate cell/view/semantic/guardrail/event evidence in a small fixed number of SQL passes for the selected field set and then writes assessment rows in one transaction.

## Apply semantics

Only these recommendation/status pairs are actionable:

```text
active + converge_candidate -> converged
converged + reactivate_candidate -> active
```

Apply requires a non-empty application reason. The existing `field_evaluations` row receives:

- `assessment_id`;
- `policy_version`;
- assessment reason;
- stored evidence-basis hash;
- the assessment metrics.

Recommendations `keep`, `review`, and `insufficient_evidence` cannot be applied as lifecycle transitions.

## HTTP API

Add:

```text
POST /api/fields/{id}/utility/assess
GET  /api/fields/{id}/utility/assessments
POST /api/governance/utility/scan
POST /api/utility/assessments/{id}/apply
GET  /api/fields/{id}/guardrail
POST /api/fields/{id}/guardrail
```

## Browser UI

Add a compact **Field Utility** panel that can:

- enter/select a field reference;
- assess one field;
- show score, recommendation, reason, and key metrics;
- protect/unprotect the field with a reason;
- explicitly apply only actionable recommendations with a separate reason;
- run a bounded registry utility scan.

The UI must never auto-apply a recommendation.

## Non-goals

- automatic lifecycle mutation on a numeric threshold;
- LLM/embedding utility judgments;
- causal claims that a low score means a field is scientifically unimportant;
- duplicate clustering (v0.3B);
- AI Field Agent autonomous proposal/fill workflow (v0.3C);
- distributed utility execution;
- production authentication/authorization.

## Release success criteria

- all 65 v0.2B tests continue to pass;
- v0.2B database migration adds utility/guardrail tables without data loss;
- a brand-new empty field produces `insufficient_evidence`;
- an old, unprotected, unused field produces `converge_candidate`;
- a protected unused field does not produce `converge_candidate`;
- a sparse field used by a Task View is retained;
- a pending high-similarity field candidate lowers the stored utility score;
- a converged field with post-convergence cell or Task View evidence produces `reactivate_candidate`;
- assessments are immutable at SQLite level;
- an apply writes the assessment ID and metrics into the existing lifecycle evaluation trail;
- a stale assessment cannot be applied after its evidence basis changes;
- bounded registry assessment works against a fresh 10,000-field demo without per-field full-database scans;
- final ZIP is re-extracted and the full suite reruns successfully.

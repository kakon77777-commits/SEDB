# SEDB v0.2B Semantic Candidate & Dedup Kernel Design

## Goal

Extend SEDB v0.2A with deterministic, local, explainable duplicate-candidate discovery without allowing similarity scores to mutate canonical identity automatically.

## Invariants

1. Similarity is advisory. No score may auto-merge, auto-alias, or rewrite a canonical field.
2. Aliases remain one-hop references directly to canonical `fields.id`; alias-to-alias chains are forbidden by construction.
3. Canonical-to-canonical relations are separate from aliases. v0.2B introduces only `related_to`; duplicate canonical fields must still be resolved through explicit merge governance.
4. Namespace isolation is the default. Cross-namespace comparison requires an explicit flag.
5. Every candidate score stores an explainable signal breakdown.
6. Every review decision requires a non-empty reason and records evaluator/evidence.
7. Existing v0.2A databases migrate forward without losing IDs, cells, versions, lineage, aliases, or proposal decisions.
8. Field-registry scanning must use bounded neighborhoods/blocking rather than an all-pairs $O(|F|^2)$ comparison.

## Architecture

Add a new `SemanticDedupService` in `src/sedb/semantic.py`. It consumes the existing field/proposal registries and writes advisory candidate records. Canonical mutations stay in governance tables and occur only after an explicit review decision.

The flow is:

$$
\text{Proposal / Field}
\rightarrow
\text{Bounded Candidate Generation}
\rightarrow
\text{Deterministic Score}
\rightarrow
\text{Persist Signals}
\rightarrow
\text{Review}
\rightarrow
\{\text{Alias},\text{Related},\text{Distinct},\text{Ignore}\}.
$$

## Deterministic score

For two field descriptions $a,b$:

$$
S(a,b)
=
0.45S_{key}
+0.30S_{label}
+0.10S_{description}
+0.10S_{type}
+0.05S_{namespace}.
$$

`S_key` is the maximum of normalized token Jaccard and normalized-key character similarity. `S_label` and `S_description` use stopword-filtered token Jaccard plus a smaller character similarity component. `S_type=1` for matching value types and `0` for different value types. A type conflict applies a final multiplicative penalty of `0.60`. `S_namespace=1` for the same namespace and `0` otherwise.

Scores are clamped to $[0,1]$ and rounded for stable storage. The stored `signals_json` records every component, the type penalty, and the final score.

## Candidate generation

### Proposal scoring

`score_proposal(proposal_id, top_k=10, max_candidates=500, cross_namespace=False)` performs a cheap pass over eligible canonical fields, ranks blocking evidence using shared non-generic tokens, normalized prefixes, and type agreement, then fully scores at most `max_candidates`. Only the requested `top_k` are persisted and returned.

### Registry scan

`scan_field_similarity(namespace, threshold, max_neighbors)` sorts fields by normalized key, compares a bounded lexical neighborhood, and supplements this with rare-token inverted-index neighbors. High-frequency tokens are ignored as blockers. Each field contributes no more than `max_neighbors` candidate neighbors before scoring. Canonical pair ordering prevents reverse duplicates.

## Tables

### `semantic_candidates`

- `id`
- `namespace`
- `source_kind` (`proposal` or `field`)
- `source_ref`
- `candidate_field_id`
- `score`
- `signals_json`
- `status` (`pending` or `reviewed`)
- `created_at`
- unique `(source_kind, source_ref, candidate_field_id)`

### `semantic_candidate_reviews`

- `candidate_id` unique
- `decision` (`alias`, `related`, `distinct`, `ignore`)
- `reason`
- `evidence_json`
- `evaluator`
- `created_at`

### `field_relations`

- canonical `left_field_id`
- canonical `right_field_id`
- `relation='related_to'`
- reason/evidence/evaluator/time
- pair stored in deterministic ID order

## Review semantics

- `alias`: valid only when the candidate source is a pending proposal. The proposal becomes accepted, its proposed key is added directly to `field_aliases` for the candidate canonical field, and a proposal decision with outcome `semantic_alias_existing` is recorded. No new canonical field is created.
- `related`: for a field-to-field candidate, write a canonical `related_to` edge. For a proposal candidate, record the review only and leave the proposal pending.
- `distinct`: record that the pair was reviewed as distinct; no canonical mutation.
- `ignore`: close the candidate without semantic assertion.

A canonical-field candidate cannot be converted into an alias; use explicit v0.2A merge governance instead.

## API

- `POST /api/proposals/{id}/candidates`
- `GET /api/proposals/{id}/candidates`
- `GET /api/candidates`
- `POST /api/candidates/{id}/review`
- `GET /api/candidates/{id}/review`
- `POST /api/governance/similarity/scan`
- `GET /api/fields/{id}/relations`

## UI

Extend the existing Field Governance panel with a `Score` action for pending proposals and a compact candidate-review list. Keep the UI local and minimal; no model-provider configuration is added in v0.2B.

## Non-goals

- embeddings or LLM calls;
- automatic synonym claims;
- automatic merge or alias above a threshold;
- fuzzy replacement of canonical identity;
- distributed similarity indexing;
- production-scale vector search.

## Release success criteria

- all 49 v0.2A tests continue to pass;
- deterministic ranking test puts reordered equivalent wording first;
- incompatible type reduces score materially;
- default namespace isolation is tested;
- alias review creates one-hop canonical alias and no second field;
- canonical-to-canonical alias review is rejected;
- related/distinct/ignore reviews are auditable;
- a fresh 10,000-field release demo completes bounded registry scanning without all-pairs enumeration;
- final ZIP is re-extracted and the full suite reruns successfully.

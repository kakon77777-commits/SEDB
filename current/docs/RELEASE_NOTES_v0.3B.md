# SEDB v0.3B Release Notes

Version: `0.3.0b1`  
Date: 2026-08-22  
Checkpoint: **Semantic Field Family Kernel**

## Core change

v0.3B lifts v0.2B pairwise semantic evidence into multi-field family proposals while refusing to equate graph connectivity with synonymy.

$$
\boxed{\text{Pairwise Similarity}\not\Rightarrow\text{Family Truth}}
$$

A family proposal is immutable and reviewable. Only explicit review creates a formal duplicate/related family; even then, no canonical field, alias, lifecycle state, or sparse cell is mutated.

## Added

- six family governance tables with immutable proposal headers/members;
- `FieldFamilyService`;
- bounded seed proposal generation;
- complete-link coherence guard;
- proposal basis SHA-256 and stale-review rejection;
- `duplicate_family`, `related_family`, `split`, `reject` decisions;
- formal field families and append-only creation events;
- duplicate-family overlap prevention;
- bounded registry family scan built on v0.2B semantic scanning;
- local family API and Browser panel;
- small family governance demo and fresh 10K benchmark fixture.

## Explicit non-goals

v0.3B does not automatically merge fields, create aliases, migrate cells, infer transitive synonymy, call an LLM, or use embeddings.

## Packaged 10K run

```text
fields: 10000
naive_all_pairs: 49995000
max_neighbors: 6
bounded_pair_upper_bound: 60000
proposals: 2
planted_families_found: 2/2
elapsed_seconds: 4.974185
```

The timing is specific to the release environment and fixture.

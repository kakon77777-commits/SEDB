# SEDB v0.2B Release Notes

Version: `0.2.0b1`  
Date: 2026-08-20  
Status: local-first executable checkpoint

## New capability

v0.2B adds an explainable, deterministic semantic-candidate layer on top of v0.2A field governance.

The new invariant is:

$$
\boxed{\text{Similarity Candidate}\neq\text{Canonical Mutation}}
$$

A score may suggest review, but cannot automatically merge, alias, or rewrite a canonical field.

## Added

- `SemanticDedupService`;
- deterministic weighted field similarity;
- per-score signal breakdown;
- proposal candidate scoring and top-k persistence;
- namespace-isolated scoring by default;
- bounded candidate generation;
- `semantic_candidates` table;
- `semantic_candidate_reviews` table;
- `field_relations` table with `related_to`;
- candidate review decisions: `alias`, `related`, `distinct`, `ignore`;
- proposal semantic alias acceptance without a second canonical field;
- canonical-to-canonical alias review rejection;
- sorted-neighborhood + rare-token registry scan;
- reverse-pair deduplication;
- HTTP API for candidate scoring, listing, review, relations, and registry scan;
- browser UI for Score and semantic candidate review;
- fresh 10K bounded-scan validation script and demo database.

## Scoring model

$$
S(a,b)=0.45S_{key}+0.30S_{label}+0.10S_{description}+0.10S_{type}+0.05S_{namespace}.
$$

Different value types apply a multiplicative penalty of $0.60$.

The algorithm is deliberately local and deterministic. It does not claim general synonym understanding and does not use embeddings or external models.

## Registry-scan boundary

The scan uses bounded lexical neighborhoods and rare-token blocking. It does not enumerate all field pairs.

For $N$ fields and configured neighborhood cap $k$, candidate generation is bounded by approximately:

$$
O(Nk)
$$

before score-threshold filtering, rather than materializing:

$$
\binom{N}{2}.
$$

This is an engineering bound for the implemented candidate generator, not a universal complexity claim for every future semantic index.

## Compatibility

Opening a v0.2A database creates the new semantic tables idempotently while preserving existing IDs, cells, aliases, versions, proposal decisions, and lineage.

## Non-goals

- embedding search;
- LLM-based synonym inference;
- automatic merge;
- automatic alias above a score threshold;
- canonical identity rewrite;
- distributed similarity infrastructure.

## Concrete 10K release validation

The packaged fresh demo recorded:

```text
fields: 10000
all_pairs_if_naive: 49995000
bounded_pair_upper_bound: 60000
persisted_candidates: 2
expected_duplicate_pairs_found: 2
elapsed_seconds: 7.983901
```

The elapsed time is specific to this execution environment and is not a cross-machine performance guarantee.

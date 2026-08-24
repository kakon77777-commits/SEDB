# SEDB v0.4A Release Notes

Version: `0.4.0a1`  
Date: 2026-08-23  
Checkpoint: **Multi-Agent Coordination & Advisory Consensus Kernel**

## Core change

v0.4A adds a bounded multi-Agent coordination layer on top of the governed v0.3C Agent runtime.

$$
\boxed{\text{Multi-Agent Agreement}\neq\text{Canonical Authority}}
$$

$$
\boxed{\text{Consensus}\neq\text{Truth}}
$$

A campaign may divide work across multiple governed Agent runs, aggregate compatible advisory evidence, preserve disagreement, and emit immutable consensus packets. A consensus packet remains advisory: it cannot accept a field proposal, create or modify a canonical field, write a sparse cell, merge/split fields, apply utility convergence, or turn a family proposal into canonical state.

## Added

- `field_agent_campaigns` with campaign policy, status, counters, and aggregate budgets;
- leased `field_agent_work_items` / `field_agent_work_claims` with expiry and safe reclaim;
- immutable campaign-to-Agent-run links;
- campaign-level run / work / step / proposal / generic-cost accounting;
- advisory grouping over Agent action receipts;
- explicit raw-support versus independent-support accounting;
- backend and evidence-root diversity metrics;
- basis-compatibility checks;
- semantic conflict and incompatible-type preservation;
- immutable `field_agent_consensus_packets` and consensus events;
- local campaign HTTP API and Browser advisory panel;
- no campaign-to-canonical mutation endpoint.

## Independence is not a vote count

If multiple Agent runs share the same backend and the same observation root, they may increase raw support while contributing only one independence unit:

$$
N_{\mathrm{raw}}\neq N_{\mathrm{independent}}.
$$

For example, two runs that repeat the same backend over the same evidence can produce:

$$
N_{\mathrm{raw}}=2,
\qquad
N_{\mathrm{independent}}=1,
$$

which is classified as `insufficient_independence`, not strong consensus.

## Consensus packet states

v0.4A can emit:

```text
strong_agreement
weak_agreement
disputed
incompatible
insufficient_independence
basis_incompatible
```

These states describe advisory evidence structure. None of them is a truth predicate.

## Work leasing

A work item can have at most one active claim. Claims carry an expiry time, so abandoned work can be reclaimed after its lease expires. Campaigns that are completed, failed, or budget-exhausted are terminal for new work and claims.

## Packaged governance evidence

`demo/sedb-campaign-governance-v0.4a.sqlite` contains a fresh five-run campaign with two consensus groups.

```text
canonical fields:      2 -> 2
canonical sparse cells:1 -> 1
linked Agent runs:     5
work items:            5
consensus packets:     2
packet states:         strong_agreement, incompatible
```

The `publication_type` group contains three raw supporting runs but two independent evidence units across two backends and two observation roots:

```text
raw support:           3
independent support:   2
backend count:         2
evidence-root count:   2
minimum pair score:    1.0
status:                strong_agreement
```

The `review_status` group contains two independent suggestions with incompatible value types:

```text
raw support:           2
independent support:   2
value types:           boolean, text
minimum pair score:    0.54
status:                incompatible
```

The disagreement is preserved instead of being collapsed by majority vote.

## Bounded coordination benchmark

`demo/sedb-campaign-benchmark-v0.4a.sqlite` records a deterministic local coordination benchmark using 80 completed Agent runs distributed across eight advisory keys.

```text
Agent runs:            80
work items:            80
advisory keys:         8
consensus packets:     8
packet state:          weak_agreement
canonical fields:      0 -> 0
canonical cells:       0 -> 0
campaign status:       completed
elapsed here:          1.606748 s
```

The elapsed time applies only to this packaged fixture and this release environment. It is not a cross-machine, production, or asymptotic performance guarantee.

Machine-readable evidence is stored in `demo/campaign-stats-v0.4a.json`. SHA-256 values for the two v0.4A SQLite fixtures are stored in `demo/DEMO_SHA256_v0.4A.txt`.

## Canonical-state invariant

For a campaign composed only of governed Agent runs and advisory consensus operations:

$$
|F_{t+1}|=|F_t|,
$$

and:

$$
|C_{t+1}|=|C_t|.
$$

Advisory artifacts, campaign receipts, and consensus packets may increase. Canonical field/cell mutation still requires the existing governance paths outside the campaign coordinator.

## Explicit non-goals

v0.4A does not claim consensus is truth, does not treat repeated same-source Agent runs as independent evidence, does not add an LLM provider, does not implement distributed consensus protocols, and does not grant multi-Agent campaigns canonical authority.

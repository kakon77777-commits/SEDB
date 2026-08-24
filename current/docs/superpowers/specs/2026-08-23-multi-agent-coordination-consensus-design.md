# SEDB v0.4A Multi-Agent Coordination & Advisory Consensus Kernel — Design

## Goal

Add a local-first multi-Agent coordination layer above the v0.3C governed Field Agent runtime without granting campaigns or consensus packets canonical mutation authority.

## Core invariants

$$
\boxed{\text{Multi-Agent Agreement}\neq\text{Canonical Authority}}
$$

$$
\boxed{\text{Consensus}\neq\text{Truth}}
$$

A completed campaign may increase work receipts, linked Agent runs, advisory groups, and immutable consensus packets, while canonical field and sparse-cell counts remain unchanged unless an external governance path acts separately.

## Architecture

v0.4A adds `CampaignService` in `src/sedb/campaign.py`. It orchestrates existing `AgentService` runs rather than duplicating proposal, semantic, utility, family, or mutation logic.

The pipeline is:

$$
\text{Campaign}\rightarrow\text{Work Items}\rightarrow\text{Leased Claims}\rightarrow\text{Independent Agent Runs}\rightarrow\text{Advisory Grouping}\rightarrow\text{Consensus / Conflict Packet}.
$$

### Persistence

New tables:

- `field_agent_campaigns`: mutable campaign lifecycle and bounded counters.
- `field_agent_campaign_runs`: immutable links from campaign/work item to an existing Agent run.
- `field_agent_work_items`: bounded work queue items.
- `field_agent_work_claims`: leased claims; only one active claim per work item.
- `field_agent_advisory_groups`: immutable aggregation snapshots.
- `field_agent_advisory_group_members`: immutable evidence members.
- `field_agent_consensus_packets`: immutable classifications.
- `field_agent_consensus_events`: immutable packet-generation audit events.

### Work leasing

A work item can have at most one active claim. Claims expire at an explicit timestamp and can then be reclaimed. A completed/failed/budget-exhausted campaign is terminal and accepts no new work, claims, or run links.

### Campaign budget

Campaign-level budget is independent of per-run Agent budgets:

```text
max_runs
max_work_items
max_agent_steps
max_proposals
max_cost_units
```

Counters aggregate linked run steps/proposals and generic cost units. A budget breach marks the campaign `budget_exhausted` and blocks further coordination writes.

### Advisory evidence

Aggregation uses Agent action receipts, not only `field_proposals`, because later runs may correctly emit `SKIPPED_PENDING_PROPOSAL` after an earlier run already created the shared proposal. Those receipts still preserve an independent advisory signal.

Each support member records:

- run id;
- backend;
- observation-root SHA-256;
- run basis SHA-256;
- normalized field key;
- label;
- value type;
- reason;
- outcome and evidence refs.

Raw support count is not independence count. Independence units are unique `(backend, observation_root_sha256)` pairs.

### Grouping

v0.4A groups by normalized field identity after canonical normalization. It does not use connected components or majority-vote semantic collapse. Within a group, proposal/suggestion variants are compared with the existing deterministic `score_field_pair` function.

### Consensus classification

A packet is classified deterministically as one of:

```text
strong_agreement
weak_agreement
disputed
incompatible
insufficient_independence
basis_incompatible
```

Rules are conservative:

1. Multiple run basis hashes => `basis_incompatible`.
2. Multiple value types => `incompatible`.
3. Two or more raw supports but only one independence unit => `insufficient_independence`.
4. Compatible variants with low minimum semantic pair score => `disputed`.
5. Two or more independent units with both backend and evidence-root diversity => `strong_agreement`.
6. Two or more independent units without both diversity dimensions => `weak_agreement`.
7. A singleton is `insufficient_independence`.

The packet stores metrics and evidence roots. It is advisory only.

### Basis safety

Campaign creation records a registry basis SHA-256. Linked Agent runs retain their own basis SHA-256. Aggregation never hides basis divergence; incompatible basis state is explicitly classified.

### Canonical safety

`CampaignService` has no methods that create canonical fields, set/delete cells, merge/split fields, apply utility assessments, review semantic candidates, or review field families. API/UI surfaces only campaign/work/aggregation operations.

## API surface

Planned local API:

```text
GET  /api/agent-campaigns
POST /api/agent-campaigns
GET  /api/agent-campaigns/{id}
POST /api/agent-campaigns/{id}/work
POST /api/agent-campaigns/{id}/claim
POST /api/agent-campaigns/{id}/link-run
POST /api/agent-campaigns/{id}/aggregate
POST /api/agent-campaigns/{id}/complete
```

No endpoint grants canonical mutation.

## Validation

The release must preserve all v0.3C tests and add coverage for migration, immutable packets, single-active-claim lease behavior, lease expiry/reclaim, terminal campaign behavior, campaign budget exhaustion, raw-vs-independent support, semantic conflict, value-type incompatibility, basis incompatibility, packet immutability, API/UI exposure, and unchanged canonical field/cell counts across a complete multi-Agent campaign.

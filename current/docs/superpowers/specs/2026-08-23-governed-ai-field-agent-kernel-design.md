# SEDB v0.3C Governed AI Field Agent Kernel Design

## Goal

Build a provider-neutral AI Field Agent runtime that can observe structured data, generate advisory field proposals, score semantic candidates, request utility assessments, and propose field families while preserving the invariant that an autonomous agent run cannot mutate canonical fields, cells, aliases, lineage, guardrails, utility lifecycle state, or reviewed family state.

## Core invariant

$$
\boxed{\text{AI Autonomy}\neq\text{Canonical Authority}}
$$

An agent may create advisory artifacts. Canonical mutation remains behind explicit governance services.

For a complete autonomous run:

$$
|F_{t+1}|=|F_t|
$$

while advisory artifacts may increase:

$$
|P_{t+1}|\ge |P_t|.
$$

## Architecture

The new `sedb.agent` module orchestrates existing services instead of duplicating them:

- `FieldService` for proposal creation only;
- `SemanticDedupService` for proposal scoring;
- `UtilityService` for assessment only;
- `FieldFamilyService` for family proposal generation only.

Mutation-capable governance methods are not exposed as agent capabilities.

The runtime pipeline is:

$$
\text{Observation Packet}
\rightarrow
\text{Backend Suggestions}
\rightarrow
\text{Intent Validation}
\rightarrow
\text{Capability Gate}
\rightarrow
\text{Budget Gate}
\rightarrow
\text{Advisory Execution}
\rightarrow
\text{Receipt Ledger}.
$$

## Agent persistence

### `field_agent_runs`

One row per run. Stores backend, namespace, policy version, budget JSON, input/basis hashes, status, counters, timestamps, and evaluator identity.

Run status is updated only through the runtime while every status change is also appended to `field_agent_run_events`.

### `field_agent_observations`

Immutable observation packets. The canonical payload is JSON and is addressed by SHA-256. Every packet has a stable ordinal inside the run.

### `field_agent_actions`

Immutable receipt for every requested action. Stores intent, capability decision, outcome, input/output JSON, reason, evidence references, and timestamp. Denied actions are first-class records.

### `field_agent_run_events`

Append-only run history for `created`, `started`, `completed`, `budget_exhausted`, and `failed` events.

## Observation packet

The deterministic reference backend accepts JSON-compatible nested records and flattens object keys into candidate field paths. Array indices are not field identity; arrays contribute their element shape without producing unbounded numeric field names.

For each discovered path, the backend emits an advisory suggestion containing:

- `key`;
- `label`;
- inferred primitive `value_type`;
- reason;
- confidence;
- evidence pointer such as `obs:<id>#/records/0/...`.

A discovered key that already resolves as canonical or alias is not proposed again.

## Backends

### `DeterministicDiscoveryBackend`

A dependency-free reference backend used for deterministic tests and local execution. It performs structural key discovery and primitive type inference. It is explicitly not presented as an LLM.

### `ExternalSuggestionBackend`

Validates a caller-supplied suggestion packet. This is the provider-neutral adapter for GPT, local models, other agents, or future model runtimes. The backend never receives canonical mutation authority.

## Capabilities

Allowed advisory actions in v0.3C:

- `create_proposal`;
- `score_proposal`;
- `assess_field`;
- `propose_family`.

Explicitly denied canonical/mutating intents include:

- `create_field`;
- `decide_proposal`;
- `review_candidate`;
- `merge_fields`;
- `split_field`;
- `update_definition`;
- `apply_assessment`;
- `review_family`;
- `set_cell`;
- `delete_cell`;
- `set_guardrail`.

Denied intents must create a `DENIED` action receipt instead of being silently ignored.

## Budgets

A run budget is a bounded policy object:

```json
{
  "max_steps": 100,
  "max_observations": 500,
  "max_proposals": 30,
  "max_candidate_scores": 20,
  "max_family_proposals": 5,
  "max_assessments": 50
}
```

The runtime increments counters atomically with advisory execution. Exceeding a dimension writes a `budget_exhausted` event and halts further actions.

## Staleness and idempotence

A run basis hash covers namespace plus a deterministic snapshot of canonical field identity, aliases, active families, Task View field membership, and observation packet hashes.

Immediately before `create_proposal`, the runtime re-resolves the candidate key. If another process has already made it canonical or an alias, the action becomes `SKIPPED_ALREADY_REPRESENTED`.

Repeated deterministic suggestions within one run are de-duplicated by normalized `(namespace,key)` identity and produce a skip receipt rather than a second proposal.

## Safety boundary

The runtime does not call proposal decision, semantic review, merge/split, field definition update, utility apply, family review, cell mutation, or guardrail mutation. Tests assert that field count and cell count are unchanged by complete autonomous runs.

## API and local UI

Add local HTTP endpoints for:

- creating/running a deterministic agent run;
- creating/running an external suggestion run;
- listing runs;
- fetching run detail with observations/actions/events.

The Browser UI gets a minimal `AI Field Agent` panel for local deterministic runs and JSON external suggestions. It displays receipts and never offers mutation buttons.

## Release success criteria

- v0.3B 107-test baseline remains green;
- old DB migrates without losing canonical data;
- observation/action history is auditable;
- deterministic raw observation discovers new proposal fields;
- existing canonical/alias keys are skipped;
- external suggestions use the same gate;
- denied mutation intents are persisted;
- budgets stop runs predictably;
- duplicate suggestions are idempotent;
- advisory semantic scoring and utility assessment work through existing services;
- family proposal action is optional and bounded;
- complete run preserves canonical field and cell counts;
- local HTTP/API and Browser UI are covered;
- release ZIP is verified after extraction.

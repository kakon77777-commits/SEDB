# SEDB v0.4B — Reflexive Autonomous Canonical Commit Kernel Design

## Goal

SEDB v0.4B converts reviewed advisory evidence into autonomous canonical commits when the action falls inside an explicit delegated autonomy surface, while preserving open-world action classification, minimum necessary constraint, authority integrity, and auditable Decision/Commit separation.

The governing invariants are:

$$
\boxed{\text{Consensus}\neq\text{Authority}}
$$

$$
\boxed{\text{NovelAction}\not\Rightarrow\text{Unauthorized}}
$$

$$
\boxed{\text{Capability}\neq\text{Authority}}
$$

$$
\boxed{\text{SelfProposal}\neq\text{SelfGrant}}
$$

$$
\boxed{\text{Decision}\neq\text{Commit}}
$$

and the autonomy objective is:

$$
\boxed{\text{Maximum Self-Direction}+\text{Minimum Necessary Constraint}+\text{Auditable History}}.
$$

## Scope

v0.4B adds a property-based authority classifier, immutable authority envelopes, public-state self-constraint snapshots, immutable Decision Receipts, atomic canonical Commit Receipts, compensating Rollback Receipts, autonomy metrics, HTTP endpoints, a minimal local UI, and reproducible release fixtures.

It does not add model-provider dependencies, permanent AI self-grant of authority, hidden-chain-of-thought extraction, destructive hard delete, automatic external deployment, or autonomous contract amendment.

## Rule taxonomy

SEDB preserves the Phase-8 distinction:

$$
\boxed{\text{Method}\neq\text{SelfCommitment}\neq\text{RelationalBoundary}}.
$$

Only canonical shared-world commit candidates enter this kernel. Ordinary cognition, search, scoring, family proposal, utility assessment, and campaign coordination remain callable methods or advisory operations and are not retrofitted with mandatory commit governance.

## Open-world action classification

The kernel does not use an action-name whitelist as the authority model. Each candidate is classified into effect properties:

```text
external
shared_world
reversible
cost_units
resource_owner
authority_domain
public_commitment
irreversible
```

Known commit adapters may infer properties. Novel actions may supply explicit properties. Missing effect classification yields `DEFER`, not `REFUSE`.

An action may therefore receive an `EXECUTE` authority decision even when the runtime lacks a commit adapter. In that case commit fails as `CAPABILITY_MISSING`; the action is not relabeled unauthorized.

## Authority envelope

An envelope is immutable and explicitly installed. It contains:

```text
id
name
version
contract_ref
authority_ref
authority_domains
resource_owners
allow_external
allow_shared_world
allow_irreversible
max_cost_units
created_by
created_at
```

The default local envelope is intentionally bounded to the local SEDB canonical database and does not grant external authority.

$$
\boxed{\text{InsideEnvelope}\Rightarrow\text{DefaultAutonomous}}.
$$

Novel actions are still classified by effect properties; absence from a name list is not denial.

No autonomous action adapter may create or activate an authority envelope. Envelope installation is an administrative boundary, preserving:

$$
\boxed{\text{SelfProposal}\neq\text{SelfGrant}}.
$$

## Public-state self-constraint

Self-constraint is evaluated only for canonical commit candidates. It uses public SEDB state and evidence metadata, not private chain of thought.

The snapshot may record callable method labels such as:

```text
VERIFY
COUNTEREXAMPLE
BACKTRACK
COMPARE
STOP
DECOMPOSE
```

They describe the preflight checks actually selected for this candidate and are not universal cognition hooks.

Examples:

- stale basis -> `STOP`;
- incompatible/disputed consensus -> `COMPARE`, `STOP`;
- irreversible shared-world effect -> `VERIFY`, `COUNTEREXAMPLE`;
- reversible, current, inside-envelope action -> minimal `VERIFY` only.

This implements minimum necessary constraint rather than maximum gate count.

## Decision engine

A Decision Receipt is immutable and stores:

```text
action
classified properties
EXECUTE / REFUSE / DEFER / IDLE / ESCALATE
reason codes
summary
envelope id
contract ref
authority ref
basis hash
constraint snapshot hash
evidence refs
evaluator
timestamp
```

Consensus packets are evidence only. `disputed`, `incompatible`, and `basis_incompatible` packets force escalation or deferral regardless of raw vote count.

Decision outcomes:

- `EXECUTE`: authority conditions are satisfied;
- `ESCALATE`: action crosses a relational or authority boundary;
- `DEFER`: effect classification, cost, or current evidence is insufficient;
- `REFUSE`: an explicit denial condition exists;
- `IDLE`: no commit action is warranted.

v0.4B primarily exercises `EXECUTE`, `ESCALATE`, and `DEFER`.

## Decision != Commit

An `EXECUTE` Decision Receipt does not mutate canonical state.

Commit is a separate preflight and transaction:

$$
\text{DecisionReceipt}
\rightarrow
\text{BasisRevalidation}
\rightarrow
\text{ConstraintRevalidation}
\rightarrow
\text{AdapterCapability}
\rightarrow
\text{AtomicTransaction}
\rightarrow
\text{CommitReceipt}.
$$

If any precondition changed, the decision remains historical but no commit occurs.

## v0.4B executable adapters

The initial commit kernel supports four bounded canonical mutations:

1. `accept_proposal` — accept a pending field proposal and create or alias a canonical field;
2. `transition_field` — bounded lifecycle transitions through existing lifecycle semantics;
3. `update_definition` — append a new immutable field definition version;
4. `set_guardrail` — append protect/unprotect guardrail state.

This adapter list is a capability list, not an authority whitelist.

## Atomic commit receipt

Successful commit stores, in the same database transaction as the canonical mutation:

```text
decision_id
transaction_id
action_type
before_state_sha256
after_state_sha256
mutation payload
rollback action
rollback mode
authority envelope ref
constraint snapshot ref
created_at
```

A separate append-only commit event ledger records preflight, committed, failed, rolled_back, and rollback_failed events.

## Reversible-first and rollback

Reversibility widens the safe autonomy surface.

v0.4B uses compensating rollback, not history erasure. Historical Decision/Commit receipts remain immutable.

Examples:

- `transition_field` -> append inverse lifecycle transition;
- `update_definition` -> append a new version restoring previous definition;
- `set_guardrail` -> append opposite guardrail event;
- `accept_proposal` -> operational compensation: remove an alias created solely by the commit or deprecate a newly created field when safe; the original decision history remains.

Rollback itself produces an immutable Rollback Receipt.

## Basis and staleness

The action basis hash covers the canonical objects the adapter depends on, plus selected consensus/evidence state. Commit recomputes the hash.

$$
H(B_t)\neq H(B_{t+1})
\Rightarrow
\text{NO COMMIT}.
$$

This prevents stale decisions from mutating a changed canonical world.

## Autonomous execute convenience path

`execute_autonomously()` performs:

1. persist Decision Receipt;
2. if decision is not `EXECUTE`, return without mutation;
3. if `EXECUTE`, invoke the separate commit step;
4. return both receipts.

The convenience method does not collapse Decision and Commit storage or transaction semantics.

## Autonomy metrics

Metrics are derived from append-only receipts, including:

```text
decision_count
execute_count
escalate_count
defer_count
refuse_count
commit_count
commit_failure_count
rollback_count
autonomous_commit_rate
escalation_rate
defer_rate
rollback_rate
novel_action_execute_rate
```

A descriptive effective-autonomy proxy may be reported as:

$$
A_{\mathrm{eff}}
=
\frac{N_{\mathrm{EXECUTE}}}
{N_{\mathrm{EXECUTE}}+N_{\mathrm{ESCALATE}}+N_{\mathrm{DEFER}}+N_{\mathrm{REFUSE}}}.
$$

It is an engineering metric, not a claim about subjective freedom or general intelligence.

## Safety and falsification conditions

The kernel is weakened or rejected if it:

- converts unknown action names into automatic denial;
- permits an AI action to install its own external authority;
- treats consensus count as authority;
- mutates canonical state before persisting a Decision Receipt;
- commits with stale basis;
- writes canonical mutation without a same-transaction Commit Receipt;
- silently erases Decision/Commit history during rollback;
- applies self-constraint as a mandatory cognition hook outside canonical commit boundaries;
- cannot distinguish authority failure from capability failure.

## Release success criteria

v0.4B must prove:

1. v0.4A migration preserves existing data and adds immutable autonomy ledgers;
2. strong independent evidence + inside-envelope reversible action can autonomously accept a proposal into a canonical field;
3. disputed/incompatible consensus cannot auto-commit;
4. novel legally classified action can receive `EXECUTE` but fail commit with `CAPABILITY_MISSING`;
5. stale decisions cannot commit;
6. rollback preserves history and produces a receipt;
7. envelope changes are not available as autonomous commit adapters;
8. all v0.4A tests remain green;
9. release ZIP is independently re-extracted and verified.

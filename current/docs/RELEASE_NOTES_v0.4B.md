# SEDB v0.4B Release Notes

Version: `0.4.0b1`  
Date: 2026-08-23  
Checkpoint: **Reflexive Autonomous Canonical Commit Kernel**

## Core change

v0.4B moves SEDB from advisory-only multi-Agent evidence into bounded autonomous canonical mutation under an explicit delegated authority envelope.

$$
\boxed{\text{Consensus}\neq\text{Authority}}
$$

$$
\boxed{\text{Decision}\neq\text{Commit}}
$$

$$
\boxed{\text{NovelAction}\not\Rightarrow\text{Unauthorized}}
$$

The kernel classifies an action by effect properties, resolves authority against an immutable envelope, creates a public-state self-constraint snapshot, records an immutable Decision Receipt, revalidates the basis at commit time, and then either performs an atomic canonical mutation or emits an auditable failure/escalation outcome.

## Open-world autonomy

v0.4B does not use the executable-adapter list as an authority whitelist. A novel action may be classified `EXECUTE` when its declared effects fall inside the delegated autonomy surface. If no executable adapter exists, the decision remains authority-valid while the commit fails with `CAPABILITY_MISSING`.

Therefore:

$$
\boxed{\text{Capability}\neq\text{Authority}}.
$$

Missing effect properties produce `DEFER`; external ownership or authority-domain violations produce `ESCALATE`. Semantic conflict such as an `incompatible` consensus packet also forces escalation rather than allowing consensus strength to override the boundary.

## Minimum-necessary self-constraint

Self-constraint is applied at the canonical commit boundary, not to every internal reasoning step. The v0.4B public-state vocabulary includes `VERIFY`, `COUNTEREXAMPLE`, `BACKTRACK`, `COMPARE`, `STOP`, and `DECOMPOSE`.

A normal reversible inside-envelope action receives the minimal verification constraint. Conflict adds `COMPARE + STOP`; irreversible shared actions add counterexample pressure and do not execute under the default local envelope.

The implementation uses public state and receipts only; it does not require or store hidden chain-of-thought.

## Decision / Commit separation

An `EXECUTE` Decision Receipt is not proof that canonical state changed.

$$
\boxed{\text{Decision}\neq\text{Commit}}.
$$

Commit revalidates the basis and constraint fingerprint, then performs the canonical mutation and writes its Commit Receipt inside one SQLite transaction. A stale basis is rejected before mutation.

The first executable adapters are:

```text
accept_proposal
transition_field
update_definition
set_guardrail
```

This is a runtime capability set, not a closed authority taxonomy.

## Rollback

v0.4B uses compensating rollback rather than historical deletion:

- a definition rollback appends a restoring immutable definition version;
- a guardrail rollback appends the opposite guardrail state;
- a lifecycle rollback performs the inverse governed transition;
- an accepted newly created field is compensated by deprecation;
- an alias created solely by a commit can be removed while the Commit Receipt remains immutable.

Decision and Commit history is never erased by rollback.

## Packaged governance evidence

`demo/sedb-autonomy-governance-v0.4b.sqlite` contains one reproducible sequence covering autonomous commit, conflict escalation, capability failure, and rollback.

```text
canonical fields before:       0
canonical fields after commit: 1
conflict decision:             ESCALATE
conflict commit:               none
novel action decision:         EXECUTE
novel commit result:           CAPABILITY_MISSING
successful commits:            1
compensating rollbacks:        1
rolled-back field status:      deprecated
```

Captured metrics:

```text
decision_count:             3
execute_count:              2
escalate_count:             1
commit_count:               1
commit_failure_count:       1
rollback_count:             1
autonomous_commit_rate:     0.5
escalation_rate:            0.3333333333333333
rollback_rate:              1.0
novel_action_execute_rate:  1.0
effective_autonomy_proxy:   0.6666666666666666
```

These values are fixture evidence for the implemented control path. They are not empirical proof that a foundation model is generally safe, self-constraining, or authorized outside the configured SEDB envelope.

## API

```text
GET    /api/autonomy/envelopes
POST   /api/autonomy/envelopes
GET    /api/autonomy/decisions
GET    /api/autonomy/stats
POST   /api/autonomy/decide
POST   /api/autonomy/execute
POST   /api/autonomy/decisions/{id}/commit
POST   /api/autonomy/commits/{id}/rollback
```

There is intentionally no Agent endpoint that can install or expand its own authority envelope.

## Validation target

The release gate requires the complete inherited test suite plus v0.4B autonomy tests, SQLite integrity checks, UTF-8 source validation, Markdown math-delimiter sanity, Python/JavaScript syntax checks, demo SHA-256 verification, manifest verification, clean ZIP extraction, and a zero-transient-path package.

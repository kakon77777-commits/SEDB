# SEDB v0.4B — AI-Native Unbounded Dynamic Field Database

**Semantic Evolution Database / Unbounded Dynamic Field Layer / Reflexive Autonomous Canonical Commit Kernel**

SEDB is a local-first experimental database for AI-native research, classification, curation, and record keeping where the logical field space can keep expanding without forcing every record to materialize every field.

The original invariant remains:

$$
\boxed{\text{Add Field}\not\Rightarrow\text{Fill Field}}
$$

v0.2A added canonical field governance:

$$
\boxed{\text{Unbounded Field Growth}\neq\text{Ungoverned Canonical Growth}}
$$

v0.2B added semantic candidates without automatic mutation:

$$
\boxed{\text{Similarity Candidate}\neq\text{Canonical Mutation}}
$$

v0.3A adds explainable operational utility and explicit lifecycle application:

$$
\boxed{\text{Assessment}\neq\text{Lifecycle Mutation}}
$$

A low score can produce a recommendation. It cannot silently converge a field.


v0.4B adds reflexive autonomous canonical commit inside explicit delegated authority envelopes:

$$
\boxed{\text{Consensus}\neq\text{Authority}}
$$

$$
\boxed{\text{Decision}\neq\text{Commit}}
$$

$$
\boxed{\text{NovelAction}\not\Rightarrow\text{Unauthorized}}
$$

Inside the delegated local canonical envelope, reversible bounded actions may commit autonomously after public-state self-constraint and preflight revalidation. Actions outside the authority surface escalate; actions with authority but without a runtime adapter fail as `CAPABILITY_MISSING`, preserving:

$$
\boxed{\text{Capability}\neq\text{Authority}}.
$$

## v0.4B highlights

Everything from v0.4A remains available. v0.4B adds:

- immutable autonomy envelopes, public-state constraint snapshots, Decision Receipts, Commit Receipts, commit events, and compensating Rollback Receipts;
- open-world action classification by effect properties rather than a closed authority whitelist;
- default autonomous execution for actions inside the delegated envelope;
- minimum-necessary self-constraint at the canonical commit boundary only;
- atomic `Decision → preflight → canonical mutation + Commit Receipt` transactions;
- executable adapters for proposal acceptance, field lifecycle transition, definition update, and guardrail state;
- compensating rollback without deleting historical Decision/Commit evidence;
- derived autonomy metrics including autonomous commit, escalation, defer, failure, novel-action, and rollback rates;
- local Autonomy API and Browser Decision/Commit receipt panel;
- no Agent route for self-installing or self-expanding an authority envelope.

### v0.4B Autonomy API

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

The envelope-install route is an administrative configuration surface. There is intentionally no `/api/agent/autonomy/envelopes` self-grant route.

### v0.4B packaged evidence

The reproducible governance fixture proves four distinct outcomes in one database:

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

The recorded autonomy metrics are:

```text
decisions:                 3
execute decisions:         2
escalations:               1
commit successes:          1
commit failures:           1
rollbacks:                 1
autonomous commit rate:    0.5
novel-action execute rate: 1.0
effective autonomy proxy:  0.6666666666666666
```

This fixture demonstrates that a novel action can be authority-legal while still being technically unavailable, and that rollback is compensating rather than historical erasure. Exact evidence is stored in `demo/autonomy-stats-v0.4b.json`.

v0.4A adds bounded multi-Agent coordination and evidence-aware advisory consensus:

$$
\boxed{\text{Multi-Agent Agreement}\neq\text{Canonical Authority}}
$$

$$
\boxed{\text{Consensus}\neq\text{Truth}}
$$

Campaigns coordinate independent governed Agent runs, preserve semantic conflict, and emit immutable consensus packets without changing canonical fields or sparse cells.

## v0.4A highlights

Everything from v0.3C remains available. v0.4A adds:

- campaign-level work queues, expiring leases, and bounded coordination budgets;
- links to already governed v0.3C Agent runs rather than a second Agent runtime;
- raw-support and independent-support accounting;
- backend / evidence-root diversity and basis-compatibility checks;
- `strong_agreement`, `weak_agreement`, `disputed`, `incompatible`, `insufficient_independence`, and `basis_incompatible` packets;
- immutable advisory-group and consensus snapshots;
- local campaign API and Browser advisory panel;
- no consensus-to-canonical mutation route.

### v0.4A Campaign API

```text
GET    /api/agent-campaigns
POST   /api/agent-campaigns
GET    /api/agent-campaigns/{id}
POST   /api/agent-campaigns/{id}/work
POST   /api/agent-campaigns/{id}/claim
POST   /api/agent-campaigns/{id}/link-run
POST   /api/agent-campaigns/{id}/aggregate
POST   /api/agent-campaigns/{id}/complete
```

### v0.4A packaged evidence

The governance fixture preserves canonical state while producing both agreement and incompatibility:

```text
canonical fields:       2 -> 2
canonical sparse cells: 1 -> 1
linked runs:            5
work items:             5
consensus packets:      2
packet states:          strong_agreement, incompatible
```

The `strong_agreement` packet has raw support 3 but independent support 2, explicitly demonstrating:

$$
N_{\mathrm{raw}}\neq N_{\mathrm{independent}}.
$$

A separate bounded coordination fixture processes 80 Agent runs across eight advisory keys:

```text
runs:               80
work items:         80
keys:               8
consensus packets:  8
packet status:      weak_agreement
canonical fields:   0 -> 0
canonical cells:    0 -> 0
elapsed here:       1.606748 s
```

That timing is specific to the packaged fixture and release environment, not a general performance promise. Exact evidence is stored in `demo/campaign-stats-v0.4a.json`.

v0.3C adds a governed provider-neutral AI Field Agent runtime:

$$
\boxed{\text{AI Autonomy}\neq\text{Canonical Authority}}
$$

The Agent may create advisory artifacts, but autonomous runs cannot mutate canonical fields or sparse cells.

## v0.3C highlights

Everything from v0.3B remains available. v0.3C adds:

- provider-neutral deterministic and external-suggestion backends;
- immutable observations, action receipts, and append-only run events;
- explicit capability allow/deny gate;
- budgeted steps, observations, proposals, semantic scores, family proposals, and assessments;
- raw structured observation discovery without numeric array-index field pollution;
- final-moment canonical/alias re-resolution before proposal creation;
- same-run and pending-proposal idempotence;
- advisory orchestration through existing semantic, utility, and family kernels;
- local Agent HTTP API and Browser receipt panel;
- no Agent canonical mutation endpoints.

### v0.3C Agent API

```text
GET    /api/agent/runs
GET    /api/agent/runs/{id}
POST   /api/agent/run/deterministic
POST   /api/agent/run/external
```

### v0.3C packaged validation evidence

The local release includes two reproducible v0.3C fixtures. The governance fixture preserves canonical state while producing advisory artifacts:

```text
canonical fields:        2 -> 2
canonical sparse cells:  1 -> 1
field proposals created: 3
semantic candidates:     4
utility assessments:     2
denied mutation receipts: 1 (`set_cell`)
budget-limited run:      budget_exhausted, 0 proposals
```

A separate deterministic structural-discovery fixture processes 2,000 records with 20 shared discoverable fields:

```text
records:           2,000
field width:       20
proposals created: 20
steps:             21
canonical fields:  0 -> 0
canonical cells:   0 -> 0
elapsed here:      0.867795 s
```

The timing is specific to the packaged fixture and release environment, not a general performance promise. Exact results are in `demo/agent-stats-v0.3c.json`.

v0.3B adds reviewed multi-field families without transitive synonymy:

$$
\boxed{\text{Pairwise Similarity}\not\Rightarrow\text{Family Truth}}
$$

$$
\boxed{\text{Confirmed Family}\not\Rightarrow\text{Automatic Merge / Alias / Cell Migration}}
$$

## v0.3B highlights

Everything from v0.3A remains available. v0.3B adds:

- immutable `field_family_proposals` and proposal members;
- complete-link coherence guard instead of connected-component synonymy;
- explicit `duplicate_family`, `related_family`, `split`, and `reject` reviews;
- stale proposal rejection through evidence-basis SHA-256;
- formal `field_families`, members, and append-only events;
- protection against overlapping active duplicate-family membership;
- split partition audit without automatic sub-family creation;
- bounded registry family scan built on the existing semantic candidate scan;
- local HTTP API and Browser **Field Families** panel;
- no embedding, LLM, network call, automatic merge, alias creation, or cell migration.

### Family coherence

For proposal group $G$:

$$
\operatorname{coh}_{\min}(G)=\min_{i<j}S(f_i,f_j),
$$

and every accepted member must satisfy the configured pairwise coherence threshold against every existing member. This prevents:

$$
A\sim B,\quad B\sim C,\quad A\not\sim C
$$

from being silently collapsed into one duplicate family.

### v0.3B family API

```text
GET    /api/family-proposals
GET    /api/family-proposals/{id}
POST   /api/family-proposals/generate
POST   /api/family-proposals/scan
POST   /api/family-proposals/{id}/review
GET    /api/field-families
GET    /api/field-families/{id}
```

### 10,000-field bounded family scan

The packaged v0.3B release fixture records:

```text
fields: 10000
naive all-pairs: 49,995,000
max_neighbors: 6
bounded pair upper bound: 60,000
family proposals: 2
planted coherent families found: 2/2
elapsed on this release environment: 4.974185 seconds
```

The elapsed time is evidence for this release environment and fixture only; it is not a universal performance claim.

## v0.3A highlights

Everything from v0.2B remains available, including sparse cells, field registry, lifecycle governance, proposals, aliases, immutable definition versions, lineage, semantic candidate scoring, Task Views, CSV/JSONL exchange, local API, and browser UI.

v0.3A adds:

- immutable `field_utility_assessments`;
- append-only `field_guardrails`;
- deterministic `utility-v1` operational-utility policy;
- recommendations: `keep`, `review`, `converge_candidate`, `reactivate_candidate`, `insufficient_evidence`;
- protected-field guardrail with auditable reason/evaluator;
- Task View support as an explicit utility signal;
- pending semantic-candidate redundancy as a negative signal;
- post-convergence cell / Task View evidence for reactivation candidacy;
- evidence-basis SHA-256 on every assessment;
- stale-assessment rejection before apply;
- explicit apply through the existing field lifecycle/evaluation ledger;
- bounded registry assessment up to 10,000 fields per call;
- local HTTP API and Browser Field Utility panel;
- no LLM, embedding, network call, or runtime third-party dependency.

## Operational utility policy

v0.3A intentionally calls this **operational utility**, not epistemic truth, scientific importance, or permanent knowledge value.

For field $f$:

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

- $C_f$ is sparse coverage over current entities;
- $T_f$ is $1$ when at least one Task View references the field, otherwise $0$;
- $R_f$ is the maximum unresolved field-to-field semantic-candidate score involving the field, otherwise $0$.

The score is then interpreted by lifecycle-aware guardrails. Current `utility-v1` constants are:

```text
minimum_age_days = 7
converge_threshold = 0.15
review_threshold = 0.35
```

Important examples:

- a brand-new empty field is `insufficient_evidence`, not immediately disposable;
- an old, unprotected, empty field with no Task View support can become `converge_candidate`;
- a protected field cannot receive `converge_candidate`;
- a Task View can preserve a rare field;
- unresolved semantic redundancy can lower the score;
- a converged field with new post-convergence cell or Task View evidence becomes `reactivate_candidate`.

## Assessment / apply separation

The lifecycle path is deliberately two-stage:

$$
\text{Evidence}
\rightarrow
\text{Assessment}
\rightarrow
\text{Recommendation}
\rightarrow
\boxed{\text{Explicit Apply}}
\rightarrow
\text{Field Transition}.
$$

Before apply, SEDB recomputes the evidence basis. If relevant state changed after assessment, apply is rejected as stale and a new assessment is required.

This prevents an old recommendation from closing a field after new evidence appeared.

## Requirements

- Python 3.11+;
- SQLite included with Python;
- no runtime third-party dependencies;
- `pytest` only for tests.

## Windows PowerShell quick start

```powershell
cd SEDB-v0.3B-local
python -m pip install -e .
sedb demo --db .\sedb-demo.sqlite --fields 10000
sedb serve --db .\sedb-demo.sqlite --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

The Browser UI includes a **Field Utility** panel. `Assess` only creates an immutable assessment. A separate Apply action is required for actionable lifecycle recommendations.

## Python utility example

```python
from sedb.db import Database
from sedb.fields import FieldService
from sedb.utility import UtilityService


db = Database("research.sqlite")
fields = FieldService(db)
utility = UtilityService(db)

field = fields.create_field(
    key="legacy_dimension",
    label="Legacy dimension",
)

assessment = utility.assess_field(
    field["id"],
    evaluator="agent:utility-audit",
)

print(assessment["score"])
print(assessment["recommendation"])
```

To protect a rare but important field:

```python
utility.set_guardrail(
    field["id"],
    True,
    reason="Required by compliance review even when sparsely used.",
    evaluator="human:reviewer",
)
```

To apply an actionable and still-current recommendation:

```python
utility.apply_assessment(
    assessment["id"],
    reason="Reviewed and accepted after evidence inspection.",
    evaluator="human:reviewer",
)
```

## Important local API routes

```text
POST   /api/fields/{id}/utility/assess
GET    /api/fields/{id}/utility/assessments
POST   /api/fields/{id}/guardrail
GET    /api/fields/{id}/guardrail
POST   /api/governance/utility/scan
POST   /api/utility/assessments/{id}/apply
```

All v0.2B semantic/governance routes remain available.

## Utility demos

Small governance fixture:

```bash
PYTHONPATH=src python examples/utility_demo.py \
  --db demo/sedb-utility-governance-v0.3a.sqlite \
  --benchmark-db demo/sedb-utility-10k-v0.3a.sqlite \
  --fields 10000
```

The packaged governance fixture demonstrates:

```text
fresh_empty         -> insufficient_evidence
old_unused          -> converge_candidate
protected_unused    -> keep
task_supported      -> keep
semantic_review     -> review
reactivation_signal -> reactivate_candidate
```

The `old_unused` field is then explicitly applied and becomes `converged`, with the assessment ID preserved in the existing lifecycle evaluation evidence.

## 10,000-field bounded utility assessment

The packaged release run recorded:

```text
fields: 10000
entities: 3
assessments: 10000
limit_fields: 10000
policy: utility-v1
recommendations: converge_candidate = 10000
elapsed on this release environment: 0.476007 seconds
```

This is evidence for the concrete release environment and fixture only. It is not a universal performance claim.

## Validation

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src examples
node --check src/sedb/web/app.js
```

Release packaging additionally validates canonical UTF-8 text, Markdown math delimiters, SQLite integrity, tracked-file SHA-256 manifest, ZIP CRC, and a fresh extracted-copy test run.

## Project status

This artifact is the **local v0.3B checkpoint**. GitHub remains intentionally unchanged during local-first development.

$$
\boxed{\text{Local Development}\rightarrow\text{Validation}\rightarrow\text{Stable Snapshot}\rightarrow\text{Selective GitHub Sync}}
$$

## Licensing status

No public software license is selected by this local artifact. Do not infer an open-source license from the source bundle or public repository.

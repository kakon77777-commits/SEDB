# FromJianghu Static Catalog for SEDB

This project is an independent, local SEDB v0.4B consumer for the preserved
static research of `我来自江湖` (`FromJianghu`). It classifies Build identity,
state owners, declarative functions, triggers, logical assets, evidence claims,
and dnSpy IL anchors without changing the game or SEDB core.

## Authority boundary

- Source access is one-way and read-only from
  `D:\AI_RESIDENCE\AI_gamedesign\FromJianghu-research`.
- The selected current snapshot is Steam Build `25099888`, game version
  `0.6.16`; Build `24413414` is retained as historical evidence.
- Twelve source artifacts are pinned by exact SHA-256 before parsing.
- Importer-owned records are immutable for the selected Build. A source hash,
  entity, label, or source-owned cell difference blocks the complete batch.
- The local SQLite database and WAL/SHM sidecars are Git-ignored.
- Steam files, both game baselines, FromJianghu evidence, SEDB `current/`, and
  unrelated SEDB projects are never modified.
- Runtime remains `NOT_STARTED`; this database does not prove launch,
  reachability, visible behavior, save/load compatibility, or deterministic
  replay.

## Accepted classification

| SEDB entity kind | Count | Meaning |
|---|---:|---|
| `fj_build_snapshot` | 2 | Historical and current Build identity |
| `fj_build_delta` | 1 | Static Build 24413414 → 25099888 change summary |
| `fj_model_snapshot` | 72 | Managed model/state-owner candidates |
| `fj_function_snapshot` | 1,209 | Declarative function vocabulary and use |
| `fj_trigger_snapshot` | 2,364 | Per-trigger static structure and catalog |
| `fj_asset_snapshot` | 3,287 | Logical asset-to-bundle namespace |
| `fj_evidence_claim` | 23 | Evidence-ledger claims with confidence boundaries |
| `fj_il_anchor` | 21 | Current and historical MethodDef-bound IL evidence |
| **Total** | **6,979** | |

The accepted database contains 92 active fields, eight Task Views, 142,562
source-owned sparse cells, and zero proposals. The Task Views are:

- FromJianghu Build Provenance
- FromJianghu Build Evolution
- FromJianghu State Owners
- FromJianghu Function Catalog
- FromJianghu Trigger Catalog
- FromJianghu Asset Catalog
- FromJianghu Evidence Claims
- FromJianghu IL Provenance

This is a semantic catalog and evidence-governance layer, not a replacement for
the original JSON/CSV artifacts and not a runtime database. Material utility
versus strong flat-file queries has not yet been measured.

## Commands

Run from `D:\Ai\work together\SEDB`:

```powershell
$env:PYTHONPATH = 'current\src;projects\fromjianghu-static-catalog'

# Source verification and diff only; never creates the database.
python projects\fromjianghu-static-catalog\cli.py plan

# Atomic schema + record bootstrap. Immediate replay must be no_op.
python projects\fromjianghu-static-catalog\cli.py bootstrap
python projects\fromjianghu-static-catalog\cli.py bootstrap

python projects\fromjianghu-static-catalog\cli.py stats
python projects\fromjianghu-static-catalog\cli.py classify
python projects\fromjianghu-static-catalog\cli.py search ElapsedTimeEvent --limit 12
python projects\fromjianghu-static-catalog\cli.py search 游戏时间事件 --limit 12
python projects\fromjianghu-static-catalog\cli.py search FJ-021 --limit 10
python projects\fromjianghu-static-catalog\cli.py show ENTITY_ID
```

Every command emits one UTF-8 JSON document. `plan` uses SQLite read-only mode
when a database exists; it rejects conflicting field/view definitions without
repairing them.

Exit codes:

- `0`: ready, imported, no-op, stats, classification, or query success;
- `1`: unexpected error;
- `2`: arguments, source contract, source hash, or source-shape failure;
- `3`: SEDB field/view schema conflict;
- `4`: existing source-owned record conflict or record missing from source;
- `5`: database, transaction, readback, integrity, or lookup failure.

## Measured acceptance — 2026-09-09

| Measurement | Result |
|---|---:|
| Source files pinned | 12 |
| Catalog fingerprint | `a01b8a8cc52dc4b376fc557f1795073928c488cd8eb1a80dcd59bf2c38234027` |
| First bootstrap | 6,979 entities / 142,562 cells |
| Immediate replay | 0 new / 6,979 unchanged / `no_op` |
| Plan replay | ready / write performed false |
| SQLite integrity | `ok` |
| SQLite bytes | 46,174,208 |
| SQLite SHA-256 | `bbdcc91bd8cbb20be5d297400bdea97f6ff32935b196b8cfbc72c350328194b7` |
| Project tests with live acceptance | 13 passed |
| Inherited SEDB v0.4B tests | 189 passed |

The database hash remained identical across a checkpointed no-op bootstrap.
The `FJ-021` query returned the expected evidence claim with its
`observed with causal static explanation` status and `not_started` runtime
boundary.

Machine-readable receipts are in [`evidence`](evidence), and the repeatable
verification sequence is in [`VERIFY.md`](VERIFY.md).

## Closure vector

- Behavioral: `PASS` for the pinned static import, classification, query,
  transaction, no-op replay, and integrity scope.
- Structural: `PARTIAL`; the catalog maps known static evidence but does not
  freshly reconstruct the whole game architecture.
- Discriminative: `PARTIAL`; fixture tests reject source drift, duplicate IDs,
  schema conflicts, source-owned cell conflicts, and injected transaction
  failure.
- Runtime: `NOT_STARTED`.
- Independent MSSP Twin: unavailable and not simulated.

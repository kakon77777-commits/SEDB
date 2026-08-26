# Unbounded Axiom Corpus SEDB Month-Split MVP Design

- Date: 2026-08-26
- Status: Approved in conversation; awaiting written-spec review
- Implementation repository: `D:\Ai\work together\SEDB`
- Project directory: `D:\Ai\work together\SEDB\projects\unbounded-axiom-corpus`
- Source corpus: `D:\Ai\work together\unbounded-axiom\registry\papers.json`
- Local database: `D:\Ai\work together\SEDB\projects\unbounded-axiom-corpus\unbounded-axiom-corpus.sqlite`
- SEDB baseline: local `current/` v0.4B

## 1. Purpose

Build a small, deterministic SEDB consumer project for the already-published
Unbounded Axiom paper corpus. The project imports one publication month at a
time from the corpus registry into one cumulative local SQLite database.

The MVP exists to validate four properties before any paper-content or AI field
discovery work begins:

1. the published registry can be projected into SEDB without rescanning source
   files or recomputing hashes;
2. a month can be imported incrementally and rerun as a true no-op;
3. source drift is reported explicitly and never resolved by silent overwrite,
   deletion, movement, or identity reassignment;
4. SEDB's sparse, governed field model can later accept AI-proposed research
   dimensions without coupling those dimensions to bootstrap metadata.

The first live acceptance month is `2026-04`, the earliest and smallest month
in the current corpus, with 87 papers.

## 2. Authority and dependency boundaries

### 2.1 Source authority

`D:\Ai\work together\unbounded-axiom\registry\papers.json` is authoritative
for the metadata imported by this MVP. The importer reads that file directly.
It does not walk `content/papers`, inspect paper bodies, or recompute source
hashes.

The Unbounded Axiom repository is read-only to this project. The importer must
not create, modify, delete, stage, commit, or deploy anything in that
repository.

### 2.2 SEDB authority

The new local SQLite database is authoritative only for its SEDB projection and
future SEDB-local governance state. It does not replace the corpus registry and
does not become a publication source.

### 2.3 Dependency direction

The dependency is intentionally one-way:

```text
SEDB/projects/unbounded-axiom-corpus
  -> reads unbounded-axiom/registry/papers.json
  -> imports SEDB/current/src/sedb

unbounded-axiom
  - has no SEDB import
  - has no SEDB configuration
  - does not know this project exists
```

### 2.4 Git and workspace boundary

The MVP is developed directly on the existing SEDB `main` branch. No new
worktree or feature branch is required. Existing unrelated and untracked files,
including the current `projects/amral-ns-symbols` tree and the source brief,
must be preserved.

The generated SQLite database, WAL/SHM files, Python caches, and pytest caches
are ignored by Git. Implementation commits include only the new project source,
tests, and documentation explicitly in scope.

### 2.5 Action boundary

This design authorizes local project implementation and local validation. It
does not authorize deployment, release, publication, merge, remote database
synchronization, CTCL registration, or mutation of SEDB core.

## 3. MVP scope

### 3.1 Included

- one cumulative local SQLite database;
- 11 fixed bootstrap metadata fields;
- one SEDB entity per paper, keyed by the permanent Logic Matrix ID;
- namespace-aware, idempotent schema initialization;
- one idempotent metadata Task View;
- strict registry validation;
- required `--month YYYY-MM` incremental bootstrap;
- deterministic difference planning;
- whole-batch blocking on any unresolved source difference;
- transactionally atomic creation of all new entities and cells in a successful
  month batch;
- stable machine-readable JSON command results;
- local statistics and SQLite integrity checks;
- a live `2026-04` import and immediate no-op rerun.

### 3.2 Explicitly excluded

- reading or classifying paper full text;
- extracting detailed human authors, institutions, or AI collaborators from
  paper bodies;
- importing the coarse registry `authorship` field;
- importing `legacy_slug`, `ext`, `raw_url`, `api_url`, or other legacy-routing
  compatibility metadata;
- filesystem scanning, rehashing, package/component decomposition, or content
  identity discovery;
- copy, translation, CTCL, temporal reconciliation, or staging movement;
- automatic field creation from AI output;
- automatic theory-family, dependency, supersession, or companion inference;
- automatic repair, overwrite, deletion, relocation, or re-identification;
- a mode that skips conflicting papers and writes the rest of a hot month;
- separate SQLite files per month;
- modifications to `SEDB/current/`.

The future AI proposal pass is a separate phase. It may use SEDB's proposal,
semantic, utility, family, Agent, or autonomy layers only under a separately
approved design.

## 4. Chosen architecture

The MVP uses a thin consumer project rather than a one-file script or a reduced
copy of `shared-artifact-catalog`.

```text
projects/unbounded-axiom-corpus/
  .gitignore
  README.md
  config.py
  source.py
  store.py
  cli.py
  tests/
    conftest.py
    test_source.py
    test_store.py
    test_cli.py
    test_live_acceptance.py
```

Responsibilities are deliberately narrow:

- `config.py` defines the default source path, local database path, field
  specifications, entity kind, namespace, Task View name, and injectable test
  configuration.
- `source.py` loads, validates, filters, and normalizes registry data into
  immutable paper records. It performs no SEDB writes.
- `store.py` wraps the SEDB v0.4B services, initializes the schema and Task View,
  computes the current SEDB-side projection, creates deterministic difference
  plans, and applies a successful new-record plan in one SQLite transaction.
- `cli.py` exposes `init`, `bootstrap`, and `stats`, maps typed failures to exit
  codes, and prints one deterministic JSON result.
- `tests/` uses temporary registries and SQLite databases except for the
  explicitly marked local live-acceptance test.

The project consumes only the generic SEDB core surface needed by the MVP:

```python
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService
```

It does not import `shared-artifact-catalog` modules or taxonomy.

## 5. Data model

### 5.1 Paper identity

Each paper maps to one globally identified SEDB entity:

```text
entity.id    = registry item id, for example lm-000001
entity.kind  = unbounded_axiom_paper
entity.label = registry item title
```

The permanent `lm-NNNNNN` identifier remains authoritative across every month.
Month is a property of that identity, not part of the identity.

### 5.2 Field registry

All MVP fields use namespace `unbounded_axiom` and `value_type="text"`.
The project owns exactly these 11 fields:

| Registry key | SEDB field key | Exact label | Exact description |
|---|---|---|---|
| `id` | `paper_id` | `Paper ID` | `Permanent Logic Matrix paper ID.` |
| `title` | `title` | `Title` | `Paper title recorded by the Unbounded Axiom registry.` |
| `source_file` | `source_file` | `Source file` | `Canonical source path recorded by the Unbounded Axiom registry.` |
| `language` | `language` | `Language` | `Paper language tag recorded by the Unbounded Axiom registry.` |
| `created` | `created_date` | `Created date` | `Publication or upload date recorded by the registry when present.` |
| `year` | `year` | `Year` | `Registry year represented as canonical text.` |
| `month` | `month` | `Month` | `Registry publication month and bootstrap partition key.` |
| `hash` | `sha256` | `SHA-256` | `Registry SHA-256 identity string preserved verbatim.` |
| `canonical_url` | `canonical_url` | `Canonical URL` | `Permanent public paper route recorded by the registry.` |
| `date_confidence` | `date_confidence` | `Date confidence` | `Registry confidence class for the recorded date.` |
| `date_basis` | `date_basis` | `Date basis` | `Registry provenance statement explaining the recorded date basis.` |

`paper_id` intentionally duplicates the entity ID as a field so Task Views and
field-oriented queries can project it without special entity-ID handling.

### 5.3 Blank-by-absence

Missing or JSON `null` source values do not create a cell. They are not written
as an empty string, `null`, `unknown`, `N/A`, zero, or another placeholder.

The expected cell count for a batch is therefore computed from the number of
nonblank owned values, not from `paper_count * 11`.

### 5.4 Future fields

Only the 11 MVP-owned fields participate in bootstrap comparison. Future
canonical fields or cells introduced through separately governed AI proposal
work are ignored by the bootstrap difference algorithm. This preserves the
separation between source metadata synchronization and evolving research
dimensions.

### 5.5 Task View

Initialization creates one Task View named:

```text
Unbounded Axiom Paper Metadata
```

It projects the 11 fields in the order shown above. Initialization reuses an
existing exact-name view only when its ordered field identities match. A name
match with a different field projection is a schema conflict.

## 6. Source validation and normalization

### 6.1 Top-level validation

The source loader requires:

- a JSON object;
- supported registry version `0.2`;
- integer `count`;
- array `items`;
- `count == len(items)`;
- globally unique nonempty paper IDs;
- IDs matching `lm-NNNNNN`;
- no duplicate source item for the same ID.

Selected paper hashes must match `sha256:` followed by 64 lowercase hexadecimal
characters. The importer validates this registry contract but does not recompute
the digest from paper bytes.

Unknown registry versions fail closed. Future version support requires an
explicit project update.

### 6.2 Month argument

`--month` is mandatory for `bootstrap` and must match `YYYY-MM` with a real
month from `01` through `12`.

A syntactically valid month that selects zero papers is an error with reason
code `target_month_empty`. It is never reported as `imported`, `no_op`, or a
successful zero-count batch.

### 6.3 Selected-item validation

Every selected paper requires nonblank values for:

- `id`;
- `title`;
- `source_file`;
- `language`;
- `year`;
- `month`;
- `hash`;
- `canonical_url`.

`created`, `date_confidence`, and `date_basis` may be absent or null and then
remain blank-by-absence. If present, they must be scalar text-compatible values.

The selected item's `month` must exactly equal the requested month. No inferred
month or filename fallback is allowed.

### 6.4 No derived source claims

The loader preserves `hash`, `date_confidence`, and `date_basis` as supplied.
It does not verify paper bytes, reinterpret dates, or claim that `created` is an
authorial writing date.

## 7. Difference model

The importer constructs the complete difference plan before creating any paper
entity.

### 7.1 States

Every relevant paper ID is classified as exactly one of:

- `new`: present in the selected source month and absent from the database;
- `unchanged`: present in both places with the same entity kind, entity label,
  and all 11 owned field values including blank-by-absence;
- `conflict`: the same global ID exists but its label, kind, or at least one
  owned field differs or is unexpectedly missing;
- `missing_from_source`: the database contains an entity assigned to the target
  month, but that ID is absent from the current target-month source selection.

The comparison ignores all non-owned fields.

### 7.2 Conflict detail

Conflict output is sorted by paper ID and then field key. Each difference
contains:

```json
{
  "field": "sha256",
  "expected": "source registry value",
  "actual": "current SEDB value",
  "reason": "value_mismatch"
}
```

Missing and blank are represented explicitly and are not collapsed into one
ambiguous string.

### 7.3 Month reassignment

Because paper identity is global, a paper that moves from one registry month to
another is not `new` in the new month when the database already contains its
ID.

- running the old month reports `missing_from_source`;
- running the new month reports `conflict` with reason code
  `month_reassignment` and shows the old and new month values;
- the MVP does not move, update, clone, delete, or re-ID the entity.

This preserves the unresolved revision for a future explicit migration or
revision-chain operation.

### 7.4 Whole-batch write gate

If the plan contains any `conflict` **or** any `missing_from_source`, the command
is blocked. It outputs every difference and creates no new paper entity.

This rule applies even when other papers in the same month are valid `new`
records. A future opt-in mode that excludes conflicting papers and imports the
remainder is deliberately outside this MVP.

## 8. Storage and transaction behavior

### 8.1 Schema initialization

`Database` initializes the SEDB v0.4B schema. `FieldService` and `ViewService`
then ensure the 11 fields and one Task View.

Initialization is idempotent only when an existing field has the expected raw
key, namespace, normalized identity, value type, label, description, and active
status. A mismatched existing field produces `schema_conflict`; the importer
does not rewrite it. The same rule applies to a conflicting exact-name Task
View projection.

### 8.2 Read behavior

`EntityService` and bounded direct queries retrieve existing paper entities and
their cells. Reads do not change existing values, field lifecycle, proposal
state, or timestamps.

### 8.3 Atomic creation

After a conflict-free preflight, `store.py` opens one SQLite transaction and
creates every `new` entity and every nonblank owned cell in that transaction.

Every created cell records `source="unbounded-axiom:registry/papers.json"` and
leaves generic numeric confidence unset. Date-specific confidence remains the
separate `date_confidence` value supplied by the registry and is not converted
into a fabricated numeric score. One UTC timestamp is shared by the entities
and cells created in the same batch.

The transaction adapter is project-local because the current public
`EntityService` methods open one connection per call. The adapter uses the
already-initialized SEDB v0.4B tables and canonical field IDs, preserves SEDB's
JSON cell encoding, performs create-only inserts, and contains no update or
delete path.

Any uniqueness, foreign-key, serialization, storage, or integrity failure
rolls back the complete month write. No partially imported paper remains.
SEDB core files and schemas are not modified.

### 8.4 Post-write verification

Before commit completion is reported, the command verifies:

- created entity count equals the planned `new` count;
- created cell count equals the computed nonblank-cell count;
- every new entity reads back with the expected owned projection;
- `PRAGMA integrity_check` returns `ok`.

## 9. CLI

Default invocation from the SEDB repository root:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python projects/unbounded-axiom-corpus/cli.py init
python projects/unbounded-axiom-corpus/cli.py bootstrap --month 2026-04
python projects/unbounded-axiom-corpus/cli.py stats
```

Test-only or operator overrides for source and database paths are explicit CLI
options or injected configuration values. Defaults point to the exact local
paths in this spec.

### 9.1 `init`

`init`:

1. opens or creates the ignored local SQLite file;
2. ensures the 11 fields;
3. ensures the Task View;
4. performs `integrity_check`;
5. returns schema creation/reuse counts.

### 9.2 `bootstrap --month YYYY-MM`

`bootstrap`:

1. validates the month argument;
2. initializes the schema idempotently;
3. reads and validates the source registry;
4. selects and validates the target month;
5. builds the complete difference plan;
6. blocks on any `conflict` or `missing_from_source`;
7. otherwise writes only `new` records in one transaction;
8. verifies readback and integrity;
9. prints the deterministic result.

When every selected record is `unchanged`, the result has `status="no_op"`,
`no_op=true`, and performs no paper-entity or paper-cell write.

### 9.3 `stats`

`stats` reports:

- total fields, entities, cells, proposals, and Task Views;
- paper entity count by month;
- logical capacity and sparse density;
- database integrity status.

It does not read paper full text or reinterpret registry metadata.

## 10. JSON result contract and exit codes

Every CLI command prints exactly one deterministic JSON document. Lists are
stably sorted. Expected command failures do not print a Python traceback.

Representative bootstrap result shape:

```json
{
  "result_version": 1,
  "command": "bootstrap",
  "status": "imported",
  "reason_code": null,
  "source": {
    "registry_version": "0.2",
    "registry_count": 3189,
    "month": "2026-04",
    "selected_count": 87
  },
  "diff": {
    "new": 87,
    "unchanged": 0,
    "conflict": 0,
    "missing_from_source": 0
  },
  "write": {
    "created_entities": 87,
    "created_cells": 0
  },
  "no_op": false,
  "integrity": "ok",
  "details": []
}
```

`created_cells` above is illustrative in shape only; the live expected value is
computed from nonblank source values and must not be hard-coded.

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | Successful `imported`, `no_op`, `init`, or `stats` result |
| `1` | Unclassified unexpected exception |
| `2` | Configuration, registry, month, or selected-source validation error |
| `3` | SEDB field or Task View schema conflict |
| `4` | Data difference blocked by `conflict` or `missing_from_source` |
| `5` | SQLite write, transaction, readback, or integrity failure |

Required reason codes include:

- `target_month_empty` for a valid month with zero selected papers;
- `schema_conflict` for an incompatible field or Task View;
- `source_conflict` for ordinary owned-data mismatch;
- `month_reassignment` for an existing global ID whose month changed;
- `missing_from_source` for database-only target-month identity;
- `storage_failure` and `integrity_failure` for exit-code-5 outcomes.

## 11. Error handling

- Invalid configuration or source data fails before difference planning.
- Schema conflict fails before paper difference planning and never overwrites a
  field or Task View.
- Data conflict fails before the write transaction and returns all known
  conflicts in one result.
- An unexpected write failure rolls back the complete batch.
- An unexpected exception returns exit code `1` and a stable `error` result;
  developer diagnostics may go to stderr, but stdout remains one JSON document.
- No error path deletes existing entities, cells, fields, views, or source
  files.

## 12. Test strategy

Tests use temporary paths and deterministic fixtures unless explicitly marked
as the local live acceptance. `test_live_acceptance.py` is opt-in, reads the
real registry, and writes only to a dedicated temporary or explicitly supplied
ignored database path; the ordinary project test command must not populate the
default persistent database as a side effect.

1. **Registry validation:** reject malformed top-level JSON, unsupported
   version, count mismatch, duplicate/global-invalid IDs, invalid month values,
   and missing selected-item requirements.
2. **Empty target month:** a correctly formatted month with zero selected
   papers must return `status="error"`, reason `target_month_empty`, and exit
   code `2`; it must not be `imported` or `no_op`.
3. **Schema idempotency:** repeated `init` creates no duplicate field or view and
   preserves canonical schema state.
4. **Schema conflict:** an existing same-key field with incompatible namespace,
   value type, definition, or Task View projection returns `schema_conflict`,
   exit code `3`, blocks bootstrap, and leaves the existing schema unchanged.
5. **First import:** a clean month creates exactly the planned entities and the
   exact computed number of nonblank cells.
6. **No-op rerun:** an immediate rerun produces only `unchanged`, reports
   `no_op=true`, and leaves logical database state unchanged.
7. **Conflict gate:** a fixture with one conflicting existing paper and one new
   paper reports both but writes neither new entity nor cell.
8. **Missing-source gate:** a fixture with `missing_from_source` plus a valid new
   paper reports both and writes neither new entity nor cell.
9. **Month reassignment:** an existing global ID whose registry month changes
   produces `missing_from_source` in the old month and `month_reassignment`
   conflict in the new month; it is never created twice or assigned a new ID.
10. **Blank-by-absence:** absent/null optional source values create no cell and
    remain distinct from false, zero, empty string, or explicit text.
11. **Future-field isolation:** an additional non-MVP field and cell on a paper
    does not change bootstrap comparison; the owned projection remains
    `unchanged`.
12. **Transaction rollback:** an injected failure during entity/cell creation
    rolls back every entity and cell from that batch.
13. **Database integrity:** initialized, imported, no-op, blocked, and rolled-back
    fixtures all retain `PRAGMA integrity_check = ok`.
14. **Live `2026-04` acceptance:** against the real registry, select exactly 87
    papers, import them, compare entity and computed cell counts, rerun to prove
    `unchanged=87`, `new=0`, and `no_op=true`, and verify source-registry SHA-256
    plus Unbounded Axiom Git status are unchanged before and after.

The live test must not assume that every paper has 11 cells. It computes the
expected count from current nonblank registry values.

The final operator acceptance also runs the same two CLI invocations against
the approved default local database when that path is new. If a database is
already present there, the workflow must not delete or overwrite it merely to
manufacture a clean first-run result; it uses a separately named ignored
acceptance database or stops for operator direction.

## 13. Acceptance criteria

The MVP is complete only when:

1. the new project exists at the approved path on SEDB `main`;
2. SEDB `current/` remains byte-unmodified;
3. project tests pass;
4. the full inherited SEDB v0.4B suite remains passing;
5. Python compilation succeeds for the new project;
6. the live source registry validates as version `0.2`, and its declared count
   equals the observed item length; the current total is recorded rather than
   treated as a permanent acceptance constant;
7. `2026-04` selects exactly 87 papers;
8. the first live bootstrap creates exactly 87 paper entities and the computed
   number of nonblank cells;
9. the immediate second bootstrap is a no-op with 87 unchanged entities;
10. SQLite integrity is `ok`;
11. the generated SQLite file and sidecars remain Git-ignored;
12. the Unbounded Axiom registry hash and worktree status are unchanged;
13. pre-existing unrelated SEDB changes and untracked trees are preserved;
14. no deployment, publication, release, remote write, CTCL call, source-file
    mutation, or SEDB-core mutation occurs.

## 14. Deferred follow-up work

Future designs may consider:

- an AI paper-content pass that creates pending field proposals for theory
  family, dependency, supersession, companion, proof, implementation, and
  concept-lineage dimensions;
- registrar review and canonical acceptance of selected proposals;
- explicit revision or month-reassignment migration operations;
- a hot-month partial-import mode that excludes blocked records while importing
  conflict-free records;
- richer authorship and institution extraction from paper bodies;
- views and queries specialized for research lineage.

None of these is an implicit extension point that may activate during this MVP.
Each requires separate scope, tests, and authority.

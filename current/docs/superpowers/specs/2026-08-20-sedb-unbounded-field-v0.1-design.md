# SEDB Unbounded Dynamic Field Layer v0.1 — Design Specification

## Status

Approved for local-first implementation on 2026-08-20. GitHub is documentation-only during this checkpoint; implementation remains local until a stable snapshot is reviewed.

## Goal

Build an AI-native sparse dynamic-field database where the global logical field set can grow to 10,000+ fields without requiring every record to populate every field, while preserving field lifecycle decisions and their reasons.

## Canonical principles

1. `Add Field != Fill Field`.
2. Blank is represented by absence of a sparse cell, not by forcing a placeholder value.
3. Logical schema width and physical storage density are independent.
4. Fields have lifecycle state; converging a field requires a non-empty reason assessment.
5. Converged fields remain queryable and may be reactivated.
6. Task views are projections over the same database, not copied tables.
7. Field and cell history is auditable enough to explain why the current schema exists.
8. Local-first: no implementation write to GitHub during v0.1 development.

## Logical model

Let `E` be entities, `F` the open-ended set of fields, and `D_f` the value domain for field `f`.

$$
V:E\times F\rightarrow D_f\cup\{\varnothing\}
$$

Only non-empty values are physically stored:

$$
C=\{(e,f,v)\mid V(e,f)\neq\varnothing\}.
$$

For task `Q`, only a selected support is rendered:

$$
F_Q\subseteq F.
$$

The system therefore permits `|F| >= 10,000` while keeping each record sparse.

## v0.1 storage architecture

SQLite stores normalized sparse structures rather than adding physical SQL columns:

- `entities`: record identity and label.
- `fields`: dynamic field registry.
- `cells`: sparse `(entity_id, field_id) -> JSON value` storage.
- `field_events`: append-only lifecycle events.
- `field_evaluations`: structured reason/evidence/metrics for converge/reactivate decisions.
- `field_proposals`: AI/user candidate fields before activation.
- `task_views`: named projections.
- `task_view_fields`: ordered fields in a projection.

Missing `(entity_id, field_id)` means blank. Explicit domain values such as `"unknown"`, `false`, `0`, or `null-like` strings remain distinguishable from absence.

## Field lifecycle

Supported states:

- `proposed`
- `active`
- `converged`
- `merged`
- `split`
- `deprecated`

Primary transitions:

- proposed -> active / deprecated
- active -> converged / merged / split / deprecated
- converged -> active / merged / split / deprecated

A transition into `converged` MUST include a non-empty `reason`. It also writes an evaluation record with evidence, metrics, evaluator identity, and reversibility. `converged -> active` is recorded as reactivation and also requires a reason.

## Services

### Database

`sedb.db.Database(path)` opens SQLite, enables foreign keys, and creates the schema.

### FieldService

- create/list/get fields
- bulk register fields
- lifecycle transitions
- create/list proposals
- evaluation history

### EntityService

- create/list/get entities
- set/get/delete sparse cells
- return one entity as sparse data keyed by field key

### ViewService

- create named task view from field keys
- fetch a matrix window for a field slice
- search fields/entities/cell text
- report storage statistics

### ExchangeService

- export/import JSONL entities with sparse `values`
- export/import CSV using headers as dynamic fields
- imports create missing fields only when explicitly enabled

## Browser application

A dependency-free local HTTP server exposes JSON APIs and serves a vanilla HTML/JS interface.

The UI contains:

1. stats panel;
2. field registry/search;
3. add-field form;
4. entity list/add form;
5. sparse matrix window showing only a limited field slice at once;
6. field-window navigation so 10,000+ logical fields never become 10,000 DOM columns;
7. lifecycle action for converge/reactivate with mandatory reason;
8. task-view creation and loading.

## API surface

- `GET /api/health`
- `GET /api/stats`
- `GET /api/fields?search=&status=&limit=&offset=`
- `POST /api/fields`
- `POST /api/fields/{field_id}/transition`
- `GET /api/fields/{field_id}/evaluations`
- `GET /api/proposals`
- `POST /api/proposals`
- `GET /api/entities`
- `POST /api/entities`
- `GET /api/entities/{entity_id}`
- `PUT /api/entities/{entity_id}/cells/{field_key}`
- `DELETE /api/entities/{entity_id}/cells/{field_key}`
- `GET /api/search?q=`
- `POST /api/views`
- `GET /api/views/{view_id}?field_offset=&field_limit=`

## Validation target

The automated suite must demonstrate:

- fields can be created without creating cells;
- sparse values preserve type through JSON encoding;
- blank and present values remain distinguishable;
- convergence without a reason is rejected;
- convergence writes evaluation history;
- converged fields can reactivate with a reason;
- a task view projects only selected fields;
- JSONL and CSV round trips preserve sparse values;
- 10,000 fields can be registered while only a small number of cells exist;
- HTTP API and static UI boot successfully.

## Non-goals for v0.1

- distributed database clustering;
- PostgreSQL/DuckDB backends;
- vector embeddings;
- automatic LLM provider integration;
- full semantic deduplication of proposed fields;
- production authentication/authorization;
- multi-user synchronization;
- pushing implementation to GitHub.

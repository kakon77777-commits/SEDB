# SEDB Unbounded Dynamic Field v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a local-first, executable SEDB v0.1 that supports 10,000+ logical dynamic fields, sparse cells, reason-governed field convergence/reactivation, task projections, search, exchange formats, and a browser UI.

**Architecture:** Python 3.13 and SQLite provide a zero-service local core. Dynamic fields live in a registry and cell values live in a sparse join table, while field events/evaluations retain governance history. A standard-library HTTP server exposes JSON APIs and serves a vanilla browser UI that renders only a field window instead of thousands of DOM columns.

**Tech Stack:** Python 3.13, SQLite 3.46+, pytest 9, standard-library `http.server`, HTML/CSS/vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-20-sedb-unbounded-field-v0.1-design.md`

## Global Constraints

- Implementation is local-first and MUST NOT be pushed to GitHub in v0.1.
- Blank cells are absence of a `cells` row; registering a field MUST NOT create cells.
- A transition to `converged` MUST reject an empty reason.
- A transition from `converged` to `active` MUST reject an empty reason.
- Task views MUST project the existing sparse database rather than copy records.
- The suite MUST exercise a registry of at least 10,000 logical fields.
- Runtime dependencies are Python standard library only; pytest is test-only.
- UTF-8 source files are canonical artifacts.

---

### Task 1: Sparse SQLite core and field registry

**Files:**
- Create: `pyproject.toml`
- Create: `src/sedb/__init__.py`
- Create: `src/sedb/db.py`
- Create: `src/sedb/fields.py`
- Create: `tests/test_fields.py`

**Interfaces:**
- Produces: `Database(path)`, `FieldService(db)`, `FieldService.create_field(...)`, `bulk_create_fields(...)`, `transition(...)`, `create_proposal(...)`, `list_evaluations(...)`.

- [ ] Write tests proving field creation does not create cells, field keys are unique, bulk creation supports 10,000 fields, convergence requires a reason, and reactivation writes evaluation history.
- [ ] Run `pytest tests/test_fields.py -q` and verify RED because `sedb` is missing.
- [ ] Implement SQLite schema creation in `Database` and minimal `FieldService` behavior required by tests.
- [ ] Run `pytest tests/test_fields.py -q` and verify GREEN.
- [ ] Commit `feat: add sparse field registry and lifecycle governance`.

### Task 2: Entities and sparse cells

**Files:**
- Create: `src/sedb/entities.py`
- Create: `tests/test_entities.py`

**Interfaces:**
- Consumes: `Database`, field registry.
- Produces: `EntityService.create_entity`, `list_entities`, `get_entity`, `set_cell`, `delete_cell`.

- [ ] Write tests for entity creation, JSON typed values, missing-cell blank semantics, overwrite, and delete.
- [ ] Run `pytest tests/test_entities.py -q` and verify RED because `EntityService` is missing.
- [ ] Implement minimal sparse entity/cell service.
- [ ] Run `pytest tests/test_entities.py -q` and verify GREEN.
- [ ] Commit `feat: add sparse entity cells`.

### Task 3: Task views, field-window matrix, search, and statistics

**Files:**
- Create: `src/sedb/views.py`
- Create: `tests/test_views.py`

**Interfaces:**
- Consumes: `Database`, `FieldService`, `EntityService`.
- Produces: `ViewService.create_view(name, field_keys)`, `get_view_matrix(view_id, field_offset, field_limit)`, `search(query)`, `stats()`.

- [ ] Write tests proving a view projects selected fields, matrix windows slice fields without copying cells, search finds field/entity/value text, and stats report 10,000 fields with sparse cell count unchanged.
- [ ] Run `pytest tests/test_views.py -q` and verify RED.
- [ ] Implement minimal view/search/stat service with SQL plus Python JSON decoding.
- [ ] Run `pytest tests/test_views.py -q` and verify GREEN.
- [ ] Commit `feat: add task projections search and stats`.

### Task 4: CSV and JSONL exchange

**Files:**
- Create: `src/sedb/exchange.py`
- Create: `tests/test_exchange.py`

**Interfaces:**
- Produces: `ExchangeService.export_jsonl`, `import_jsonl`, `export_csv`, `import_csv`.

- [ ] Write round-trip tests that preserve sparse values and verify missing CSV cells remain absent rather than becoming placeholder cells.
- [ ] Run `pytest tests/test_exchange.py -q` and verify RED.
- [ ] Implement deterministic UTF-8 JSONL/CSV exchange and optional missing-field creation.
- [ ] Run `pytest tests/test_exchange.py -q` and verify GREEN.
- [ ] Commit `feat: add sparse CSV and JSONL exchange`.

### Task 5: Local HTTP API and browser UI

**Files:**
- Create: `src/sedb/server.py`
- Create: `src/sedb/web/index.html`
- Create: `src/sedb/web/app.js`
- Create: `src/sedb/web/style.css`
- Create: `tests/test_server.py`

**Interfaces:**
- Produces: `create_server(db_path, host, port)`, JSON routes from the spec, static `/`, `/app.js`, `/style.css`.

- [ ] Write HTTP tests for health, field/entity creation, cell write, converge reason rejection, stats, and a static index containing the SEDB title.
- [ ] Run `pytest tests/test_server.py -q` and verify RED.
- [ ] Implement API routing with `ThreadingHTTPServer` and JSON request/response helpers.
- [ ] Implement browser UI with field search, entity creation, selected-field matrix window, converge/reactivate actions, task views, and stats refresh.
- [ ] Run `pytest tests/test_server.py -q` and verify GREEN.
- [ ] Commit `feat: add local SEDB browser application`.

### Task 6: CLI, demo dataset, documentation, and release validation

**Files:**
- Create: `src/sedb/cli.py`
- Create: `examples/build_demo.py`
- Create: `README.md`
- Create: `docs/RELEASE_NOTES_v0.1.md`
- Create: `.gitignore`
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces commands: `sedb init`, `sedb demo`, `sedb serve`, `sedb stats`.

- [ ] Write CLI tests for init, demo, stats, and argument parsing.
- [ ] Run `pytest tests/test_cli.py -q` and verify RED.
- [ ] Implement CLI and demo builder that creates sample entities plus 10,000 logical fields with only sparse values.
- [ ] Document Windows/Linux launch commands, architecture, field semantics, API summary, local-first workflow, and that public licensing is intentionally undecided for this local checkpoint.
- [ ] Run `pytest -q` and verify the complete suite passes.
- [ ] Run `python -m sedb.cli demo --db /tmp/sedb-demo.sqlite --fields 10000`, then `python -m sedb.cli stats --db /tmp/sedb-demo.sqlite` and verify `fields >= 10000` while cells remain sparse.
- [ ] Compile all Python with `python -m compileall -q src examples`.
- [ ] Commit `release: prepare SEDB local v0.1 checkpoint`.

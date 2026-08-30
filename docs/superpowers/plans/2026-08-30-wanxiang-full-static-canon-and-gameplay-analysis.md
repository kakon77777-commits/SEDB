# Wanxiang Full Static Canon and Gameplay Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. The user explicitly disallows subagent-driven implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the accepted Wave 1 Wanxiang SEDB database into a hash-gated 29,939-row static canon with additive Hero enrichment, explicit reference edges, six gameplay-analysis reports and a compact multi-AI context index.

**Architecture:** A project-local OpenXML reader validates the frozen 36-workbook AllExcel snapshot and emits canonical row records. A full-catalog composer merges those records, Hero enrichment and explicit rule-backed edges with the accepted Wave 1 selection; the SEDB store adds scope-aware missing-cell enrichment without updating existing cells, while analysis and context exporters consume only verified database state.

**Tech Stack:** Python 3.11+ standard library (`zipfile`, `xml.etree.ElementTree`, `sqlite3`, `hashlib`, `json`), SEDB `current` v0.4.0b1, pytest, Windows PowerShell and SHA-256.

**Spec:** `docs/superpowers/specs/2026-08-30-wanxiang-full-static-canon-and-gameplay-analysis-design.md`

## Global Constraints

- Work directly on `D:\Ai\work together\SEDB` branch `main`; no worktree and no subagents.
- Modify only `projects/wanxiang-character-canon/**`, this plan/spec and the approved game-analysis/context output paths.
- Do not modify SEDB `current/`, existing projects, releases, installed game, Steam, Workshop, frozen workbooks, `.dat` files, PNGs or methodology papers.
- Canonical workbook source is exactly `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\baseline\game\wanxiang\wanxiang\ModDocs\AllExcel`.
- Source-manifest SHA-256 is `0B607E20ADE02510181CB5B3145AE3F0D68E6AABA16C50458A0E725EFC5C6F1F`; validate all 36 member length/hash records.
- Exact source contract is 36 tables, 29,939 data rows, 228 `Type=0` Hero rows, 41 `Type=1`, one Hero sentinel, 17,210 EventDialog rows and one null-ID Formula row.
- Register exactly 52 frozen `StreamingAssets/*.dat` runtime candidates by path, length and SHA without decoding them or adding row entities.
- Exact pre-edge full-catalog entity count is 31,678. Reference-edge count is deterministic source output and must be printed and replay-verified before apply.
- `ModTools/Data`, `ModTools/Excel` and Workshop snapshots remain noncanonical provenance layers.
- Default database is generated/ignored `projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`; never stage it or its backup/sidecars.
- Existing source-owned cells are immutable. Catalog migration may insert only new entities and absent source cells; any differing existing value/source blocks the invocation.
- Curated and proposal cells are outside importer equality and must remain byte-equivalent.
- Before the first real catalog apply, create and verify a recoverable ignored Wave 1 SQLite backup; never overwrite it.
- Every real apply reloads all sources and requires an identical fingerprint immediately before one-transaction apply.
- Preserve the unrelated untracked brief at 6,850 bytes and SHA-256 `30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`.
- No foreground game use, provider call, image work, MOD emission, push, PR, publication, deployment or release.
- Use `python -m pytest`, not a bare `pytest` command, on this host.

## Pre-implementation state

- Accepted Wave 1 code/evidence commit: `10339db4a80d229b2e2e10bade74486ccc797796`.
- Approved full-static-canon design commit: `6a4f0a84bcb00751e6967b2dd44759a09eac1adf`.
- Default Wave 1 database: 1,967 entities, 39,600 cells, 118 fields, 9 views, integrity `ok`.
- SEDB inherited baseline: 189 tests.
- Only unrelated dirty path: `docs/BRIEF_unbounded_axiom_corpus_sedb_2026-08-25.md`.

## File Structure

- `projects/wanxiang-character-canon/excel_reader.py` — safe deterministic OpenXML parser.
- `projects/wanxiang-character-canon/catalog_config.py` — table counts, source paths and versions.
- `projects/wanxiang-character-canon/catalog_identity.py` — stable row and edge IDs.
- `projects/wanxiang-character-canon/catalog_source.py` — row catalog and Hero enrichment.
- `projects/wanxiang-character-canon/catalog_schema.py` — catalog fields and ten views.
- `projects/wanxiang-character-canon/reference_rules.py` — reviewed direct-reference rules.
- `projects/wanxiang-character-canon/reference_graph.py` — operation normalization and edges.
- `projects/wanxiang-character-canon/backup.py` — recoverable SQLite backup.
- `projects/wanxiang-character-canon/gameplay/*.py` — six analyses and report export.
- `projects/wanxiang-character-canon/context_index.py` — human/machine indexes and links.
- `projects/wanxiang-character-canon/source.py` — scoped ownership and per-cell sources.
- `projects/wanxiang-character-canon/schema.py` — Wave 1 plus catalog schema.
- `projects/wanxiang-character-canon/store.py` — enrichment planning and atomic inserts.
- `projects/wanxiang-character-canon/cli.py` — catalog/query/analysis/context commands.
- `projects/wanxiang-character-canon/tests/catalog_fixtures.py` — XLSX/catalog fixtures.
- `projects/wanxiang-character-canon/tests/test_excel_reader.py` — OpenXML regressions.
- `projects/wanxiang-character-canon/tests/test_catalog_source.py` — catalog selection tests.
- `projects/wanxiang-character-canon/tests/test_catalog_schema.py` — schema/view tests.
- `projects/wanxiang-character-canon/tests/test_catalog_store.py` — migration/backup tests.
- `projects/wanxiang-character-canon/tests/test_reference_graph.py` — edge tests.
- `projects/wanxiang-character-canon/tests/test_catalog_cli.py` — CLI tests.
- `projects/wanxiang-character-canon/tests/test_gameplay_analysis.py` — report tests.
- `projects/wanxiang-character-canon/tests/test_context_index.py` — context/link tests.
- `projects/wanxiang-character-canon/tests/test_catalog_live_acceptance.py` — real acceptance.
- Generated/ignored: `projects/wanxiang-character-canon/local-backups/*.sqlite*`.
- Generated reports: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4/**`.
- Canonical context index: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`.

---

### Task 1: Safe OpenXML reader and AllExcel manifest contract

**Files:**
- Create: `projects/wanxiang-character-canon/excel_reader.py`
- Create: `projects/wanxiang-character-canon/catalog_config.py`
- Create: `projects/wanxiang-character-canon/tests/catalog_fixtures.py`
- Create: `projects/wanxiang-character-canon/tests/test_excel_reader.py`
- Modify: `projects/wanxiang-character-canon/.gitignore`

**Interfaces:**
- Produces `WorkbookReadError(reason_code, message)`.
- Produces immutable `WorkbookRow(row_number, values, canonical_json, sha256)`.
- Produces immutable `WorkbookSnapshot(path, sha256, headers, metadata_rows, rows)`.
- Produces `read_workbook(path: Path, sheet_name: str = "Sheet1") -> WorkbookSnapshot`.
- Produces `CatalogContract(source_root, manifest_path, manifest_sha256, table_counts, reader_version)` and `default_catalog_contract()`.
- Produces `write_xlsx_fixture(path, *, relationship_target, headers, metadata_rows, data_rows)`.

- [ ] **Step 1: Write failing relative/absolute OPC tests**

```python
def test_relative_and_package_absolute_targets_decode_identically(tmp_path):
    relative = write_xlsx_fixture(
        tmp_path / "relative.xlsx",
        relationship_target="worksheets/sheet1.xml",
        headers=("Id", "Name"),
        metadata_rows=(("INT", "STRING"), (-1, "nil"), ("编号", "名称")),
        data_rows=((1, "万轻舟"),),
    )
    absolute = write_xlsx_fixture(
        tmp_path / "absolute.xlsx",
        relationship_target="/xl/worksheets/sheet1.xml",
        headers=("Id", "Name"),
        metadata_rows=(("INT", "STRING"), (-1, "nil"), ("编号", "名称")),
        data_rows=((1, "万轻舟"),),
    )
    assert read_workbook(relative).rows == read_workbook(absolute).rows
    assert read_workbook(absolute).rows[0].row_number == 5
```

Also test path traversal, external target, missing relationship, duplicate
header, missing row 1 and wrong sheet name with exact reason codes.

- [ ] **Step 2: Run reader tests and verify RED**

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python -m pytest -q projects\wanxiang-character-canon\tests\test_excel_reader.py
```

Expected: import failure because `excel_reader.py` does not exist.

- [ ] **Step 3: Implement workbook dataclasses and OPC resolver**

```python
@dataclass(frozen=True)
class WorkbookRow:
    row_number: int
    values: dict[str, Any]
    canonical_json: str
    sha256: str


@dataclass(frozen=True)
class WorkbookSnapshot:
    path: Path
    sha256: str
    headers: tuple[str, ...]
    metadata_rows: tuple[dict[str, Any], ...]
    rows: tuple[WorkbookRow, ...]


def _normalize_relationship_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if "://" in normalized or normalized.startswith("//"):
        raise WorkbookReadError("external_target_rejected", target)
    parts = PurePosixPath(normalized.lstrip("/")).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise WorkbookReadError("relationship_path_escape", target)
    if parts and parts[0] == "xl":
        return PurePosixPath(*parts).as_posix()
    return (PurePosixPath("xl") / PurePosixPath(*parts)).as_posix()
```

Row 1 defines headers, rows 2–4 become `metadata_rows`, and only rows 5+
become data records. Canonical row JSON uses UTF-8, sorted keys and compact
separators; row SHA-256 is uppercase.

- [ ] **Step 4: Add cell-type/UTF-8 tests and exact decoding**

Cover shared strings, inline strings, booleans, signed integers, floats,
formula-cached strings, error strings and blank cells. Include `万轻舟` and
assert serialization under a UTF-8 subprocess.

```python
payload = row.canonical_json.encode("utf-8")
assert row.sha256 == hashlib.sha256(payload).hexdigest().upper()
```

- [ ] **Step 5: Implement the 36-table source contract**

`catalog_config.py` contains the ordered counts from the spec, total 29,939,
manifest SHA, source-layer constants, reader version `wanxiang-openxml/v1` and
exact source paths.

```python
@dataclass(frozen=True)
class CatalogContract:
    source_root: Path
    manifest_path: Path
    manifest_sha256: str
    table_counts: Mapping[str, int]
    runtime_candidate_root: Path
    runtime_candidate_count: int = 52
    reader_version: str = "wanxiang-openxml/v1"
```

`.gitignore` adds `local-backups/` and retains SQLite/cache rules.

- [ ] **Step 6: Add opt-in real reader regression**

Skip unless `WANXIANG_CANON_LIVE=1`. Read real EventResult/Condition and assert
1,627/2,924 rows, then scan all 36 workbooks and assert 29,939 rows with no
source-tree change.

- [ ] **Step 7: Verify and commit Task 1**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_excel_reader.py
python -m compileall -q projects\wanxiang-character-canon\excel_reader.py projects\wanxiang-character-canon\catalog_config.py
```

Verify the unrelated brief fingerprint, stage only Task 1 files and commit:

```text
feat: add safe Wanxiang AllExcel reader
```

---

### Task 2: Complete row catalog, stable IDs and Hero enrichment

**Files:**
- Create: `projects/wanxiang-character-canon/catalog_identity.py`
- Create: `projects/wanxiang-character-canon/catalog_source.py`
- Create: `projects/wanxiang-character-canon/tests/test_catalog_source.py`
- Modify: `projects/wanxiang-character-canon/source.py`
- Modify: `projects/wanxiang-character-canon/tests/catalog_fixtures.py`
- Modify: `projects/wanxiang-character-canon/tests/test_source.py`

**Interfaces:**
- Extends `SourceEntity` with `cell_sources: dict[str, str]` and `source_for(key)`.
- Extends `SnapshotSelection` with `scope_name`, `owned_keys` and `scope_entity_kinds`.
- Produces `table_row_entity_id(build_id, table, source_id, *, row_number, workbook_sha256) -> str`.
- Produces `CatalogRow(table, source_id, row_number, workbook_path, workbook_sha256, payload, payload_json, source_row_sha256)`.
- Produces `CatalogRows(table_counts, source_hashes, rows, source_fingerprint)`.
- Produces `load_catalog_rows(config, contract) -> CatalogRows`.
- Produces `compose_full_catalog(config, *, include_edges=False) -> SnapshotSelection`.

- [ ] **Step 1: Write failing stable row-ID tests**

```python
def test_row_ids_preserve_scalar_type_and_null_row_identity():
    numeric = table_row_entity_id(25006280, "Event", 1, row_number=5, workbook_sha256="A" * 64)
    text = table_row_entity_id(25006280, "Event", "1", row_number=5, workbook_sha256="A" * 64)
    null = table_row_entity_id(25006280, "Formula", None, row_number=792, workbook_sha256="B" * 64)
    assert numeric != text
    assert null.startswith("wx-build-25006280-row-formula-r792-")
    assert numeric == table_row_entity_id(25006280, "event", 1, row_number=99, workbook_sha256="C" * 64)
```

- [ ] **Step 2: Run identity/catalog tests and verify RED**

Expected: missing `catalog_identity.py` and `catalog_source.py`.

- [ ] **Step 3: Implement row identity and scoped cell sources**

```python
@dataclass(frozen=True)
class SourceEntity:
    entity_id: str
    kind: str
    label: str
    values: dict[str, Any]
    cell_source: str
    cell_sources: dict[str, str] = field(default_factory=dict)

    def source_for(self, key: str) -> str:
        return self.cell_sources.get(key, self.cell_source)


@dataclass(frozen=True)
class SnapshotSelection:
    build_id: int
    source_hashes: dict[str, str]
    entities: tuple[SourceEntity, ...]
    counts: dict[str, int]
    scope_name: str = "wave1"
    owned_keys: frozenset[str] = frozenset()
    scope_entity_kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CatalogRow:
    table: str
    source_id: Any
    row_number: int
    workbook_path: str
    workbook_sha256: str
    payload: dict[str, Any]
    payload_json: str
    source_row_sha256: str


@dataclass(frozen=True)
class CatalogRows:
    table_counts: dict[str, int]
    source_hashes: dict[str, str]
    rows: tuple[CatalogRow, ...]
    source_fingerprint: str
```

Wave 1 `load_snapshot()` sets explicit Wave 1 key/kind scope so it remains a
no-op after catalog cells exist.

- [ ] **Step 4: Write failing manifest/count/drift tests**

Build a tiny fixture contract with Hero, EventDialog and Formula workbooks.
Require reason codes for manifest hash mismatch, missing member, workbook hash,
wrong table count, duplicate non-null table ID and duplicate stable entity ID.

```python
catalog = load_catalog_rows(config, fixture.contract)
assert catalog.table_counts == {"EventDialog": 2, "Formula": 1, "Hero": 3}
assert sum(catalog.table_counts.values()) == 6
assert catalog.rows[0].source_row_sha256
```

- [ ] **Step 5: Implement manifest-gated row loading**

Map manifest member `wanxiang/ModDocs/AllExcel/<file>` to the frozen source root,
verify length/SHA and exact counts, and reject nonconfigured workbooks. Each
generic row includes source layer/authority/table/ID/row/workbook path/hash/row
hash/full payload plus compact name/title/description/flag fields.

- [ ] **Step 6: Write failing Hero merge tests**

```python
selection = compose_full_catalog(config, include_edges=False)
form = next(entity for entity in selection.entities if entity.entity_id.endswith("-hero-1001"))
assert form.values["source_row_payload"]["Desc"] == "完整人物背景"
assert form.values["skill_ids"] == [10, 11]
assert sum(entity.kind == "wanxiang_treasure_snapshot" for entity in selection.entities) == 1
assert sum(entity.kind == "wanxiang_hero_sentinel_snapshot" for entity in selection.entities) == 1
```

Mutate IdName/name/Birth/Image/ParentId and require
`hero_registry_reconciliation_conflict`.

- [ ] **Step 7: Implement Hero projection and deterministic merge**

`merge_source_entities(base, extension)` requires equal ID/kind/label, permits
identical overlaps, unions disjoint values/sources and rejects contradictions.
Materialize descriptions, stats, skills, properties, Ji pairs,
player/atlas/point/route/acquisition/skin/story fields and payload.

- [ ] **Step 8: Add Build evidence and exact pre-edge counts**

Enrich the Build with catalog version, manifest/workbook hashes, table counts,
29,939 total rows, fingerprint, reader version and the ordered 52-entry runtime
candidate path/length/SHA projection. Wave 1 `source_sha256` remains
byte-equivalent. A candidate is evidence only; no `.dat` decode claim is added.

- [ ] **Step 9: Verify unit and read-only real selection**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_identity.py projects\wanxiang-character-canon\tests\test_source.py projects\wanxiang-character-canon\tests\test_catalog_source.py
$env:WANXIANG_CANON_LIVE = '1'
python -m pytest -q projects\wanxiang-character-canon\tests\test_catalog_source.py -k real
```

Real selection reports 29,669 generic rows, 41 treasures, one sentinel, 228
enriched forms and 31,678 total pre-edge entities. Source signature is unchanged.

- [ ] **Step 10: Commit Task 2**

```text
feat: compose Wanxiang full row catalog
```

---

### Task 3: Catalog fields, ownership layers and ten Task Views

**Files:**
- Create: `projects/wanxiang-character-canon/catalog_schema.py`
- Create: `projects/wanxiang-character-canon/tests/test_catalog_schema.py`
- Modify: `projects/wanxiang-character-canon/schema.py`

**Interfaces:**
- Produces `CATALOG_SOURCE_FIELD_SPECS`, `CATALOG_SOURCE_OWNED_KEYS` and `CATALOG_VIEW_SPECS`.
- Produces `WAVE1_SOURCE_OWNED_KEYS` before unioning `SOURCE_OWNED_KEYS`.
- Keeps the first nine `VIEW_SPECS` exact and appends ten catalog views.

- [ ] **Step 1: Write failing field-layer tests**

```python
def test_catalog_source_keys_are_owned_and_do_not_leak_into_curated_layers():
    required = {
        "catalog_source_fingerprint", "source_layer", "source_authority",
        "source_table", "source_record_id", "source_workbook_path",
        "source_workbook_sha256", "source_row_sha256", "source_row_payload",
        "edge_source_entity_id", "edge_target_table", "edge_resolution_status",
    }
    assert required <= CATALOG_SOURCE_OWNED_KEYS
    assert CATALOG_SOURCE_OWNED_KEYS.isdisjoint(CURATED_KEYS | PROPOSAL_KEYS)
    assert WAVE1_SOURCE_OWNED_KEYS < SOURCE_OWNED_KEYS
```

- [ ] **Step 2: Write failing exact-view tests**

The first nine names/orders equal Wave 1, followed by:

```python
[
    "AllExcel Table Catalog", "Full Hero Context", "World and Map Context",
    "Relationship Routes", "Event Network", "Dialogue Index",
    "Combat and Progression", "Reference Resolution",
    "Static Gameplay Questions", "Catalog Provenance",
]
```

- [ ] **Step 3: Run schema tests and verify RED**

Expected: missing `catalog_schema.py`.

- [ ] **Step 4: Implement explicit catalog field groups**

Source/build fields:

```text
catalog_schema_version, catalog_manifest_path, catalog_manifest_sha256,
catalog_workbook_hashes, catalog_table_counts, catalog_total_rows,
catalog_source_fingerprint, catalog_reader_version, source_layer,
runtime_candidate_files,
source_authority, source_table, source_record_id, source_workbook_path,
source_workbook_sha256, source_row_sha256, source_row_payload, description_tw,
flag, level, hp, power, is_player, property_ids, ji_values, is_atlas,
atlas_index, acquisition_description, acquisition_description_tw, point_value,
condition_operations, event_result_operations, selection_options, guide_steps
```

Edge fields:

```text
edge_source_entity_id, edge_source_table, edge_source_field, edge_slot,
edge_raw_value, edge_target_table, edge_target_source_id,
edge_target_entity_id, edge_resolution_status, edge_rule_id,
edge_rule_version, edge_evidence_level, edge_claim_boundary
```

Analysis fields:

```text
analysis_name, metric_key, metric_value, claim_class, evidence_basis,
falsifying_test
```

Use JSON for arbitrary IDs/payload/operations/metrics, integer for row/slot and
counts, boolean for flags, and text for labels/status/hash/path.

- [ ] **Step 5: Implement ten catalog views**

Use compact/materialized fields and exclude `source_row_payload` from broad
views. `Dialogue Index` starts with source ID, name/title, next-link summaries,
row and payload SHA.

- [ ] **Step 6: Verify and commit Task 3**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_schema.py projects\wanxiang-character-canon\tests\test_catalog_schema.py
```

Commit:

```text
feat: define Wanxiang catalog schema and views
```

---

### Task 4: Scope-aware enrichment store and recoverable backup

**Files:**
- Create: `projects/wanxiang-character-canon/backup.py`
- Create: `projects/wanxiang-character-canon/tests/test_catalog_store.py`
- Modify: `projects/wanxiang-character-canon/store.py`
- Modify: `projects/wanxiang-character-canon/tests/test_store.py`

**Interfaces:**
- Produces `BackupError(reason_code, message)`.
- Produces `PlannedCell(key, value, source)`.
- Produces `EntityEnrichment(entity_id, cells)`.
- Extends `DiffPlan` with `enrich` while preserving existing fields.
- Produces `BackupResult(path, length, sha256, integrity, entity_count, cell_count)`.
- Produces `create_verified_backup(config, destination) -> BackupResult`.

- [ ] **Step 1: Write failing scoped-plan tests**

```python
def test_wave1_scope_ignores_later_catalog_cells(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(full))
    rerun = store.plan(wave1)
    assert rerun.conflicts == ()
    assert len(rerun.unchanged) == len(wave1.entities)


def test_missing_catalog_cell_is_enrichment_not_conflict(tmp_path):
    store, wave1, full = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    plan = store.plan(full)
    assert plan.enrich
    assert not plan.blocked
```

- [ ] **Step 2: Run catalog-store tests and verify RED**

Expected: `DiffPlan` has no `enrich` and state has no cell sources.

- [ ] **Step 3: Implement source-aware state and plan dataclasses**

```python
@dataclass(frozen=True)
class PlannedCell:
    key: str
    value: Any
    source: str


@dataclass(frozen=True)
class EntityEnrichment:
    entity_id: str
    cells: tuple[PlannedCell, ...]


@dataclass(frozen=True)
class DiffPlan:
    build_id: int
    new: tuple[SourceEntity, ...]
    enrich: tuple[EntityEnrichment, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[EntityConflict, ...]
    missing_from_source: tuple[str, ...]
    source_fingerprint: str
```

`_owned_state` returns values and sources. `plan` iterates only
`selection.owned_keys`, compares source and value, classifies absent cells as
enrichment, and limits missing checks to `selection.scope_entity_kinds`.

- [ ] **Step 4: Write conflict/preservation tests**

Cover changed existing value, changed source, stale enrichment race, missing
catalog entity, curated/proposal preservation and Wave 1 no-op after expansion.

- [ ] **Step 5: Implement atomic new plus enrichment apply**

Inside `BEGIN IMMEDIATE`, verify new IDs and enrichment cells remain absent,
insert only those rows, read back exact values/sources, verify Wave 1 retention
and curated/proposal snapshot equality, then run integrity. No SQL UPDATE,
DELETE or `ON CONFLICT DO UPDATE` is permitted.

- [ ] **Step 6: Write failing backup tests**

```python
def test_verified_backup_is_recoverable_and_never_overwritten(tmp_path):
    store, wave1, _ = prepared_catalog_store(tmp_path)
    store.ensure_schema()
    store.apply(store.plan(wave1))
    target = tmp_path / "local-backups" / "wave1.sqlite"
    result = create_verified_backup(store.config, target)
    assert result.integrity == "ok"
    assert result.entity_count == len(wave1.entities)
    with pytest.raises(BackupError, match="already exists"):
        create_verified_backup(store.config, target)
```

- [ ] **Step 7: Implement SQLite backup and verification**

Use `sqlite3.Connection.backup()` after confirming no WAL/SHM sidecars. Hash
the backup, reopen it for count/integrity verification and never overwrite.

- [ ] **Step 8: Inject readback failure and prove total rollback**

Apply a fixture with new entities and enrichment cells, inject failure after
inserts, and assert neither category persists.

- [ ] **Step 9: Verify full project suite and commit**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_store.py projects\wanxiang-character-canon\tests\test_catalog_store.py
python -m pytest -q projects\wanxiang-character-canon\tests
```

Commit:

```text
feat: add additive Wanxiang catalog migration
```

---

### Task 5: Explicit reference rules and deterministic graph

**Files:**
- Create: `projects/wanxiang-character-canon/reference_rules.py`
- Create: `projects/wanxiang-character-canon/reference_graph.py`
- Create: `projects/wanxiang-character-canon/tests/test_reference_graph.py`
- Modify: `projects/wanxiang-character-canon/catalog_identity.py`
- Modify: `projects/wanxiang-character-canon/catalog_source.py`

**Interfaces:**
- Produces `ReferenceRule(rule_id, source_table, field_pattern, target_table, split_ampersand, evidence)`.
- Produces `ReferenceEdge(source_entity_id, source_table, source_field, slot, raw_value, target_table, target_source_id, target_entity_id, resolution_status, rule_id)`.
- Produces `normalize_repeated_operations(table, payload) -> dict[str, Any]`.
- Produces `build_reference_edges(build_id, catalog_rows) -> tuple[SourceEntity, ...]`.
- Rule-set version is `wanxiang-reference-rules/v1`.

- [ ] **Step 1: Write failing Event LogicType tests**

```python
def test_event_logic_type_uses_documented_enum_only():
    expected = {
        0: "EventDialog", 1: "EventSelection", 2: "EventNormal",
        3: "Battle", 4: "EventPuzzle", 5: "EventDice",
    }
    assert EVENT_LOGIC_TARGETS == expected
    assert resolve_event_logic_target(99) is None
```

Preserve metadata evidence:
`事件逻辑类型：0对话 1选项 2一般事件 3战斗 4答题 5骰子`.

- [ ] **Step 2: Define exact direct rules and fixture tests**

```text
Hero: Birth, ParentId, SkillId0-3, Property0-5, ExtraHeroId, StoryId
Map: ParentId
Birth: ResidentMap
Relation: Birth, PropertyId, GuidEvent0-9
Event: Map, ConditionId, ResultId, LogicId via LogicType
EventDialog: NextDialogId, NextEventId
EventSelection: Condition0-19, EventId0-19
EventNormal: NextEventId
EventPuzzle: PuzzleGroupId, SuccessEventId, FailedEventId
EventDice: DiceId
Battle: SuccessEventId, FailedEventId, FixedHero0-4
Skill: conditionId, FormulaId, EffectId0-1, ExtraFormulaId, ExtraEffectId0-1
EventResult: ConditionId0-9 only
```

Story targets remain `missing_target` because no Story table exists. Condition
type/value and EventResult type/value fields do not create target edges in v1.

- [ ] **Step 3: Run reference tests and verify RED**

Expected: missing rules/graph modules.

- [ ] **Step 4: Implement sentinel, multi-ID and operation normalization**

Suppress null/blank/case-insensitive `nil`/numeric `-1` from edges while
preserving raw payload. Split `&` values in order, reject duplicate components,
and normalize Condition 10 slots, EventResult 10 slots, EventSelection 20 slots
and Relation 10 guide slots into JSON arrays.

- [ ] **Step 5: Implement resolution states and stable edge IDs**

`resolved` requires exact table/source-ID match. Valid absent targets emit
`missing_target`. Unknown Event LogicType emits `unknown_semantics` with no
target entity. Name/similarity matching is forbidden.

```python
def reference_edge_entity_id(edge: ReferenceEdge) -> str:
    projection = [edge.source_entity_id, edge.source_field, edge.slot,
                  edge.target_table, edge.target_source_id]
    digest = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()[:16]
    return f"wx-edge-{digest}"
```

- [ ] **Step 6: Add graph to selection and fingerprint**

`compose_full_catalog(include_edges=True)` includes edge entities, edge count and
rule breakdown. Independent loads produce identical IDs/order/fingerprint.

- [ ] **Step 7: Run unit and read-only real graph plan**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_reference_graph.py projects\wanxiang-character-canon\tests\test_catalog_source.py
$env:WANXIANG_CANON_LIVE='1'
python -m pytest -q projects\wanxiang-character-canon\tests\test_reference_graph.py -k real
```

Print real deterministic edge/status/rule counts. Do not write the default DB.

- [ ] **Step 8: Commit Task 5**

```text
feat: build Wanxiang static reference graph
```

---

### Task 6: Catalog CLI and fixture end-to-end acceptance

**Files:**
- Create: `projects/wanxiang-character-canon/tests/test_catalog_cli.py`
- Modify: `projects/wanxiang-character-canon/cli.py`
- Modify: `projects/wanxiang-character-canon/store.py`
- Modify: `projects/wanxiang-character-canon/README.md`

**Interfaces:**
- Adds `catalog-plan`, `catalog-bootstrap`, `table`, `edges`, `dialog`, `route`.
- Extends `stats` with catalog/table/edge counts.
- Keeps JSON stdout and exit codes 0/2/3/4.

- [ ] **Step 1: Write failing subprocess CLI tests**

```python
plan = run_cli("catalog-plan", "--build", "25006280")
assert plan.returncode == 0
assert plan.json["pre_edge_entities"] == fixture.pre_edge_count
assert plan.json["edge_count"] == fixture.edge_count
assert sqlite_entity_count(database) == 0

first = run_cli("catalog-bootstrap", "--build", "25006280")
second = run_cli("catalog-bootstrap", "--build", "25006280")
assert first.json["status"] == "created"
assert second.json["status"] == "no_op"
```

Also cover source error exit 2, conflict exit 3, backup/readback error 4 and no
database mutation after a blocked plan.

- [ ] **Step 2: Write failing query tests**

Require compact `table EventDialog`, complete payload from `dialog <id>`,
incoming/outgoing edge lists and Relation guide-step/edge output. Broad lists
omit `source_row_payload`.

- [ ] **Step 3: Run CLI tests and verify RED**

Expected: parser rejects unknown commands.

- [ ] **Step 4: Implement catalog commands and bounded JSON**

`catalog-plan` is read-only. `catalog-bootstrap` ensures schema, reloads source,
compares fingerprints, creates backup only for an accepted Wave 1 default DB
without catalog records, then applies atomically.

List commands accept bounded limits and ID samples include omitted counts.

- [ ] **Step 5: Preserve Wave 1 commands after expansion**

After catalog bootstrap, old `plan`/`bootstrap` remain unblocked no-ops;
`search 万轻舟` still links identity/forms/assets without duplicate entities.

- [ ] **Step 6: Verify and commit Task 6**

```powershell
python -m pytest -q projects\wanxiang-character-canon\tests\test_cli.py projects\wanxiang-character-canon\tests\test_catalog_cli.py
python -m pytest -q projects\wanxiang-character-canon\tests
```

Commit:

```text
feat: add Wanxiang full catalog CLI
```

---

### Task 7: Real backup, full-catalog bootstrap and acceptance

**Files:**
- Create: `projects/wanxiang-character-canon/tests/test_catalog_live_acceptance.py`
- Create: `projects/wanxiang-character-canon/evidence/wave1-backup-manifest.json`
- Create: `projects/wanxiang-character-canon/evidence/full-catalog-acceptance.json`
- Modify: `projects/wanxiang-character-canon/README.md`
- Modify: `projects/wanxiang-character-canon/VERIFY.md`
- Generate/ignore: `projects/wanxiang-character-canon/local-backups/wave1-25006280.sqlite`
- Generate/ignore: `projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`

**Interfaces:**
- Produces accepted local full static canon plus backup/catalog evidence.

- [ ] **Step 1: Write gated real acceptance test**

Skip unless `WANXIANG_CANON_LIVE=1`. Seed a temporary DB with Wave 1:

```python
wave1 = load_snapshot(config)
store.apply(store.plan(wave1))
full = compose_full_catalog(config, include_edges=True)
result = store.apply(store.plan(full))
edge_count = full.counts["wanxiang_reference_edge_snapshot"]
assert result.created_entities + 1967 == 31678 + edge_count
rerun = store.plan(compose_full_catalog(config, include_edges=True))
assert rerun.new == ()
assert rerun.enrich == ()
assert store.integrity_check() == "ok"
```

Assert exact tables/rows/dialogs/Hero distribution, retained forms,
52 runtime-candidate records, deterministic edges and unchanged source
signatures.

- [ ] **Step 2: Run project tests without live flag**

All unit/integration tests pass and live tests skip explicitly.

- [ ] **Step 3: Capture pre-apply preservation evidence**

Verify default DB is accepted Wave 1, no sidecars, brief/source/install/
Workshop signatures, `current/` diff zero and Git scope. Create ignored backup
and verify hash/counts/integrity.

- [ ] **Step 4: Run real catalog plan twice**

```powershell
$env:PYTHONPATH='current\src;projects\wanxiang-character-canon'
python projects\wanxiang-character-canon\cli.py catalog-plan --build 25006280
python projects\wanxiang-character-canon\cli.py catalog-plan --build 25006280
```

Require identical fingerprints, 31,678 pre-edge base, deterministic edges,
zero conflicts/missing and zero DB entity changes.

- [ ] **Step 5: Run first real catalog bootstrap**

Require one transaction, exact new/enrichment/cell/edge counts, readback and
integrity `ok`. Confirm backup hash unchanged.

- [ ] **Step 6: Rerun and verify no-op**

Require `new=0`, `enrich=0`, `conflicts=0`, `missing=0`, all full entities
unchanged and identical fingerprint.

- [ ] **Step 7: Run live and inherited tests**

```powershell
$env:WANXIANG_CANON_LIVE='1'
python -m pytest -q projects\wanxiang-character-canon\tests\test_catalog_live_acceptance.py
$env:PYTHONPATH='current\src'
python -m pytest -q current\tests
```

- [ ] **Step 8: Write measured evidence and commit**

Record exact edge/entity/cell/field/view counts, fingerprints, first/no-op
results, backup/DB hashes, integrity, source preservation, tests and
NotMeasured. Database and backup remain ignored.

Commit:

```text
test: accept Wanxiang full static canon
```

---

### Task 8: Six static gameplay analyses and reports

**Files:**
- Create: `projects/wanxiang-character-canon/gameplay/__init__.py`
- Create: `projects/wanxiang-character-canon/gameplay/common.py`
- Create: `projects/wanxiang-character-canon/gameplay/character.py`
- Create: `projects/wanxiang-character-canon/gameplay/events.py`
- Create: `projects/wanxiang-character-canon/gameplay/relationships.py`
- Create: `projects/wanxiang-character-canon/gameplay/combat.py`
- Create: `projects/wanxiang-character-canon/gameplay/export.py`
- Create: `projects/wanxiang-character-canon/tests/test_gameplay_analysis.py`
- Modify: `projects/wanxiang-character-canon/cli.py`
- Generate: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4/**`

**Interfaces:**
- Produces `Claim(claim_class, text, evidence, falsifying_test="")`.
- Produces six `analyze_*` functions returning JSON-safe report models.
- Produces `export_gameplay_reports(config, output_root) -> ReportManifest`.
- Adds `gameplay-report NAME|all`.

- [ ] **Step 1: Write verified-input and claim-boundary tests**

Require DB integrity, accepted catalog fingerprint and exact source counts.
Reject `runtime-unreachable`, `proves fun` and equivalent language in OBSERVED.

- [ ] **Step 2: Implement common loader and report schema**

```python
@dataclass(frozen=True)
class Claim:
    claim_class: Literal["OBSERVED", "INFERRED", "UNKNOWN", "FALSIFYING_TEST"]
    text: str
    evidence: tuple[str, ...]
    falsifying_test: str = ""


@dataclass(frozen=True)
class ReportManifest:
    output_root: Path
    report_paths: tuple[Path, ...]
    sha256_by_path: dict[str, str]
    catalog_fingerprint: str
```

Reports include BuildID, DB/catalog fingerprints, source tables, rule version,
timestamp, metrics, claims and NotMeasured.

- [ ] **Step 3: Implement character coverage with failing fixtures first**

Test description/skill/property/relation/event/dialog/art coverage per form and
identity, missing-field counts and no duplicate forms.

- [ ] **Step 4: Implement event network with failing graph fixtures first**

Use deterministic standard-library Tarjan SCC. Report node/typed-edge/degree,
static-root-candidate, terminal, SCC, cycle, missing-target and isolated counts.
Never name a static candidate runtime-unreachable.

- [ ] **Step 5: Implement choice/consequence and pacing analyses**

Choice metrics include options, distinct Event IDs, repeated destinations and
one-hop convergence by identical target Event `ResultId`. Pacing includes
CostTime, Times, OnceInTurn, priority/weight, explicit time conditions and map
event density.

- [ ] **Step 6: Implement relationship analysis**

Measure guide steps, Property/Event resolution, repeated fallback text, shared
targets and missing references. Prose is evidence, not a structured condition.

- [ ] **Step 7: Implement combat/progression analysis**

Measure skill cost/launch/success, Formula/Effect links, Battle party and
success/failure links, plus Difficulty HP/Damage/DebuffResist values. Label
representational diversity as static.

- [ ] **Step 8: Implement deterministic JSON/Markdown export**

Write exactly six JSON, six Markdown and one manifest under the approved output
root via temp file plus atomic replace. Never write under baseline/inputs/
art-engineering.

- [ ] **Step 9: Add CLI and reconciliation tests**

`gameplay-report all` returns report hashes/counts. Tests recompute DB metrics
and require exact JSON reconciliation. Markdown includes all claim classes and
source paths.

- [ ] **Step 10: Generate real reports and commit**

Fingerprint immutable sources before/after, validate JSON and report hashes,
and record the output manifest in SEDB evidence.

Commit code and committed evidence only:

```text
feat: analyze Wanxiang static gameplay systems
```

---

### Task 9: AI context index, final verification and local handoff

**Files:**
- Create: `projects/wanxiang-character-canon/context_index.py`
- Create: `projects/wanxiang-character-canon/tests/test_context_index.py`
- Create: `projects/wanxiang-character-canon/AI_CONTEXT_INDEX.md`
- Create: `projects/wanxiang-character-canon/evidence/full-static-verification.json`
- Modify: `projects/wanxiang-character-canon/VERIFY.md`
- Modify: `projects/wanxiang-character-canon/README.md`
- Modify: `projects/wanxiang-character-canon/cli.py`
- Generate: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`
- Generate: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4\context-index.json`

**Interfaces:**
- Produces `build_context_index(config, evidence, report_manifest) -> ContextIndex`.
- Produces `validate_context_links(index) -> tuple[LinkCheck, ...]`.
- Adds `context-index`.
- Produces `WANXIANG_FULL_STATIC_CANON_PASS` only after all gates pass.

```python
@dataclass(frozen=True)
class ContextIndex:
    payload: dict[str, Any]
    human_markdown: str


@dataclass(frozen=True)
class LinkCheck:
    path: str
    exists: bool
    reason: str
```

- [ ] **Step 1: Write failing context schema/reading-order tests**

Require BuildID, commit/tree basis, source/catalog/DB fingerprints,
table/entity/edge/view counts, DB/report/spec paths, query recipes, unresolved
counts, statuses, NotMeasured and next-work routing.

Human index begins with a six-item reading order and explains authority ranking
plus refresh instructions within its first 120 nonblank lines.

- [ ] **Step 2: Write failing single-canonical-index/link tests**

The SEDB-side `AI_CONTEXT_INDEX.md` contains only purpose, canonical path,
machine-index path, refresh command and evidence boundary. It must not duplicate
changing counts/fingerprints/report summaries. All local links must exist.

- [ ] **Step 3: Implement context builder, validator and CLI**

Generate machine JSON with sorted keys and human Markdown with stable sections.
`context-index` is read-only and returns reason-coded exit 4 for stale links.

- [ ] **Step 4: Generate real canonical index and pointer**

Use accepted DB/report manifest. Record a verification-basis commit/tree rather
than claiming a self-referential final documentation commit.

- [ ] **Step 5: Run fresh complete verification**

```powershell
$env:PYTHONPATH='current\src;projects\wanxiang-character-canon'
$env:WANXIANG_CANON_LIVE='1'
python -m pytest -q projects\wanxiang-character-canon\tests
$env:PYTHONPATH='current\src'
python -m pytest -q current\tests
python -m compileall -q current\src projects\wanxiang-character-canon
```

- [ ] **Step 6: Verify preservation, scope and replay**

Require full plan/bootstrap no-op, DB/backup integrity, input hashes,
installed-game/Workshop metadata signatures, report/context hashes, `current/`
diff zero, ignored DB/backup and exact brief fingerprint.

- [ ] **Step 7: Write final verification evidence**

Record exact measured test/count/hash/timing results and NotMeasured. Do not
reuse stale Wave 1 counts as current full-catalog counts.

- [ ] **Step 8: Commit final context and verification**

Stage only SEDB project docs/evidence/code. Approved research outputs remain in
their research paths and are hash-listed.

```text
docs: verify Wanxiang full static canon
```

- [ ] **Step 9: Keep integration local**

Do not push, publish, deploy or release. Report local commits, DB, Wave 1
backup, canonical context index, six reports, preservation and runtime/MOD work.

---

## Plan Self-Review Checklist

- Spec coverage: parser, catalog, Hero enrichment, provenance, migration,
  graph, views, CLI, acceptance, six analyses, context index and preservation
  each map to a task.
- Scope: Tasks 1–7 produce a useful full database before reports/context; no
  task requires runtime foreground use.
- Type consistency: `SourceEntity`, `SnapshotSelection`, `CatalogRows`,
  `PlannedCell`, `EntityEnrichment`, `DiffPlan`, `ReferenceEdge`, `Claim` and
  `ContextIndex` each have one declared producer and named consumers.
- Exact counts: 36 / 29,939 / 31,678 / 228 / 41 / 1 / 17,210 are hard gates;
  edge count is deterministic output verified twice before apply.
- No guessed enums: only documented Event LogicType 0–5 maps logic targets;
  Condition/EventResult operation targets remain raw/unknown.
- No placeholders: steps name files, interfaces, tests, commands, failures and
  commit boundaries.
- User constraints: inline only, direct main, no subagents, no foreground,
  no source mutation and no publication.

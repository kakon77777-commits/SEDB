# Wanxiang Character Canon SEDB Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. The user explicitly disallows subagent-driven development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent SEDB Wave 1 consumer that validates the Wanxiang BuildID `25006280` research artifacts and atomically imports 1,967 build, identity, form, asset, candidate, gap and methodology entities into a local idempotent SQLite canon database.

**Architecture:** A strict source adapter reads the Wanxiang research root one-way and produces generic immutable `SourceEntity` records. A SEDB-backed store owns schema/view preflight, deterministic plan/conflict semantics, one-transaction create-only apply, readback and integrity checks; human-curated and proposal fields remain sparse and outside importer equality.

**Tech Stack:** Python 3.11+, SQLite, SEDB `current` v0.4.0b1 (`Database`, `FieldService`, `ViewService` plus direct transactional SQL), pytest, Windows PowerShell, SHA-256.

**Spec:** `docs/superpowers/specs/2026-08-30-wanxiang-character-canon-sedb-design.md`

## Global Constraints

- Work directly on SEDB `main` under `projects/wanxiang-character-canon`; no worktree and no subagents.
- Modify only the new project directory plus this plan/spec. Do not modify `current/`, existing projects or releases.
- Preserve the unrelated untracked `docs/BRIEF_unbounded_axiom_corpus_sedb_2026-08-25.md` at 6,850 bytes and SHA-256 `30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`.
- Read only from `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research`; never modify source artifacts or PNGs.
- Default source BuildID is `25006280`; same-Build source drift blocks the whole invocation.
- Expected Wave 1 entities: 1 build + 165 identities + 228 forms + 1,391 exact assets + 172 visual candidates + 8 gaps + 2 methodology references = 1,967.
- Exact source contract: 228 Hero forms, 165 names, 1,391 exact `roles/*` paths, 1,513 output PNG manifest records, 172 ambiguous PNG records, 8 known Image gaps.
- Local SQLite, WAL/SHM sidecars, caches and test databases are Git-ignored.
- Importer-owned source/derived cells are immutable for a Build; curated and proposal fields are ignored during bootstrap equality.
- `plan` is read-only. `bootstrap` recomputes then applies only an unblocked plan in one transaction.
- No game runtime, Steam/Workshop mutation, image generation/editing, AI provider call, push, publication, deployment or release.

## File Structure

- `projects/wanxiang-character-canon/.gitignore` — local database/cache exclusions.
- `projects/wanxiang-character-canon/README.md` — authority, setup, commands and counts.
- `projects/wanxiang-character-canon/config.py` — immutable project/build/source/schema constants.
- `projects/wanxiang-character-canon/identity.py` — stable deterministic IDs and name normalization.
- `projects/wanxiang-character-canon/source.py` — source validation and `SnapshotSelection` creation.
- `projects/wanxiang-character-canon/schema.py` — field registry and Task View contract.
- `projects/wanxiang-character-canon/store.py` — schema preflight, diff plan, atomic apply, readback and stats.
- `projects/wanxiang-character-canon/cli.py` — init/plan/bootstrap/stats/search/show commands.
- `projects/wanxiang-character-canon/tests/conftest.py` — SEDB/current and project import paths.
- `projects/wanxiang-character-canon/tests/fixtures.py` — faithful small source fixture builder.
- `projects/wanxiang-character-canon/tests/test_identity.py` — stable IDs and normalization.
- `projects/wanxiang-character-canon/tests/test_source.py` — schema/hash/count/source selection.
- `projects/wanxiang-character-canon/tests/test_schema.py` — fields and views.
- `projects/wanxiang-character-canon/tests/test_store.py` — idempotence, conflict, rollback and curated preservation.
- `projects/wanxiang-character-canon/tests/test_cli.py` — CLI outcomes and exit codes.
- `projects/wanxiang-character-canon/tests/test_live_acceptance.py` — real BuildID `25006280` acceptance.
- Generated/ignored: `projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`.

---

### Task 1: Project boundary, configuration and stable identity primitives

**Files:**
- Create: `projects/wanxiang-character-canon/.gitignore`
- Create: `projects/wanxiang-character-canon/README.md`
- Create: `projects/wanxiang-character-canon/config.py`
- Create: `projects/wanxiang-character-canon/identity.py`
- Create: `projects/wanxiang-character-canon/tests/conftest.py`
- Create: `projects/wanxiang-character-canon/tests/test_identity.py`

**Interfaces:**
- Produces `ProjectConfig`, source/build constants and stable ID functions:
  - `normalize_name_key(value: str) -> str`
  - `character_identity_id(name: str) -> str`
  - `build_entity_id(build_id: int) -> str`
  - `form_entity_id(build_id: int, hero_id: int) -> str`
  - `asset_entity_id(build_id: int, resource_path: str) -> str`
  - `candidate_entity_id(build_id: int, output_path: str) -> str`
  - `gap_entity_id(build_id: int, role_class: str, hero_id: int) -> str`
  - `methodology_entity_id(slug: str, version: str) -> str`.

- [ ] **Step 1: Write failing identity tests**

```python
def test_name_normalization_is_nfkc_and_whitespace_only():
    assert normalize_name_key("  萬\u3000輕舟  ") == "萬 輕舟"
    assert normalize_name_key("万轻舟") == "万轻舟"
    assert normalize_name_key("萬輕舟") != normalize_name_key("万轻舟")


def test_ids_are_stable_and_namespaced():
    assert build_entity_id(25006280) == "wx-build-25006280"
    assert form_entity_id(25006280, 1001) == "wx-build-25006280-hero-1001"
    assert character_identity_id("万轻舟").startswith("wx-char-")
    assert character_identity_id("万轻舟") == character_identity_id(" 万轻舟 ")
    assert asset_entity_id(25006280, "Roles\\Image\\1001") == asset_entity_id(
        25006280, "roles/image/1001"
    )
```

Mutation guarded: accidental Simplified/Traditional conversion, unstable path separators, Build-free form IDs or nondeterministic hashes.

- [ ] **Step 2: Run the identity test and verify RED**

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
pytest -q projects\wanxiang-character-canon\tests\test_identity.py
```

Expected: import failure because `identity.py` does not exist.

- [ ] **Step 3: Implement exact identity functions**

```python
def normalize_name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return " ".join(normalized.split())


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def character_identity_id(name: str) -> str:
    return f"wx-char-{_digest(normalize_name_key(name))}"


def asset_entity_id(build_id: int, resource_path: str) -> str:
    normalized = resource_path.replace("\\", "/").strip("/").lower()
    return f"wx-build-{build_id}-asset-{_digest(normalized)}"
```

Use the exact string formats listed in Interfaces for the remaining functions.

- [ ] **Step 4: Implement configuration and boundary README**

`ProjectConfig` defaults:

```python
SOURCE_ROOT = Path(r"D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research")
BUILD_ID = 25006280
NAMESPACE = "wanxiang_character_canon"
DATABASE_NAME = "wanxiang-character-canon.sqlite"
ENTITY_COUNTS = {
    "wanxiang_build_snapshot": 1,
    "wanxiang_character_identity": 165,
    "wanxiang_character_form_snapshot": 228,
    "wanxiang_visual_asset_snapshot": 1391,
    "wanxiang_visual_candidate_snapshot": 172,
    "wanxiang_source_gap_snapshot": 8,
    "wanxiang_methodology_reference": 2,
}
```

`.gitignore` must include `*.sqlite`, `*.sqlite3`, `*.sqlite-wal`, `*.sqlite-shm`, `__pycache__/` and `.pytest_cache/`.

- [ ] **Step 5: Run tests and verify GREEN**

Expected: identity tests pass; `git check-ignore` proves the default database and sidecars are ignored.

- [ ] **Step 6: Commit Task 1 only**

Before staging, require the unrelated brief hash to remain exact. Stage only the six Task 1 files and commit:

```text
feat: scaffold Wanxiang character canon project
```

---

### Task 2: Strict one-way source selection

**Files:**
- Create: `projects/wanxiang-character-canon/source.py`
- Create: `projects/wanxiang-character-canon/tests/fixtures.py`
- Create: `projects/wanxiang-character-canon/tests/test_source.py`

**Interfaces:**
- Produces immutable dataclasses:

```python
@dataclass(frozen=True)
class SourceEntity:
    entity_id: str
    kind: str
    label: str
    values: dict[str, Any]
    cell_source: str


@dataclass(frozen=True)
class SnapshotSelection:
    build_id: int
    source_hashes: dict[str, str]
    entities: tuple[SourceEntity, ...]
    counts: dict[str, int]
```

- Produces `load_snapshot(config: ProjectConfig) -> SnapshotSelection`.

- [ ] **Step 1: Write a faithful failing fixture test**

The fixture builder writes small but schema-faithful versions of:

- `role-targets.json` with two Hero forms sharing one name;
- `characters.json`;
- `unity-object-index.json` with three exact `roles/*` paths, one without extracted PNG;
- `mapping-candidates.json` with two exact assets and one ambiguity;
- `extraction-result.json` with one known Image gap;
- `extraction-output-manifest.json` with two canonical PNGs and one ambiguous PNG;
- two methodology paper files plus matching validation manifests.

Test:

```python
selection = load_snapshot(fixture_config)
assert selection.build_id == 25006280
assert selection.counts == {
    "wanxiang_build_snapshot": 1,
    "wanxiang_character_identity": 1,
    "wanxiang_character_form_snapshot": 2,
    "wanxiang_visual_asset_snapshot": 3,
    "wanxiang_visual_candidate_snapshot": 1,
    "wanxiang_source_gap_snapshot": 1,
    "wanxiang_methodology_reference": 2,
}
assert [entity.entity_id for entity in selection.entities] == sorted(
    entity.entity_id for entity in selection.entities
)
```

- [ ] **Step 2: Add failing validation tests**

Require reason-coded failures for:

- unsupported JSON schema;
- source file SHA change;
- role-target count mismatch;
- duplicate entity ID;
- output manifest count/byte mismatch;
- paper validation hash mismatch;
- an exact ResourceManager path omitted from the asset entity set;
- an ambiguous PNG incorrectly treated as exact.

```python
with pytest.raises(SourceValidationError) as error:
    load_snapshot(tampered_config)
assert error.value.reason_code == "source_hash_mismatch"
```

- [ ] **Step 3: Run source tests and verify RED**

Expected: missing `source.py` implementation.

- [ ] **Step 4: Implement source validation and record construction**

Validation sequence:

1. resolve every configured path under the exact source root;
2. reject symlink/reparse escape and any Steam path;
3. read UTF-8 JSON and validate schema/count contracts;
4. hash every input file and methodology paper;
5. build one Build entity;
6. group 228 forms by normalized exact name into provisional identity entities;
7. create one form entity per Hero row and link identity ID;
8. create all 1,391 exact role-path asset entities from ResourceManager inventory;
9. enrich 1,341 mapped/extracted assets from mapping/result/manifest; keep 50 exact paths `not_extracted`;
10. create 172 candidate entities from `ambiguous/` manifest paths;
11. create eight source-gap entities from known Image target failures;
12. create two methodology-reference entities;
13. sort and reject duplicate entity IDs.

Do not read PNG bytes; trust the validated output manifest path/length/SHA projection.

- [ ] **Step 5: Run fixture tests and verify GREEN**

Expected: all source fixture and rejection cases pass.

- [ ] **Step 6: Run a read-only real source selection**

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python -c "from config import default_config; from source import load_snapshot; s=load_snapshot(default_config()); print(s.counts)"
```

Expected exact total `1,967` and no files created under the source root.

- [ ] **Step 7: Commit Task 2 only**

Commit source adapter and tests as:

```text
feat: validate Wanxiang snapshot sources
```

---

### Task 3: SEDB field and Task View contract

**Files:**
- Create: `projects/wanxiang-character-canon/schema.py`
- Create: `projects/wanxiang-character-canon/tests/test_schema.py`

**Interfaces:**
- Produces `FIELD_SPECS: tuple[FieldSpec, ...]`, `VIEW_SPECS: tuple[ViewSpec, ...]`, `SOURCE_OWNED_KEYS: frozenset[str]`, `CURATED_KEYS`, `PROPOSAL_KEYS`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_field_keys_are_unique_and_layered():
    keys = [field.key for field in FIELD_SPECS]
    assert len(keys) == len(set(keys))
    assert SOURCE_OWNED_KEYS.isdisjoint(CURATED_KEYS)
    assert SOURCE_OWNED_KEYS.isdisjoint(PROPOSAL_KEYS)


def test_required_views_have_exact_ordered_fields():
    names = [view.name for view in VIEW_SPECS]
    assert names == [
        "Build Snapshots",
        "Character Canon",
        "Character Forms",
        "Visual Asset Map",
        "Art Redesign Board",
        "Visual Collision Audit",
        "Source Gaps",
        "Exposure–Tension Control",
        "Methodology Provenance",
    ]
```

Assert every view key exists and no Exposure/Tension field is source-owned.

- [ ] **Step 2: Run schema tests and verify RED**

Expected: missing `schema.py`.

- [ ] **Step 3: Implement explicit field groups**

Source/build keys:

```text
source_build_id, source_schema, source_path, source_sha256, source_row,
source_evidence_level, record_status, steam_app_id, depot_manifest,
snapshot_status
```

Identity/form keys:

```text
normalized_name_key, identity_status, identity_group_evidence, linked_form_ids,
identity_entity_id, hero_id, id_name, name_zh, name_tw, title, title_tw,
birth_id, faction_text, base_description, description, card_name, rarity,
image_path, card_path, parent_id, extra_hero_id, skin_group_id, story_id,
route_filter, property_values, skill_ids
```

Asset/candidate/gap keys:

```text
role_class, resource_path, resource_numeric_id, unity_source_file, unity_path_id,
mapping_status, extraction_status, hero_id_known, png_path, png_sha256,
png_length, image_width, image_height, image_mode, alpha_extrema,
candidate_reason, related_expected_path, gap_kind, gap_expected_path,
gap_reason, gap_candidates
```

Methodology keys:

```text
methodology_title, methodology_version, methodology_path, methodology_sha256,
methodology_validation_path, methodology_intended_use
```

Curated art keys are the complete Identity/World, Rendering/Group Difference and Exposure–Tension field lists from the spec. Proposal keys:

```text
proposal_identity_summary, proposal_visual_collision, proposal_art_direction,
proposal_similarity_score, proposal_evidence_basis
```

Every field uses namespace `wanxiang_character_canon`, status `active`, exact label, type (`text`, `integer`, `number`, `boolean` or `json`) and a nonempty description.

- [ ] **Step 4: Implement all nine ordered Task Views**

Views use only fields relevant to their task. `Exposure–Tension Control` begins with `name_zh`, `art_identity_age_class`, `sfw_safety_boundary`, then the exposure/tension fields. Sparse blank cells remain absent.

- [ ] **Step 5: Run schema tests and verify GREEN**

Expected: unique layered fields and exact views pass.

- [ ] **Step 6: Commit Task 3 only**

```text
feat: define Wanxiang canon schema and views
```

---

### Task 4: Atomic SEDB plan and bootstrap store

**Files:**
- Create: `projects/wanxiang-character-canon/store.py`
- Create: `projects/wanxiang-character-canon/tests/test_store.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class EntityConflict:
    entity_id: str
    differences: tuple[FieldDifference, ...]

@dataclass(frozen=True)
class DiffPlan:
    build_id: int
    new: tuple[SourceEntity, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[EntityConflict, ...]
    missing_from_source: tuple[str, ...]
    source_fingerprint: str

    @property
    def blocked(self) -> bool: ...


class CanonStore:
    @classmethod
    def open(cls, config: ProjectConfig) -> "CanonStore": ...
    def ensure_schema(self) -> InitResult: ...
    def plan(self, selection: SnapshotSelection) -> DiffPlan: ...
    def apply(self, plan: DiffPlan) -> WriteResult: ...
    def stats(self) -> dict[str, Any]: ...
```

- [ ] **Step 1: Write failing schema-preflight tests**

Assert first `ensure_schema()` creates every field and nine views, second call reuses all, and an existing same-key field with wrong namespace/type/description raises `SchemaConflictError` without mutation.

- [ ] **Step 2: Write failing plan tests**

Cover:

- empty DB plans every fixture entity as `new`;
- exact rerun returns all `unchanged`, `blocked=False`;
- same entity ID with changed owned cell produces `source_conflict`;
- same-Build existing owned entity missing from selection produces `missing_from_source`;
- curated cell changes do not affect source plan;
- deterministic source fingerprint and sorted plan records.

- [ ] **Step 3: Write failing apply/rollback tests**

```python
plan = store.plan(selection)
result = store.apply(plan)
assert result.created_entities == len(selection.entities)
assert store.integrity_check() == "ok"
assert store.plan(selection).new == ()
```

Inject a readback failure inside the transaction and assert entity/cell counts remain zero.

- [ ] **Step 4: Run store tests and verify RED**

Expected: missing store implementation.

- [ ] **Step 5: Implement exact schema preflight**

Mirror the established Unbounded Axiom consumer pattern:

- match field key, namespace, normalized key, label, value type, description and active status;
- reject normalized-key collisions;
- match each Task View name and ordered field keys;
- create missing fields with `FieldService.bulk_create_fields` and missing views with `ViewService.create_view`;
- never rewrite a conflicting field/view.

- [ ] **Step 6: Implement owned-state and deterministic plan**

Load entities and only `SOURCE_OWNED_KEYS` cells in project namespace. Compare entity kind/label plus owned values; missing optional values equal absent cells. Missing-from-source applies to existing project entity kinds for the target Build and to the two global methodology entities.

Plan fingerprint is SHA-256 over canonical JSON containing BuildID, source hashes and sorted planned entity IDs/owned values.

- [ ] **Step 7: Implement one-transaction create-only apply**

Reject blocked plans. Recompute no source itself inside `apply`; CLI must recompute the plan immediately before apply. In one `Database.connect()` transaction:

- insert all new entities;
- resolve field IDs and insert nonblank owned cells with exact cell source;
- read back entity/cell counts and every owned value;
- run `PRAGMA integrity_check`;
- let any exception roll back the complete write.

Do not update/delete existing entities or cells.

- [ ] **Step 8: Run store tests and verify GREEN**

Expected: schema/no-op/conflict/rollback/curated-preservation tests pass.

- [ ] **Step 9: Commit Task 4 only**

```text
feat: add atomic Wanxiang SEDB bootstrap
```

---

### Task 5: Domain CLI and queries

**Files:**
- Create: `projects/wanxiang-character-canon/cli.py`
- Create: `projects/wanxiang-character-canon/tests/test_cli.py`

**Interfaces:**
- Commands: `init`, `plan --build`, `bootstrap --build`, `stats`, `search QUERY`, `show ENTITY_ID`, `unresolved`.
- Global overrides: `--source-root`, `--db`.

- [ ] **Step 1: Write failing CLI tests**

Use subprocess with UTF-8 environment and fixture paths. Assert:

- `init` JSON reports field/view counts and integrity;
- `plan` exits 0 when unblocked and never creates entities;
- `bootstrap` creates fixture entities and second run returns `status=no_op`;
- blocked plan exits 3 and database entity count stays unchanged;
- invalid source exits 2 with reason code;
- `search 万轻舟` finds identity/forms/assets;
- `show` returns entity plus sparse cells;
- `unresolved` lists the fixture gap.

- [ ] **Step 2: Run CLI tests and verify RED**

Expected: missing `cli.py`.

- [ ] **Step 3: Implement structured CLI outcomes**

Success and failure output are one JSON object on stdout. Configure stdout/stderr UTF-8 on Windows. Exit codes:

```text
0 success / no_op / read-only query
2 source validation failure
3 schema or source conflict
4 storage/readback/integrity failure
```

`plan` loads source and calls `store.plan` only. `bootstrap` loads source, ensures schema, computes plan, rejects blocked, then reloads source and recomputes an identical fingerprint immediately before `apply`.

- [ ] **Step 4: Implement domain search/show/unresolved**

Search query matches entity ID/label and project cell values. Show returns identity links/forms/assets through stored IDs without inferring new links. Unresolved filters source-gap and ambiguous-candidate entities.

- [ ] **Step 5: Run CLI tests and verify GREEN**

Expected: all command/exit-code assertions pass.

- [ ] **Step 6: Commit Task 5 only**

```text
feat: add Wanxiang canon CLI
```

---

### Task 6: Real BuildID 25006280 bootstrap acceptance

**Files:**
- Create: `projects/wanxiang-character-canon/tests/test_live_acceptance.py`
- Generate/ignore: `projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`
- Update: `projects/wanxiang-character-canon/README.md`

**Interfaces:**
- Consumes the real read-only Wanxiang research root.
- Produces accepted local database and evidence-backed README counts.

- [ ] **Step 1: Write gated live acceptance test**

The test skips unless `WANXIANG_CANON_LIVE=1`. With a temporary database and real source root it must:

```python
selection = load_snapshot(config)
assert sum(selection.counts.values()) == 1967
store.ensure_schema()
first = store.apply(store.plan(selection))
assert first.created_entities == 1967
assert store.plan(load_snapshot(config)).new == ()
assert store.plan(load_snapshot(config)).conflicts == ()
assert store.integrity_check() == "ok"
```

Also assert exact entity-kind counts and no source file hash changes.

- [ ] **Step 2: Run project tests without live flag**

Expected: all unit tests pass and one live test skips.

- [ ] **Step 3: Run real `init`, `plan`, and first bootstrap**

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python projects\wanxiang-character-canon\cli.py init
python projects\wanxiang-character-canon\cli.py plan --build 25006280
python projects\wanxiang-character-canon\cli.py bootstrap --build 25006280
```

Expected: 1,967 entities created in one transaction, integrity `ok`.

- [ ] **Step 4: Rerun bootstrap and verify no-op**

Expected: `new=0`, `conflicts=0`, `missing_from_source=0`, `unchanged=1967`, `status=no_op`.

- [ ] **Step 5: Run live acceptance and queries**

```powershell
$env:WANXIANG_CANON_LIVE = '1'
pytest -q projects\wanxiang-character-canon\tests\test_live_acceptance.py
python projects\wanxiang-character-canon\cli.py stats
python projects\wanxiang-character-canon\cli.py search 万轻舟
python projects\wanxiang-character-canon\cli.py unresolved
```

Expected: live test passes, search links identity/forms/assets, unresolved lists IDs `0–7`.

- [ ] **Step 6: Update README with measured results**

Record exact field/view/entity/cell counts, database integrity, first bootstrap and no-op results. Do not call Wave 2–5 complete.

- [ ] **Step 7: Commit Task 6 only**

Stage the README/test only; database remains ignored. Commit:

```text
test: accept Wanxiang canon Wave 1
```

---

### Task 7: Full SEDB regression, scope audit and final handoff

**Files:**
- Create: `projects/wanxiang-character-canon/VERIFY.md`
- Create: `projects/wanxiang-character-canon/evidence/wave1-verification.json`

**Interfaces:**
- Produces `WANXIANG_CANON_WAVE1_PASS` only when project, live, inherited SEDB, source-preservation and dirty-file gates all pass.

- [ ] **Step 1: Run full project suite**

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
pytest -q projects\wanxiang-character-canon\tests
```

Expected: all project tests pass; live test behavior matches the explicit flag.

- [ ] **Step 2: Run inherited SEDB suite and compile checks**

```powershell
$env:PYTHONPATH = 'current\src'
pytest -q current\tests
python -m compileall -q current\src projects\wanxiang-character-canon
```

Expected: inherited SEDB suite remains green and `current/` has no diff.

- [ ] **Step 3: Verify real database and source preservation**

Require:

- `PRAGMA integrity_check=ok`;
- 1,967 entities and exact per-kind counts;
- second bootstrap no-op;
- methodology and Wanxiang source hashes unchanged;
- no source file written under game research root;
- database and sidecars ignored;
- `current/` unchanged.

- [ ] **Step 4: Verify dirty-file fingerprint and changed-file scope**

The existing brief remains 6,850 bytes and SHA `30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`. Git changes since pre-project HEAD may contain only:

- `projects/wanxiang-character-canon/**`
- this plan/spec commits.

No other untracked/tracked file is staged or absorbed.

- [ ] **Step 5: Write verification JSON and VERIFY.md**

JSON fields include status, commit/tree, source hashes, project/inherited test counts, per-kind entity counts, cell/field/view counts, first/no-op bootstrap results, integrity, source write count, current diff count, dirty fingerprint and `NotMeasured` boundaries.

- [ ] **Step 6: Commit final verification artifacts**

```text
docs: verify Wanxiang canon Wave 1
```

- [ ] **Step 7: Do not push or publish**

Report local commits, database path, search command, remaining Wave 2–5 work and the unchanged unrelated brief. Integration remains local on `main`.

---

## Plan Self-Review Result

- Scope: one independently useful Wave 1 subsystem; narrative/context Waves 2–5 remain designed but unimplemented.
- Spec coverage: direct-main boundary, one-way dependency, snapshot/entity topology, 1,967 counts, source/curated/proposal separation, sparse art fields, views, plan/apply conflict policy, real acceptance and dirty-file preservation each map to a task.
- Type consistency: `SourceEntity` and `SnapshotSelection` originate in Task 2; `DiffPlan` and `CanonStore` originate in Task 4 and are consumed by Tasks 5–7.
- Safety: source writes, SEDB core changes, provider calls, game runtime and publication are excluded.
- Execution: inline only, no subagents.

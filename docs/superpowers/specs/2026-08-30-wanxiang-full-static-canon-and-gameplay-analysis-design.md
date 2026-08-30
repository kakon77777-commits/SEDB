# Wanxiang Full Static Canon and Gameplay Analysis Design

**Status:** `WRITTEN_APPROVED_BY_USER`

**Date:** 2026-08-30

**Extends:** `docs/superpowers/specs/2026-08-30-wanxiang-character-canon-sedb-design.md`

## 1. Purpose

Extend the accepted Wanxiang Character Canon SEDB Wave 1 database into a
complete local static-data canon for Steam BuildID `25006280`, then derive an
evidence-bounded semantic reference graph and six gameplay-analysis reports.

The completed system must:

- preserve all 29,939 rows from the 36 shipped `ModDocs/AllExcel` workbooks;
- enrich the existing 228 character-form entities without changing their IDs;
- distinguish official shipped ModDocs data, packaged runtime candidates,
  mixed ModTools working data and Workshop overlays;
- retain complete EventDialog rows while keeping ordinary listings compact;
- create only explicit, rule-backed reference edges;
- support static analysis of characters, events, choices, pacing,
  relationships, combat and progression;
- publish one canonical local context index that another AI or a compacted
  conversation can understand quickly;
- leave the installed game, Steam, Workshop, frozen inputs and SEDB `current/`
  unchanged.

This is a static documented-data acceptance. It is not runtime ownership,
runtime reachability, balance acceptance or a claim that the game has already
been made more fun.

## 2. Authority and filesystem boundaries

### 2.1 SEDB implementation root

Continue directly on the existing local SEDB `main` branch under:

`D:\Ai\work together\SEDB\projects\wanxiang-character-canon`

The user has explicitly selected direct-main development, no worktree and no
subagent-driven implementation. No push, publication, deployment or release is
authorized.

SEDB `current/`, existing projects and release archives remain read-only
dependencies.

### 2.2 Immutable source root

The complete static canon reads only from the frozen copy:

`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\baseline\game\wanxiang\wanxiang\ModDocs\AllExcel`

The source adapter verifies workbook records against:

`evidence/source-inventory/current-verification.manifest.json`

That manifest measured 244,516 bytes with SHA-256:

`0B607E20ADE02510181CB5B3145AE3F0D68E6AABA16C50458A0E725EFC5C6F1F`

The importer validates every consumed workbook's length and SHA-256 against the
manifest. Trusting only the manifest hash without verifying its member records
is insufficient.

The path mapping is exact and local: manifest member
`wanxiang/ModDocs/AllExcel/<file>` maps to `<immutable source root>/<file>`.
The adapter never resolves the manifest's former Steam root or reads the live
installation to satisfy this contract.

### 2.3 Explicitly excluded canonical sources

- `ModTools/Data`: installed working data with confirmed mixed provenance.
- `ModTools/Excel`: mutable tool working workbooks.
- `baseline/workshop/**`: preserved external overlays, including Tingchao
  Island, expression-disable, clothing and full-body portrait mods.
- the live Steam installation and live Workshop paths.

These may be registered as provenance evidence but never merged into the base
canon automatically.

After unsubscribe, the active Workshop directory was observed empty and its
manifest no longer named the four item IDs. `ModTools/Data` nevertheless still
contained Tingchao Island rows. Therefore Workshop subscription state and
ModTools working state are separate layers.

### 2.4 Runtime candidates

The 52 frozen `WXQXZ_Data/StreamingAssets/*.dat` files are registered by path,
length and SHA-256 as packaged-runtime candidates. They are not decoded or
declared authoritative in this phase.

### 2.5 Authorized output root

New research reports may be written only under:

`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4`

The canonical context entry may be written at:

`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`

Immutable-input verification excludes only those newly authorized output paths;
it continues to hash-gate every source workbook and other consumed input.

## 3. Measured AllExcel baseline

All workbooks use `Sheet1`. Row 1 is the field-name row; rows 2–4 are the type,
sentinel/default and description metadata rows. Source records begin at physical
row 5. Physical row number is preserved on every entity.

| Table | Data rows |
| --- | ---: |
| Achievement | 120 |
| Assist | 199 |
| Audio | 50 |
| Battle | 308 |
| Birth | 2 |
| Buff | 10 |
| Condition | 2,924 |
| Dice | 23 |
| Dictionary | 268 |
| Difficulty | 4 |
| Effect | 34 |
| Ending | 75 |
| Event | 3,589 |
| EventDialog | 17,210 |
| EventDice | 8 |
| EventNormal | 14 |
| EventPuzzle | 13 |
| EventResult | 1,627 |
| EventSelection | 155 |
| Formula | 788 |
| Hero | 270 |
| HotKey | 14 |
| Map | 109 |
| MapInfo | 13 |
| Monster | 267 |
| News | 113 |
| PlayerPortrait | 10 |
| Point | 27 |
| Property | 121 |
| PuzzleGroup | 198 |
| Relation | 50 |
| Skill | 928 |
| SkillCondition | 44 |
| Switch | 77 |
| Talent | 85 |
| UIText | 192 |
| **Total** | **29,939** |

Measured source projection:

- nonblank source cells: 496,128;
- canonical compact row-JSON UTF-8 bytes: 18,702,469;
- EventDialog rows: 17,210;
- simplified plus traditional EventDialog description characters: 1,105,423;
- duplicate non-null `Id` values within each table: zero;
- Formula rows with null `Id`: one;
- Hero distribution: 228 `Type=0`, 41 `Type=1`, one `Type=null` sentinel
  with `Id=-1`.

These are exact acceptance counts for this Build and source manifest.

## 4. Workbook reader contract

Create a project-local OpenXML reader rather than importing from the art
toolchain at runtime. It may reuse the accepted algorithm but has its own tests
and version.

The reader must:

- use only Python standard-library ZIP/XML support;
- resolve workbook relationships according to OPC package rules;
- accept both relative targets such as `worksheets/sheet1.xml` and
  package-absolute targets such as `/xl/worksheets/sheet1.xml`;
- reject path traversal, external worksheet targets and missing relationships;
- read shared strings, inline strings, booleans, integers, floats, strings,
  errors and blank cells deterministically;
- preserve source row number;
- reject a missing row-1 header or duplicate nonblank header name by default;
- permit only an audited, workbook-hash-bound header override: exact
  EventSelection workbook SHA-256
  `663C7422DE201BD6D5E8EC2923E5798AD94CA2C59F456138FB797AEBF50C2308`,
  cell `CY1`, expected `Condition9`, replacement `Condition16`; this repairs the
  documented slot-16 source typo without weakening duplicate-header rejection;
- retain rows 2–4 as workbook metadata evidence but never emit them as source
  records;
- canonicalize each data row with UTF-8, sorted keys and compact JSON;
- calculate a SHA-256 for every canonical row payload;
- configure CLI output as UTF-8 on Windows, never CP950.

The existing reader failure on EventResult and Condition is a required
regression case: their package-absolute relationship target must resolve to the
same ZIP member as its relative equivalent.

EventSelection is a second required regression: its source header row contains
both the real slot-9 `Condition9` at `BI1` and a mislabeled slot-16 `Condition9`
at `CY1`. An unqualified dictionary projection loses slot 9. The audited
override must retain both `Condition9` and `Condition16`, and must fail if the
workbook hash or expected `CY1` value changes.

## 5. Canon topology and stable identities

### 5.1 Complete source-row representation

Every one of the 29,939 records appears exactly once in the semantic database.

For 35 non-Hero tables, each row is a
`wanxiang_table_row_snapshot` entity. Required fields include:

- `source_build_id`;
- `source_layer=SHIPPED_MODDOCS_ALL_EXCEL`;
- `source_authority=STATIC_DOCUMENTED_DATA_RUNTIME_OWNERSHIP_NOT_MEASURED`;
- `source_table`;
- `source_record_id` when non-null;
- `source_row`;
- `source_workbook_path`;
- `source_workbook_sha256`;
- `source_row_sha256`;
- `source_row_payload`;
- source-observed name/title/description/flag summaries when available.

`source_row_payload` preserves all workbook columns and values, including
complete EventDialog text. List and search commands return compact summaries;
`show` returns the complete sparse cells and payload.

### 5.2 Hero rows

- The 228 `Type=0` rows enrich the existing
  `wanxiang_character_form_snapshot` entities
  `wx-build-25006280-hero-<hero-id>`.
- The 41 `Type=1` rows become `wanxiang_treasure_snapshot` entities.
- The `Type=null`, `Id=-1` row becomes one
  `wanxiang_hero_sentinel_snapshot` entity.

The importer validates each existing form's Hero ID, IdName, names, titles,
Birth, Menpai, expected Image/Card paths, ParentId and source row against the
full Hero row. Any mismatch is a whole-batch conflict.

Full Hero enrichment materializes:

- BaseDesc, Desc and traditional text;
- Level, HP, Power, rarity and card fields;
- four Skill IDs;
- six Property IDs;
- three Ji/JiValue pairs;
- IsPlayer, ParentId, ExtraHeroId, SkinGroupId and StoryId;
- route filter, point, atlas, acquisition text and flag;
- complete canonical row payload and row SHA.

No new character identity is inferred from this enrichment.

### 5.3 Stable row IDs

For non-Hero rows with a non-null `Id`, construct the stable ID from:

`BuildID + normalized table key + canonical JSON scalar Id`

Use the first 16 lowercase hexadecimal characters of SHA-256 over that exact
UTF-8 projection:

`wx-build-<build>-row-<table-slug>-<digest>`

For a row without `Id`, use workbook SHA, table key and physical row number:

`wx-build-<build>-row-<table-slug>-r<row>-<digest>`

The original source ID and row remain normal fields; a hash-based entity ID is
not presented as a human-readable source ID.

All 29,939 source rows map to 29,939 semantic records, of which 228 reuse Wave
1 form IDs. Before reference-edge entities, the accepted database therefore
contains:

`1,967 + 29,939 - 228 = 31,678` entities.

### 5.4 Build-level catalog evidence

Enrich `wx-build-25006280` with new, previously absent fields:

- catalog schema version;
- AllExcel manifest path and SHA;
- ordered workbook hashes;
- exact table counts;
- total row count;
- catalog source fingerprint;
- reader version.

The accepted Wave 1 `source_sha256` remains unchanged.

## 6. Per-cell provenance and additive enrichment

Extend `SourceEntity` so a value may carry its own exact source string. A single
entity can therefore retain Wave 1 registry provenance for old cells and Hero
workbook provenance for newly enriched cells.

The fallback entity-level `cell_source` remains valid for entities whose cells
all come from one source. Explicit per-key provenance overrides the fallback.

Plan comparison includes:

- entity kind and label;
- source-owned value;
- source string for each importer-owned cell;
- absence versus presence.

Curated and proposal cells remain outside source equality and are never
rewritten.

## 7. Reference graph

### 7.1 Edge entity

Every explicit reference becomes a
`wanxiang_reference_edge_snapshot` entity with:

- source entity ID, table, field and repeated-slot index;
- raw source value;
- target table and source ID;
- resolved target entity ID when present;
- `resolution_status`: `resolved`, `missing_target` or `unknown_semantics`;
- rule ID and rule-set version;
- evidence level;
- `STATIC_LINK_ONLY_RUNTIME_REACHABILITY_NOT_PROVEN` boundary.

The stable edge ID is the first 16 characters of SHA-256 over canonical source
entity ID, source field, slot, target table and canonical target ID.

For the accepted Build/source/rule version, the exact edge count is 40,075:
31,117 `resolved`, 8,958 `missing_target` and zero `unknown_semantics`.
`plan` must publish the deterministic count and per-rule breakdown before apply;
the accepted rerun must reproduce the same count and edge IDs. Combined with
the 31,678 pre-edge base, the exact full entity count is 71,753.

### 7.2 Explicit reference families

- Hero → Birth, Parent Hero, Skill, Property, ExtraHero, Story.
- Map → Parent Map.
- Birth → Resident Map.
- Relation → Birth, Property, Guide Event.
- Event → Map, Condition, Result and typed logic record.
- EventDialog → next EventDialog and next Event.
- EventSelection → Condition and option Event.
- EventNormal → next Event.
- EventPuzzle → PuzzleGroup, success Event and failure Event.
- EventDice → Dice.
- Battle → success Event, failure Event and fixed Hero.
- Skill → SkillCondition, Formula and Effect.

Event `LogicType` maps `LogicId` only through a versioned, evidence-backed enum
registry to Dialog, Selection, Normal, Battle, Puzzle or Dice. An unknown enum
value produces `unknown_semantics`, not a guessed edge.

Condition, EventResult, EventSelection and other repeated columns are first
normalized into ordered JSON operation blocks. Only operation types with an
explicit reviewed enum mapping create target edges.

### 7.3 Sentinel and multi-value rules

- null, blank, `nil` and numeric `-1` mean no reference for the edge layer;
  their raw value remains in `source_row_payload`;
- `&`-delimited ID fields emit one ordered edge per nonblank component;
- duplicate components are rejected unless the source contract explicitly
  permits them;
- names, descriptions and visual similarity never create canonical edges;
- a syntactically valid target ID absent from its table creates
  `missing_target` and does not silently disappear.

Missing targets do not block the catalog import. Parser/schema/hash drift,
duplicate stable IDs and contradictory existing owned cells do block it.

## 8. Atomic in-place database migration

### 8.1 Recoverable Wave 1 checkpoint

Before the first full-catalog apply:

- close all project database connections;
- run `PRAGMA wal_checkpoint(TRUNCATE)` and require exact `(0, 0, 0)` so no
  uncheckpointed frames remain; Windows may retain an empty WAL and shared-memory
  sidecar after a successful checkpoint, so sidecar filename presence alone is
  not a failure;
- create an ignored local Wave 1 SQLite backup;
- record original database length and SHA in a committed evidence manifest;
- verify the backup with `PRAGMA integrity_check=ok` and the accepted Wave 1
  counts.

Never overwrite the backup.

### 8.2 Plan states

The full-catalog plan classifies records as:

- `new`: entity does not exist;
- `enrich`: entity metadata matches and one or more selected source cells are
  absent;
- `unchanged`: every selected source cell and provenance matches;
- `conflict`: kind, label, existing source value or provenance differs;
- `missing_from_source`: an entity owned by the full-catalog selection scope is
  absent from the new source selection.

`enrich` may insert only absent cells. It may not update an existing cell.

The plan fingerprint is SHA-256 over BuildID, table counts, workbook hashes,
canonical source records, per-cell sources, reference-rule version and ordered
edges.

### 8.3 Apply

Apply operates in one SQLite transaction:

1. verify schema and view preflight;
2. verify every `new` entity remains absent;
3. verify every `enrich` cell remains absent;
4. insert new entities;
5. insert new and enrichment cells;
6. insert reference-edge entities and cells;
7. read back metadata, values, sources and exact counts;
8. verify the 1,967 accepted Wave 1 entities still exist;
9. verify curated/proposal cells are byte-equivalent;
10. run `PRAGMA integrity_check`.

Any exception rolls back the entire catalog expansion. No update or delete is
permitted.

The second source load immediately before apply must reproduce the same plan
fingerprint.

## 9. Schema and Task Views

Retain all nine Wave 1 views unchanged and add:

1. **AllExcel Table Catalog** — table, source ID, row, payload SHA and summary.
2. **Full Hero Context** — complete form background, stats, skills and routes.
3. **World and Map Context** — Birth, Map and MapInfo records and parent links.
4. **Relationship Routes** — Relation guide steps, properties and event links.
5. **Event Network** — Event, condition, logic, result and static graph fields.
6. **Dialogue Index** — compact EventDialog locator and next links.
7. **Combat and Progression** — Battle, Skill, Formula, Effect, Buff and
   Difficulty records.
8. **Reference Resolution** — resolved/missing/unknown edge audit.
9. **Static Gameplay Questions** — metrics linked to evidence and falsifying
   tests.
10. **Catalog Provenance** — workbook, reader, fingerprints and acceptance.

Views remain sparse projections; `source_row_payload` is not displayed in broad
matrix views by default.

CLI additions:

```text
catalog-plan --build 25006280
catalog-bootstrap --build 25006280
table TABLE [--id VALUE] [--limit N]
edges ENTITY_ID [--direction in|out|both]
dialog DIALOG_ID
route RELATION_ID
gameplay-report NAME
context-index
```

Existing `plan`, `bootstrap`, `stats`, `search`, `show` and `unresolved`
continue to work.

## 10. Static gameplay analysis

Generate both Markdown and JSON evidence for six analyses under
`analysis/sedb-wave2-4`.

### 10.1 Character coverage

Measure background/description completeness, skills, properties, relations,
event/dialog mentions and visual asset coverage by Hero form and provisional
identity.

### 10.2 Event network

Measure nodes, typed edges, in/out degree, static root candidates, terminal
nodes, strongly connected components, cycles, missing targets and isolated
records. Never label a node runtime-unreachable without runtime evidence.

### 10.3 Choice and consequence

Measure selection count, enabled-option count, branch destinations, result
diversity, short-horizon convergence and repeated destinations. Treat a static
branch as authored possibility, not a proven player-visible choice.

### 10.4 Time and pacing

Measure Event `CostTime`, `Times`, `OnceInTurn`, priority/weight distribution,
year/month conditions when explicit, map event density and repeatable-event
surfaces.

### 10.5 Relationship routes

Measure guide-step counts, explicit Property gates, time/map/battle conditions,
repeated fallback events, cross-route event/property reuse and missing route
targets.

### 10.6 Combat and progression

Measure skill AP costs, launch/success rates, formula/effect use, battle party
constraints, success/failure continuations and the four Difficulty multipliers.
Static representational diversity is not accepted as live build diversity.

Every report uses four claim classes:

- `OBSERVED`;
- `INFERRED`;
- `UNKNOWN`;
- `FALSIFYING_TEST`.

Each metric records source tables, rule version and database/source
fingerprints.

## 11. Context-compression and multi-AI index

### 11.1 Canonical human entry

Create:

`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`

It must be understandable in roughly 90 seconds and contain:

- current status and BuildID;
- a six-item reading order;
- exact paths to SEDB code, database, specs, verification and reports;
- data-layer authority ranking;
- entity/view counts and source fingerprints;
- common CLI recipes;
- links to character, world, event, relationship, combat and art material;
- `OBSERVED / INFERRED / UNKNOWN / NOT_MEASURED` boundaries;
- the remaining runtime and MOD-engineering work;
- how another AI should refresh evidence instead of trusting stale counts.

### 11.2 Machine-readable entry

Create:

`analysis/sedb-wave2-4/context-index.json`

Required keys include schema, BuildID, verification-basis commit/tree, source
fingerprints, table/entity/edge/view counts, report paths, database path,
query recipes, unresolved counts, accepted statuses, NotMeasured boundaries and
next-work routing.

### 11.3 SEDB-side discovery pointer

Create a short
`projects/wanxiang-character-canon/AI_CONTEXT_INDEX.md` that points to the
canonical research-root index and machine JSON. It must not duplicate changing
counts or report prose.

The canonical index is the only human-maintained full index. Link checks and
machine-JSON validation are acceptance gates.

## 12. Error and drift policy

Whole invocation blocks on:

- source manifest or workbook hash drift;
- unsupported workbook relationship or cell type;
- missing/duplicate header;
- wrong table count;
- duplicate stable row/edge ID;
- Hero reduced/full-row disagreement;
- schema or Task View conflict;
- changed existing importer-owned cell value/source;
- disappearance of an owned catalog record;
- plan fingerprint drift between reloads;
- database backup, readback or integrity failure;
- unauthorized write outside SEDB project or approved analysis output root.

The importer records but does not block on:

- syntactically valid missing reference target;
- unknown condition/result operation enum;
- static root/terminal/isolation findings;
- missing optional display text;
- absence of a normalized Menpai table.

All nonblocking cases remain queryable evidence and appear in the unresolved
reports.

## 13. Test and acceptance gates

### 13.1 Parser and source tests

- relative and package-absolute OPC relationships;
- shared/inline strings, booleans, integers, floats and blanks;
- UTF-8 output containing simplified Chinese that CP950 cannot encode;
- metadata/data row boundary;
- workbook hash/length validation;
- exact 36-table and 29,939-row contract;
- exact per-table counts;
- one null-ID Formula row and Hero type distribution;
- canonical row JSON and SHA determinism.

### 13.2 Identity and enrichment tests

- stable row IDs for numeric, string and null IDs;
- all 228 form IDs retained;
- 41 treasure and one sentinel records;
- reduced/full Hero reconciliation;
- missing-cell enrichment;
- different existing value/source conflict;
- curated/proposal cell preservation.

### 13.3 Edge tests

- every explicit reference family;
- typed Event LogicType registry;
- repeated slot order;
- `&` multi-ID splitting;
- null/blank/nil/-1 suppression;
- resolved, missing and unknown status;
- no name/similarity-generated edges;
- deterministic edge count and IDs on replay.

### 13.4 Store and CLI tests

- Wave 1 backup and integrity;
- empty/full/enrichment/no-op/conflict plans;
- one-transaction rollback under injected readback failure;
- exact entity/cell/edge counts;
- complete EventDialog payload through `show` and `dialog`;
- compact list/search output;
- new view order and schema preflight;
- UTF-8 JSON exit-code behavior.

### 13.5 Analysis and context tests

- report JSON reconciles to stored rows/edges;
- Markdown claim classes have supporting evidence;
- no runtime-reachability wording upgrade;
- all index links resolve;
- context-index JSON validates and names current evidence basis;
- canonical/pointer index topology has no duplicated changing facts.

### 13.6 Real acceptance

Require:

- all Wave 1 project tests remain green;
- all new project tests pass;
- inherited SEDB `current/` 189 tests pass;
- exact 31,678 pre-edge entity base plus 40,075 edges, totaling 71,753;
- 29,939 source rows represented exactly once;
- 228 enriched forms, 41 treasures and one sentinel;
- EventDialog count 17,210;
- catalog second bootstrap `no_op`;
- SQLite `PRAGMA integrity_check=ok`;
- Wave 1 cells and curated/proposal cells retained;
- every consumed input hash unchanged;
- installed game and Workshop write count zero;
- `current/` diff count zero;
- unrelated brief still 6,850 bytes and SHA-256
  `30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`;
- changed files limited to the existing Wanxiang SEDB project, this spec/plan
  and the approved game-analysis/context output paths.

Final accepted status:

`WANXIANG_FULL_STATIC_CANON_PASS`

This status does not imply runtime or gameplay-fun acceptance.

## 14. Implementation slices

1. Reader and source-manifest adapter.
2. Complete row catalog and Hero enrichment.
3. Additive store migration and real catalog bootstrap.
4. Explicit reference-rule registry and edge import.
5. Static gameplay analysis and report reconciliation.
6. AI context index, final verification and local handoff.

Each slice uses TDD, a fresh verification gate and a local commit. Implementation
is inline only.

## 15. Non-goals and NotMeasured boundaries

- No foreground game launch or input.
- No live save, RNG, event-order or transition observation.
- No decoding claim for `.dat` files.
- No Steam/Workshop mutation.
- No edit of the installed original, frozen source workbooks or PNGs.
- No automatic canonical identity merge/split.
- No AI-written curated art fields.
- No image generation/editing.
- No MOD package emission or runtime load test.
- No SEDB core refactor or commercial cleanup.
- No push, PR, publication, deployment or release.

Future runtime observation must use an isolated, fingerprinted test copy and a
separate approval gate.

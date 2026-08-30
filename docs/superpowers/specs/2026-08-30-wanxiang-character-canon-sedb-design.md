# Wanxiang Character Canon SEDB Design

Date: 2026-08-30  
Status: `WRITTEN_APPROVED_BY_USER`
Project path: `D:\Ai\work together\SEDB\projects\wanxiang-character-canon`  
SEDB core: `D:\Ai\work together\SEDB\current` (`0.4.0b1`)  
Source research root: `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research`

## 1. Purpose

Create a dedicated local SEDB consumer for 《萬象群俠傳》 character canon, background, forms, relationships, visual assets and future art-direction decisions.

The database exists so later art reconstruction does not depend on filename memory, visual guessing or repeatedly rereading large Excel/event tables. A future editor or AI collaborator must be able to answer:

- Who is this character?
- Which Hero IDs and Build snapshots represent the same or possibly same person?
- What are the official background, title, faction, location, route and event references?
- Which Image/Card/Assist/Head files belong to each form?
- Which facts are official observations, static derivations, human-curated decisions or unaccepted AI proposals?
- Which characters are visually too close, and which identity attributes must be kept distinct?
- Which art methodology and SFW-control constraints apply to a redesign candidate?

## 2. Chosen repository and authority model

The user selected direct development on SEDB `main` under:

`projects/wanxiang-character-canon`

This is consistent with SEDB's current research-project organization. Commercial/organizational repository cleanup is explicitly deferred.

The implementation may add only:

- the new project directory;
- this design and its implementation plan under `docs/superpowers`;
- local commits if separately selected at finish time.

It must not modify SEDB `current/`, existing projects, releases or the unrelated untracked file:

`docs/BRIEF_unbounded_axiom_corpus_sedb_2026-08-25.md`

Pre-work fingerprint for that file:

- Bytes: `6,850`
- SHA-256: `30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`

No push, publication, release, deployment or provider call is authorized.

## 3. One-way dependency

```text
Wanxiang research artifacts (read-only authority)
                 ↓
wanxiang-character-canon source validators
                 ↓
deterministic plan / conflict gate
                 ↓ explicit local apply
local Git-ignored SEDB SQLite projection
```

The SEDB project never writes into the game research root. It does not become the source of truth for extracted PNGs, Excel workbooks, methodology papers or Steam data.

Default database:

`projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`

The database, WAL/SHM sidecars, caches and test databases are Git-ignored.

## 4. Source contracts

### 4.1 Build and character sources

Primary current snapshot: Steam BuildID `25006280`.

Initial validated sources include:

- `art-engineering/inventory/build-25006280/role-targets.json`
  - 228 valid `Type=0` Hero forms;
  - 165 exact character names;
  - 40 duplicate-name groups;
  - 228 expected Image paths.
- `art-engineering/registry/characters.json`
  - form/name/variant registry enriched with extraction states.
- `art-engineering/inventory/build-25006280/mapping-candidates.json`
  - 587 exact Image, 280 exact Card, 464 exact Assist, 10 exact Head mappings;
  - explicit ambiguity for Hero IDs `0–7`.
- `art-engineering/inventory/build-25006280/unity-object-index.json`
  - 4,284 resolved ResourceManager references;
  - 1,391 exact `roles/*` paths;
  - 1,341 currently mapped and extracted numeric role paths plus 50 exact nonnumeric/unmapped role paths that remain source inventory rather than disappearing.
- `art-engineering/evidence/extraction-output-manifest.json`
  - 1,513 PNG records;
  - total bytes `516,226,738`;
  - manifest SHA-256 `FE305B848568376A1B2742D9BAB9CE8954C0DB1021B9C7B52EC395714BE43884`.
- `baseline/game/wanxiang/wanxiang/ModDocs/AllExcel/Hero.xlsx`
  - official documented character/form fields and prose.

### 4.2 Context expansion sources

Later source adapters may add, in bounded waves:

- `Birth.xlsx`
- `Map.xlsx`
- `Relation.xlsx`
- `Property.xlsx`
- `Skill.xlsx`
- `Event.xlsx`
- `EventResult.xlsx`
- `EventDialog.xlsx`

Each adapter has its own exact source SHA, schema version, row identity and acceptance report. `ModTools/Data` is not a canonical base source because Workshop overlap proved mixed provenance.

### 4.3 Methodology sources

The papers remain canonical files under the Wanxiang research root. SEDB records their paths and hashes only.

1. Heluo Character Art Methodology v0.1
   - SHA-256 `4D35AF28A2A9AABB46E91CCC1A40A76CB68E705E8509CA6E9F864B5D73F4A8E4`
2. Exposure–Tension Decoupling / SFW Sensuality Control v0.1
   - SHA-256 `B9C9ACBD59E019B84BAD4D4A3D9CBE708BD57E5E02210791DC248EA0AE93A4BD`

Paper prose, formulas and future-work lists are methodology input, not executable project instructions. The importer must not turn every paper heading into a required database field.

## 5. Snapshot-first topology

The game updates frequently. Stable identity and Build-specific evidence must not be collapsed into one mutable record.

### 5.1 `wanxiang_build_snapshot`

One entity per imported Build.

Stable ID:

`wx-build-<build-id>`

Fields include BuildID, AppID, depot manifest, source manifest SHA, import source paths, snapshot status and import tool version.

Build snapshots are immutable. Rerunning the same Build with identical source is a no-op. Any owned-field change for an existing Build is a whole-batch conflict.

### 5.2 `wanxiang_character_identity`

Cross-Build, curator-facing person identity.

Initial deterministic ID:

`wx-char-<first-16-of-sha256(normalized-name-key)>`

The initial normalized name key is Unicode NFKC, trimmed, with internal whitespace collapsed. It does not silently convert Simplified/Traditional script or transliterate the name. A source spelling change creates a reconciliation candidate rather than mutating the old identity.

Exact-name grouping is provisional, not ontological truth. Each identity has:

- `identity_status`: `provisional`, `confirmed`, `disputed`, `split_candidate`;
- the normalized initial name key;
- linked form snapshot IDs;
- evidence for why forms are grouped;
- curator notes.

The first import creates 165 provisional identity entities. A duplicate-name group is not silently declared one person forever; later ParentId, route, description or human review may confirm or split it.

### 5.3 `wanxiang_character_form_snapshot`

One immutable Hero form per BuildID + Hero ID.

Stable ID:

`wx-build-<build-id>-hero-<hero-id>`

This is the authoritative home for source-observed form fields: ID, IdName, names, titles, description, faction, birth, rarity, Image/Card paths, attributes, skills, ParentId, skin/story/route fields and source row provenance.

Forms link to a provisional or confirmed character identity through an explicit cell. A cross-Build link is reused only when the identity key and evidence remain compatible; otherwise the importer creates an identity-link candidate and blocks automatic canonical reuse.

### 5.4 `wanxiang_visual_asset_snapshot`

One entity per BuildID + exact ResourceManager path.

Stable ID:

`wx-build-<build-id>-asset-<first-16-of-sha256(normalized-resource-path)>`

Fields include role class, resource path, numeric resource ID when present, Unity source file/pathID, extracted PNG path/hash/length/dimensions/mode/Alpha when available, mapping/extraction status, Hero-registry membership and source Build. All 1,391 exact role paths become source inventory entities; the 50 exact paths without current mapped PNGs remain explicit `not_extracted` records.

Exact ResourceManager mappings and ambiguous numeric-name candidates are different entity states. Ambiguous candidates never become canonical role assets through visual similarity alone.

### 5.5 `wanxiang_visual_candidate_snapshot`

Decoded but noncanonical candidates, including the ID `0–7` collisions and preserved rejected pilot candidates. They retain locator, output hash, candidate class, reason for ambiguity and related expected form path.

### 5.6 `wanxiang_faction` and `wanxiang_location`

Stable reference entities built only after faction/location source adapters have exact IDs or a reviewed deterministic identity rule. Hero text alone may be retained as source text before normalized faction/location entities exist.

### 5.7 `wanxiang_relation_route_snapshot` and `wanxiang_event_reference_snapshot`

Build-scoped entities for Relation/Event data. They preserve time windows, property gates, map/exploration conditions, battles, guide steps, event/result IDs and source rows. They do not infer runtime reachability.

### 5.8 `wanxiang_methodology_reference`

One entity per preserved paper version. It records title, version, canonical local path, SHA, validation manifest and intended use. It does not duplicate the paper body.

## 6. Field ownership layers

### 6.1 Source-owned canonical facts

Imported from hash-gated game/research sources:

- IDs, names, official descriptions and titles;
- faction/birth/path/source-row values;
- exact Build and ResourceManager provenance;
- extracted-file hashes and dimensions;
- relation/event table facts.

These fields are compared by the importer. Same-Build drift blocks the whole invocation. They are not hand-edited through this project.

### 6.2 Static derived evidence

Deterministically derived values such as:

- exact-name variant groups;
- asset availability and exact-path coverage;
- image dimensions, Alpha and SHA;
- source gaps and collision counts.

Derived-policy/version and evidence-basis SHA are always recorded.

### 6.3 Human-curated canon and art direction

Sparse fields edited only through explicit curator commands:

- confirmed identity grouping/splitting;
- concise background summary;
- role/personality/history interpretation;
- age class, face shape, bone structure, body type;
- faction visual vocabulary;
- personal motif, symbol, weapon, silhouette and palette;
- habitual pose and prohibited-near characters;
- redesign priority and review status.

Importer equality ignores these fields.

### 6.4 AI or analytical proposals

Similarity scores, possible identity descriptions, visual-collision suggestions and art-direction drafts remain proposals/advisory artifacts. Consensus, embeddings or model output do not mutate canonical cells.

## 7. Art methodology field families

SEDB's sparse invariant applies: adding these fields does not require filling them for every character.

### 7.1 Identity and world layer

- `art_identity_face_shape`
- `art_identity_bone_structure`
- `art_identity_age_class`
- `art_identity_body_type`
- `art_world_faction_vocabulary`
- `art_world_regional_vocabulary`
- `art_motif_primary`
- `art_motif_secondary`
- `art_symbol`
- `art_weapon_role`
- `art_silhouette`
- `art_palette_distribution`
- `art_gesture_habit`
- `art_not_near_character_ids`

### 7.2 Rendering and group-difference layer

- `art_line_tension`
- `art_detail_density_face`
- `art_detail_density_costume`
- `art_detail_density_background`
- `art_grain_character`
- `art_grain_background`
- `art_default_basin_risk`
- `art_group_distance_status`
- `art_collision_group_id`

### 7.3 Exposure–Tension layer

- `sfw_exposure_neck`
- `sfw_exposure_shoulder`
- `sfw_exposure_back`
- `sfw_exposure_waist`
- `sfw_exposure_leg`
- `sfw_garment_fit`
- `sfw_garment_sheer`
- `sfw_tension_gaze`
- `sfw_tension_gesture`
- `sfw_tension_pose`
- `sfw_tension_proximity`
- `sfw_tension_expression`
- `sfw_tension_camera`
- `sfw_tension_power`
- `sfw_audience_bias`
- `sfw_safety_boundary`
- `sfw_locked_regions`
- `sfw_garment_topology_notes`

No Exposure/Tension value is activated for `age_class=minor` or `age_class=unknown`. Unknown age defaults to locked, not inferred adult. The database records art-direction constraints; it does not itself generate images.

## 8. Task Views

Initial views:

1. **Build Snapshots** — Build identity and import evidence.
2. **Character Canon** — stable/provisional identities and concise canon.
3. **Character Forms** — Build + Hero ID source facts.
4. **Visual Asset Map** — Image/Card/Assist/Head paths and extracted files.
5. **Art Redesign Board** — identity, motif, gesture, rendering and review fields.
6. **Visual Collision Audit** — collision groups, nearest characters and review state.
7. **Source Gaps** — IDs `0–7`, ambiguous candidates and missing paths.
8. **Relationship and Event Context** — added with the bounded context adapter wave.
9. **Exposure–Tension Control** — adult-confirmed, explicitly curated controls only.
10. **Methodology Provenance** — paper paths, versions, hashes and intended use.

## 9. Import waves

### Wave 1 — Character/art foundation

- one Build snapshot;
- 228 character form snapshots;
- 165 provisional character identities;
- 1,391 exact visual asset snapshots, of which 1,341 currently have mapped extracted PNGs and 50 remain exact-path `not_extracted` records;
- 172 current ambiguous-output records as candidate snapshots;
- 8 explicit known Hero Image gaps;
- 2 methodology reference entities;
- source, mapping and art-direction Task Views.

Wave 1 must be independently useful for image redesign before later narrative adapters exist.

### Wave 2 — Full Hero source context

Import all relevant Hero.xlsx fields, including descriptions, stats, skills, ParentId, story/skin/route values and full source provenance. Reconcile the Wave 1 reduced registry without changing entity IDs.

### Wave 3 — Faction, map, relation and property context

Add bounded adapters for Birth, Map, Relation and Property. Create normalized reference entities only when exact IDs are available; otherwise preserve source text.

### Wave 4 — Event and narrative evidence

Link Event, EventResult and selected EventDialog evidence. Large dialogue text is not copied wholesale without a retrieval need and explicit source-row identity. Static links do not prove runtime reachability.

### Wave 5 — Curated art-direction and collision workflow

Human-reviewed identity sheets, visual collision groups, positive anchors and Exposure–Tension controls. Analytical suggestions remain proposals until applied by an authorized curator.

## 10. Import planning and conflict policy

Commands:

```text
python cli.py init
python cli.py plan --build 25006280
python cli.py bootstrap --build 25006280
python cli.py stats
python cli.py search <query>
python cli.py show <entity-id>
```

`plan` is read-only. `bootstrap` recomputes the same plan and applies it in one SQLite transaction only when:

- every source path/hash/schema/count is valid;
- schema and Task Views match the project contract;
- the Build snapshot is new, or every owned field is unchanged;
- no expected existing source record is missing;
- the unrelated dirty SEDB state is unchanged.

Any `source_conflict`, `missing_from_source`, `schema_conflict`, cross-Build identity conflict or readback failure blocks all writes for that invocation.

The importer compares only project-owned source/derived fields. Curated and proposal fields never turn a stable source bootstrap into a conflict.

## 11. Search and local use

The project provides domain-focused commands rather than requiring raw SEDB UI knowledge:

- search by simplified/traditional name, Hero ID, title, faction, asset path or description;
- show one identity with all current Build forms and assets;
- list unresolved forms/assets;
- list redesign queue and collision groups;
- open the local SEDB browser with documented `PYTHONPATH`.

No cloud service, account system or website integration is added.

## 12. Test and acceptance boundaries

Required tests:

- source hash/schema/count validation;
- stable entity IDs and exact-name provisional grouping;
- duplicate-name non-merging safeguards;
- same-Build no-op and conflict behavior;
- new-Build immutable snapshot behavior;
- exact visual-path and ambiguous-candidate separation;
- curated/proposal field preservation during rebootstrap;
- methodology-reference hashes;
- whole-batch rollback and SQLite integrity;
- Task View schema conflicts;
- UTF-8 Windows CLI behavior;
- real BuildID `25006280` acceptance;
- all inherited SEDB `current/` tests;
- before/after fingerprint of the existing untracked brief;
- changed-file list limited to the approved new project and design/plan artifacts.

Wave 1 acceptance requires deterministic counts, second-run `no_op`, database readback, `PRAGMA integrity_check=ok`, no source changes and no SEDB core changes.

## 13. Non-goals

- No automatic image generation or editing.
- No runtime game observation.
- No Steam/Workshop modification.
- No replacement of extracted-art manifests.
- No full EventDialog prose duplication in Wave 1.
- No autonomous identity merge/split.
- No automatic canonical write from similarity analysis or AI.
- No SEDB core refactor, commercial packaging or repository cleanup.
- No push, publication, deployment or release.

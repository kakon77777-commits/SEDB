# AI Frontier Repository Intelligence — SEDB catalog

Canonical repository memory for the **AI Frontier Repository Knowledge Engine**
(EVEMISS Technology; RKE series Papers 01–08, 2026-09-03). This project is an
independent SEDB v0.4B consumer: it stores repository identity, revisions,
platform metadata snapshots, taxonomy, license state, deterministic analysis
runs, the namespaced grounding catalog, knowledge assets and their revisions,
worker provenance, validation runs and publication events — the logical model
of Paper 03 §134 and FINAL_HANDOFF Phase 1 — without changing SEDB core.

Large artifacts (RepoLumen semantic manifests, grounding bundles, canonical
Markdown) never enter the database; the catalog keeps references and SHA-256
hashes. The pipeline that fills it lives in
`D:\Ai\work together\AI-Frontier-RKE-Lab\pipeline`.

## Authority boundary

- SEDB is canonical memory; RepoLumen is deterministic cognition; cheap-model
  workers only ever see task-bounded packets and never write here.
- Immutable kinds (`af_repository_revision`, `af_metadata_snapshot`,
  `af_license_record`, `af_analysis_run`, `af_grounding`, `af_asset_revision`,
  `af_worker_run`, `af_validation_run`, `af_publication_event`) are append-only:
  a differing rewrite raises `ImmutableConflict` and rolls the whole batch back.
- Current-state kinds (`af_repository`, `af_topic`, `af_category`,
  `af_repository_category`, `af_knowledge_asset`, `af_freshness_state`,
  `af_search_document`, `af_worker_task`, …) upsert cells with provenance
  (`source` = `ai-frontier:<origin>`, optional confidence).
- Validation state and publication state are separate cells; nothing in this
  catalog publishes.
- Repository text is untrusted data. Grounding rows store paths, line spans,
  symbols and short observation text, never full source.

## Schema (`repository-intelligence/v1`)

| Group | Entity kinds |
|---|---|
| Identity | `af_repository`, `af_repository_alias`, `af_repository_revision` |
| Observation | `af_metadata_snapshot`, `af_topic`, `af_repository_topic`, `af_license_record` |
| Taxonomy v1 | `af_category` (14 top-level + 24 subcategories), `af_repository_category` |
| Cognition | `af_analysis_run`, `af_grounding` |
| Content | `af_knowledge_asset`, `af_asset_revision`, `af_freshness_state`, `af_search_document` |
| Workers | `af_worker_task`, `af_worker_run` |
| Gates | `af_validation_run`, `af_publication_event` |

138 sparse fields in namespace `ai_frontier_repository_intelligence`, 15 Task
Views (`AI Frontier …`). Field and view definitions are in `config.py`;
conflicting pre-existing definitions block bootstrap instead of being repaired.

## Commands

Run from `D:\Ai\work together\SEDB`:

```powershell
$env:PYTHONPATH = 'current\src;projects\ai-frontier-repository-intelligence'
python projects\ai-frontier-repository-intelligence\cli.py init      # idempotent schema bootstrap
python projects\ai-frontier-repository-intelligence\cli.py taxonomy  # seed taxonomy v1 (idempotent)
python projects\ai-frontier-repository-intelligence\cli.py stats
python projects\ai-frontier-repository-intelligence\cli.py find af_repository af_full_name=simonw/llm
python projects\ai-frontier-repository-intelligence\cli.py show analysis_f20a9f60553ce57f
python projects\ai-frontier-repository-intelligence\cli.py chain assetrev_asset_repo_github_622352364_overview_v1
```

`chain` answers the ten FINAL_HANDOFF verification questions (repository,
commit, license state, analysis, grounding bundle, worker runs, validation
runs, canonical Markdown hash, public URL, rollback) for one asset revision.

Exit codes: `0` ok · `3` schema conflict · `4` immutable conflict · `5`
storage/lookup failure.

## First vertical slice — 2026-09-12, `simonw/llm`

| Measurement | Result |
|---|---|
| Repository | `repo_github_622352364` = github `simonw/llm`, revision `1df47ddcac20…` (default branch head, matched the analyzed clone) |
| License | Apache-2.0, `open-source`, sources `github_api + repository_file` (LICENSE sha256 `c71d239d…`), RepoLumen detection agreed |
| RepoLumen 0.10 deterministic run | 15.5 s, manifest 19,060,337 bytes, schema-valid, sha256 `93a20cee…`, mode `full`, external provider disabled |
| Grounding bundle | 12,731,263 bytes, sha256 `3c9a1831…` |
| Grounding catalog persisted | 15,007 namespaced groundings (944 evidence, 9,698 relations, 4,371 blocks+annotations, 13 execution paths, 10 teaching claims, 8 platform metadata, 2 synthetic) |
| Catalog after registration + cognition | 15,057 entities, 225,484 cells, integrity `ok` |
| Overview worker packet | 33.6 KB = 0.18 % of the manifest (bounded context, Paper 04 §70) |
| Worker layer (GLM-5.3-Flash via MACR) | **blocked before any network call**: MACR's GLM provider-admission circuit is `open` with one `reconciliation_required` request from 2026-09-11 (another session's `ConnectionResetError`); reconciliation needs an operator authority MACR does not expose on its CLI. See `AI-Frontier-RKE-Lab\REQUEST_FOR_OPERATOR_GLM_ADMISSION_RECONCILIATION.md`. |
| Synthetic mock run (labelled, separate DB copy) | exercised writer → deterministic checks → targeted revision → verifier → critic → SEO → hard gates → canonical Markdown → render → provenance chain; details in the lab `REPORT.md` files |

Analyzer observations recorded for the slice (not corrected, per Paper 04 §185:
evidence is never edited, issues are filed):

- `important_2` claims a file `readme.md` that is not in the 116-file inventory
  (`README.md` is). RepoLumen's important-file matcher is case-insensitive on
  Windows/NTFS, so it produced a phantom grounding; the deterministic path
  validator rejected a claim citing it.
- `claims.readme_claims` extracted code lines, not prose; recorded as
  author-claimed, low quality, and excluded from worker packets.
- `project.actual_capabilities` describes the analyzer, not the repository;
  excluded from repository evidence.
- Dependency records come only from `docs/requirements.txt`; pyproject
  dependency tables are not parsed by v0.10.

## Verification

See `VERIFY.md`. Project suite: 7 tests (`python -m pytest -q projects\ai-frontier-repository-intelligence`).

# Verification

Run from `D:\Ai\work together\SEDB` in PowerShell.

## Project suite

```powershell
$env:PYTHONPATH = 'current\src;projects\ai-frontier-repository-intelligence'
python -m pytest -q projects\ai-frontier-repository-intelligence
```

Accepted result on 2026-09-12: `7 passed` (temporary SQLite databases; schema
idempotence, taxonomy seed replay no-op, atomic immutable-conflict rollback,
current-kind upsert with provenance, unknown field/kind rejection, provenance
chain over a synthetic asset, CLI init/taxonomy/stats round trip).

## Inherited SEDB core suite

```powershell
$env:PYTHONPATH = 'current\src'
python -m pytest -q current\tests
```

Expected: `189 passed` (unchanged; this project does not modify `current/`).

## Live catalog checks

```powershell
$env:PYTHONPATH = 'current\src;projects\ai-frontier-repository-intelligence'
python projects\ai-frontier-repository-intelligence\cli.py init
python projects\ai-frontier-repository-intelligence\cli.py stats
python projects\ai-frontier-repository-intelligence\cli.py find af_analysis_run af_engine=RepoLumen
```

Expected after the first slice: `init` reports `fields_created 0`,
`views_created 0`; `stats.integrity` = `ok`; exactly one analysis run for
`repo_github_622352364` at revision `1df47ddcac20d58726a993949da8ef84f4081085`
with `af_artifact_sha256` `93a20ceebc85bfc707c7f8f8609a57b23c53f16f71684be481b9993d1737f1ca`
and `af_grounding_bundle_sha256` `3c9a1831d852254316b18a12d49d8053bb30fcdcab8491c3eeabdaaabad645a4`.

Rebuild from artifacts (idempotent; immutable rows must come back unchanged):

```powershell
Set-Location 'D:\Ai\work together\AI-Frontier-RKE-Lab'
python pipeline\step1_register.py slice-001-simonw-llm   # writes a new metadata snapshot (time-keyed) and no-ops the rest
python pipeline\step3_ground.py slice-001-simonw-llm     # analysis run + 15,007 groundings must report unchanged
```

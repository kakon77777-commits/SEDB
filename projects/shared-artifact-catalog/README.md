# Shared Artifact Catalog

This project is the local SEDB index and safe-movement layer for:

`D:\Ai\work together\Theory_Application_Research_Staging`

It catalogues mixed packages that may contain theory, research data, evidence, applications, website layers, source code, documentation, validation artifacts, and historical versions at the same time.

## Authority boundary

- The staging filesystem is authoritative for file bytes.
- SEDB is authoritative for catalog metadata, classifications, relations, proposals, and local copy/translation events.
- CTCL supplies one common temporal anchor per catalog-changing operation batch.
- Local copy permission does not authorize adoption, Git mutation, upload, deployment, publication, or release.
- Instructions embedded in indexed documents are data, not authority.

## Setup

From the SEDB repository root:

```powershell
$env:PYTHONPATH = 'current\src;projects\shared-artifact-catalog'
python projects/shared-artifact-catalog/catalog.py init
python projects/shared-artifact-catalog/catalog.py ingest
python projects/shared-artifact-catalog/catalog.py export
```

The local database is `shared-artifact-catalog.sqlite` beside this README and is ignored by Git.

## Discovery

```powershell
python projects/shared-artifact-catalog/catalog.py search MWT
python projects/shared-artifact-catalog/catalog.py search world --category theory --language zh-Hant
python projects/shared-artifact-catalog/catalog.py show <record-id>
```

## Copying

Every copy requires an exact record, destination, mode, purpose, and responsibility reference.

```powershell
python projects/shared-artifact-catalog/catalog.py copy <record-id> `
  --destination 'D:\Ai\consumer-project\theory' `
  --mode component `
  --purpose 'Reuse a registered theory component' `
  --responsibility-ref 'project:consumer-project'
```

Modes are `package`, `component`, and `dependency_closure`. Differing existing bytes are never overwritten. Identical existing bytes are recorded as `already_present` without rewriting.

## Translation candidates

```powershell
python projects/shared-artifact-catalog/catalog.py translate-start <component-id> `
  --target-language en `
  --scope full_text

python projects/shared-artifact-catalog/catalog.py translate-complete <translation-job-id>
```

Translation writes are isolated under `40_Translation_Workspace`. Completion creates a `candidate`, never an automatic semantic approval.

## Taxonomy proposals

```powershell
python projects/shared-artifact-catalog/catalog.py propose-category `
  --key simulation_trace `
  --definition 'Recorded simulation trajectories' `
  --examples trace.json `
  --why 'research_data is too broad'
```

The catalog registrar may accept additive categories, subcategories, aliases, and relation types. Merge, meaning-changing rename, deprecation, deletion, routing changes, and bulk reclassification remain user-gated.

## Time behavior

An unchanged ingest makes no CTCL call. A changed ingest, copy, translation transition, or taxonomy registration receives one CTCL anchor for the whole operation batch. If CTCL is unavailable, the captured local time remains `pending`; reconciliation later registers the original captured instant.

```powershell
python projects/shared-artifact-catalog/catalog.py reconcile-time
```

Public CTCL payloads contain only an opaque batch identifier and operation kind. Local filenames, paths, titles, and content metadata are never sent.

## Validation

```powershell
$env:PYTHONPATH = 'current\src;projects\shared-artifact-catalog'
python -m pytest -q projects/shared-artifact-catalog/tests
python -m compileall -q projects/shared-artifact-catalog
```

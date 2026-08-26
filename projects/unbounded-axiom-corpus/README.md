# Unbounded Axiom Corpus SEDB MVP

This project imports published paper metadata from
`D:\Ai\work together\unbounded-axiom\registry\papers.json` into one
cumulative, local, Git-ignored SEDB SQLite database.

## Authority boundary

- The Unbounded Axiom registry is the read-only metadata source of truth.
- This SQLite database is a local SEDB projection, not a publication source.
- The importer never scans paper files, recomputes hashes, edits the corpus,
  deploys, publishes, registers CTCL instants, or calls an AI provider.
- Any `conflict` or `missing_from_source` blocks the complete month write.
- A bootstrap run never overwrites, deletes, moves, or re-identifies a paper.
- Only the 11 MVP metadata fields participate in equality checks; later
  AI-governed fields do not change bootstrap results.

## Setup

From `D:\Ai\work together\SEDB`:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python projects/unbounded-axiom-corpus/cli.py init
```

The default database is:

```text
projects\unbounded-axiom-corpus\unbounded-axiom-corpus.sqlite
```

It and its SQLite sidecars are ignored by Git.

## Import one month

```powershell
python projects/unbounded-axiom-corpus/cli.py bootstrap --month 2026-04
```

Run the same command again. A stable month returns `status: no_op`, `new: 0`,
and the full selected count as `unchanged`.

A syntactically valid month containing no papers is an error, not a successful
zero-count import.

## Statistics

```powershell
python projects/unbounded-axiom-corpus/cli.py stats
```

## Explicit path overrides

Tests and controlled acceptance runs can supply source and database paths:

```powershell
python projects/unbounded-axiom-corpus/cli.py `
  --source 'D:\Ai\work together\unbounded-axiom\registry\papers.json' `
  --db 'projects\unbounded-axiom-corpus\acceptance-2026-04.sqlite' `
  bootstrap --month 2026-04
```

## Exit codes

- `0`: successful init, import, no-op, or stats
- `1`: unexpected exception
- `2`: configuration, source, or month validation error
- `3`: SEDB schema conflict
- `4`: source difference blocked the batch
- `5`: SQLite write, readback, or integrity failure

Every command result is one deterministic JSON document on stdout.

## Tests

Ordinary tests use temporary registries and databases:

```powershell
$env:PYTHONPATH = 'current\src;projects\unbounded-axiom-corpus'
python -m pytest -q projects/unbounded-axiom-corpus/tests
```

The real-registry acceptance is opt-in and still writes only to a pytest
temporary database:

```powershell
$env:SEDB_RUN_LIVE_ACCEPTANCE = '1'
try {
  python -m pytest -q `
    projects/unbounded-axiom-corpus/tests/test_live_acceptance.py
} finally {
  Remove-Item Env:SEDB_RUN_LIVE_ACCEPTANCE -ErrorAction SilentlyContinue
}
```

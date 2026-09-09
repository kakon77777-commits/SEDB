# Verification

Run from `D:\Ai\work together\SEDB` in PowerShell 7.6.

## Project suite and pinned live acceptance

```powershell
$env:PYTHONPATH = 'current\src;projects\fromjianghu-static-catalog'
$env:SEDB_RUN_FROMJIANGHU_ACCEPTANCE = '1'
try {
  python -m pytest -q projects\fromjianghu-static-catalog
} finally {
  Remove-Item Env:SEDB_RUN_FROMJIANGHU_ACCEPTANCE -ErrorAction SilentlyContinue
}
```

Accepted result: `13 passed`.

The suite exercises real temporary SQLite databases and covers:

- exact eight-kind source classification and stable record identity;
- source SHA-256 drift and duplicate source-ID rejection;
- 92-field/eight-view schema idempotence;
- read-only plan rejection of conflicting SEDB field definitions;
- source-owned record conflict blocking;
- injected cell-write rollback;
- bootstrap/no-op replay and classification queries;
- CP950-to-UTF-8 CLI output regression;
- a full 6,979-entity / 142,562-cell rebuild from the pinned live source.

## Inherited SEDB core suite

```powershell
$env:PYTHONPATH = 'current\src'
python -m pytest -q current\tests
```

Accepted result: `189 passed`.

## Local database checks

```powershell
$env:PYTHONPATH = 'current\src;projects\fromjianghu-static-catalog'
python projects\fromjianghu-static-catalog\cli.py plan
python projects\fromjianghu-static-catalog\cli.py bootstrap
python projects\fromjianghu-static-catalog\cli.py stats
python projects\fromjianghu-static-catalog\cli.py classify
python projects\fromjianghu-static-catalog\cli.py search FJ-021 --limit 10
```

Required gates:

- plan: `new=0`, `unchanged=6979`, conflicts/missing `0`,
  `write_performed=false`;
- bootstrap: `status=no_op`, created entities/cells `0`;
- stats: 6,979 entities, 142,562 cells, 92 fields, eight views;
- SQLite `PRAGMA integrity_check`: `ok`;
- query: `FJ-021`, claim status
  `observed with causal static explanation`, runtime `not_started`;
- checkpointed SQLite SHA-256:
  `bbdcc91bd8cbb20be5d297400bdea97f6ff32935b196b8cfbc72c350328194b7`.

The ignored SQLite file is local evidence, not a release artifact. Recompute
its hash after any authorized source-contract version or schema change rather
than treating this historical hash as permanently current.

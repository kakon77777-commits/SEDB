# Wanxiang Character Canon SEDB

This is an independent, local SEDB consumer for the preserved Wanxiang
Qunxia Zhuan research snapshot. Wave 1 creates a queryable character and visual
asset canon without changing the game, Steam/Workshop state, extracted PNGs,
methodology papers, or SEDB `current`.

## Authority boundary

- Source access is one-way and read-only from
  `D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research`.
- The default source snapshot is Steam BuildID `25006280`.
- Generated SQLite databases and caches stay local and are Git-ignored.
- Importer-owned facts are immutable within a Build. Same-Build drift blocks
  the complete batch; curated and proposal fields are not overwritten.
- No runtime launch, asset replacement, image generation, publishing, push,
  deployment, or release is part of this project.

## Wave 1 topology

| Entity kind | Expected count |
| --- | ---: |
| `wanxiang_build_snapshot` | 1 |
| `wanxiang_character_identity` | 165 |
| `wanxiang_character_form_snapshot` | 228 |
| `wanxiang_visual_asset_snapshot` | 1,391 |
| `wanxiang_visual_candidate_snapshot` | 172 |
| `wanxiang_source_gap_snapshot` | 8 |
| `wanxiang_methodology_reference` | 2 |
| **Total** | **1,967** |

Cross-Build character identity is separate from Build-scoped Hero forms.
Exact ResourceManager assets are separate from ambiguous decoded candidates.
The two preserved methodology papers are references, not executable project
instructions or automatically adopted art policy.

## Local setup and commands

From the SEDB repository root in PowerShell:

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python -m pytest -q projects\wanxiang-character-canon\tests
python projects\wanxiang-character-canon\cli.py plan --build 25006280
python projects\wanxiang-character-canon\cli.py bootstrap --build 25006280
python projects\wanxiang-character-canon\cli.py stats
python projects\wanxiang-character-canon\cli.py search 万轻舟
python projects\wanxiang-character-canon\cli.py show wx-char-IDENTIFIER
python projects\wanxiang-character-canon\cli.py unresolved
python projects\wanxiang-character-canon\cli.py catalog-plan --build 25006280
python projects\wanxiang-character-canon\cli.py catalog-bootstrap --build 25006280
python projects\wanxiang-character-canon\cli.py table EventDialog --id 10
python projects\wanxiang-character-canon\cli.py dialog 10
python projects\wanxiang-character-canon\cli.py edges ENTITY_ID --direction both
python projects\wanxiang-character-canon\cli.py route 1
python projects\wanxiang-character-canon\cli.py gameplay-report all
```

`plan` is read-only. `bootstrap` must recompute the complete plan and applies
only an unblocked batch in one transaction. Every command writes one UTF-8 JSON
object to stdout. Exit codes are `0` for success/no-op/read-only queries, `2`
for source or usage rejection, `3` for schema/source conflicts, and `4` for
storage, readback, integrity, or lookup failures.

`catalog-plan` composes the 29,939-row AllExcel catalog and 40,075 static
reference edges without creating entities. `catalog-bootstrap` reloads the
sources, verifies the same fingerprint, makes a recoverable local Wave 1 backup
when expanding an existing Wave 1 database, and then inserts new entities and
missing cells atomically. List commands are compact; `show` and `dialog` return
the complete stored payload explicitly.

## Measured Wave 1 acceptance (2026-08-30)

The default local database was built from Steam BuildID `25006280` and remains
Git-ignored at `projects/wanxiang-character-canon/wanxiang-character-canon.sqlite`.

| Measurement | Accepted result |
| --- | ---: |
| Registered fields | 118 |
| Task Views | 9 |
| Entities | 1,967 |
| Source-owned cells | 39,600 |
| First bootstrap | 1,967 entities created |
| Immediate second bootstrap | no-op, 1,967 unchanged |
| Plan conflicts / missing | 0 / 0 |
| SQLite integrity | `ok` |
| Live acceptance | 1 passed |
| Source tree before/after | 4,169 files / 3,612,075,730 bytes, unchanged |

The accepted per-kind counts are the Wave 1 topology in the table above. The
source fingerprint is
`E9479199871688AD2C24F3F3A7336FB550FFDACB6D73A7CD4F4270FDDCB1C075`.
The local SQLite file measured 14,749,696 bytes with SHA-256
`6843DB0E16DB57E8E110A04DABC5F95F37817A6E34C2527F2F463A8DFACF1F3B`
after the accepted no-op rerun. This accepts only the Wave 1 character/art
foundation. The full-catalog implementation is present, but this table and hash
describe the preserved pre-catalog baseline; the current accepted database is
the full static catalog below.

## Measured full static catalog acceptance (2026-08-30)

| Measurement | Accepted result |
| --- | ---: |
| AllExcel tables / rows | 36 / 29,939 |
| EventDialog rows | 17,210 |
| Pre-edge entities | 31,678 |
| Reference edges | 40,075 |
| Resolved / missing edges | 31,117 / 8,958 |
| Total entities | 71,753 |
| Total cells | 1,102,664 |
| Registered fields / views | 174 / 19 |
| First catalog apply | 69,786 new / 229 enriched |
| Immediate replay | 71,753 unchanged, no-op |
| SQLite integrity | `ok` |

The accepted catalog fingerprint is
`CD59082E7C2D92F0296EA5DCB91F33270470366DCD6A31F2BDD632A3A0A955FE`.
The ignored database measures 399,114,240 bytes with SHA-256
`3426A60131652D4797BF0A44A124B4CF74587A0645CF6E11C6598D3CD1E08B49`.

The recoverable ignored Wave 1 backup is
`local-backups/wave1-25006280.sqlite`, SHA-256
`5403E4AA92D36C92ED7D04CD17AD1A56DC0BCB547D5E32C412A6E6986C7E3862`.
Static reference edges do not prove runtime reachability, and this acceptance
does not by itself accept runtime behavior or player experience.

## Static gameplay reports

`gameplay-report all` verifies the accepted database SHA-256, SQLite integrity,
catalog fingerprint, exact source-table counts and reference-rule version before
writing anything. It then atomically writes six JSON reports, six Markdown
reports and `manifest.json` under
`analysis\sedb-wave2-4` in the research root. A second run is deterministic.

The six analyses cover character/art coverage, the authored event graph,
choice/consequence, time/pacing fields, relationship routes, and
combat/progression. Every report separates `OBSERVED`, `INFERRED`, `UNKNOWN`
and `FALSIFYING_TEST`; static graph findings are never upgraded to runtime
reachability or gameplay-fun claims. Machine acceptance evidence is in
`evidence/gameplay-analysis-acceptance.json`. The final AI context index remains
the next gate.

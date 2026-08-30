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
```

`plan` is read-only. `bootstrap` must recompute the complete plan and applies
only an unblocked batch in one transaction. Every command writes one UTF-8 JSON
object to stdout. Exit codes are `0` for success/no-op/read-only queries, `2`
for source or usage rejection, `3` for schema/source conflicts, and `4` for
storage, readback, integrity, or lookup failures.

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
foundation; the narrative and context work described as Waves 2–5 remains
unimplemented.

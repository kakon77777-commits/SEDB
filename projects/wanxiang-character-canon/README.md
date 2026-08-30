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
```

`plan` is read-only. `bootstrap` must recompute the complete plan and applies
only an unblocked batch in one transaction. CLI implementation follows in the
later Wave 1 tasks.

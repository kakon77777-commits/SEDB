# Wanxiang Character Canon SEDB — Verification

Status: `WANXIANG_FULL_STATIC_CANON_PASS`

The current local database accepts the complete 36-table, 29,939-row frozen
AllExcel projection and its explicit v1 reference graph for BuildID `25006280`.
It remains a static documented-data result, not runtime or gameplay-fun
acceptance.

## Final full-static acceptance

| Gate | Fresh result |
| --- | --- |
| Wanxiang project suite with all live gates | 106 passed / 0 failed (217.15s) |
| Inherited SEDB suite | 189 passed / 0 failed (53.64s) |
| Python compile gate | exit 0 |
| Full catalog replay | 71,753 unchanged; bootstrap `no_op` |
| Wave 1 replay | 1,967 unchanged; bootstrap `no_op` |
| Gameplay report replay | 12 / 12 hashes identical |
| Context validation | 30 links / 0 failures / 6 reports |
| Research/game/Workshop preservation | exact before/after metadata signatures |
| SEDB `current/` diff | 0 |
| Installed game / Workshop writes | 0 / 0 |

The canonical human handoff is
`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\AI_CONTEXT_INDEX.md`.
The machine index is `analysis\sedb-wave2-4\context-index.json`; the SEDB-side
`AI_CONTEXT_INDEX.md` is intentionally only a discovery pointer. Machine final
evidence is
[`evidence/full-static-verification.json`](evidence/full-static-verification.json).

`WANXIANG_FULL_STATIC_CANON_PASS` accepts only the frozen static canon, explicit
reference graph, six static gameplay analyses, and context handoff. It does not
accept runtime reachability, balance, player fun, live MOD loading, or an art
replacement set.

## Static gameplay report result

| Gate | Accepted result |
| --- | --- |
| Verified report input | accepted DB SHA, integrity, catalog/table counts and v1 rules |
| Outputs | 6 JSON + 6 Markdown + 1 manifest |
| Deterministic replay | all 12 report hashes identical |
| Independent metric reconciliation | 6 / 6 |
| Claim classes | `OBSERVED`, `INFERRED`, `UNKNOWN`, `FALSIFYING_TEST` in every report |
| Atomic-write residue | 0 temporary files |
| Manifest SHA-256 | `F78F8ED32EAF9332F9FF4314C606206A5FD777257B6F7825A69270B006D803D0` |
| Immutable source projection | 4,171 files / 3,612,083,998 bytes, unchanged |

The canonical output directory is
`D:\AI_RESIDENCE\AI_gamedesign\Wanxiang-Qunxia-Zhuan-research\analysis\sedb-wave2-4`.
Machine evidence is
[`evidence/gameplay-analysis-acceptance.json`](evidence/gameplay-analysis-acceptance.json).
The final `WANXIANG_FULL_STATIC_CANON_PASS` status remains gated on the AI
context index and fresh complete verification.

## Full static database result

| Gate | Accepted result |
| --- | --- |
| Pre-edge entity base | 31,678 |
| Reference graph | 40,075 edges: 31,117 resolved / 8,958 missing |
| Full database | 71,753 entities / 1,102,664 cells |
| Schema | 174 fields / 19 Task Views |
| First apply | 69,786 new entities / 229 enriched entities |
| Exact replay | 0 new / 0 enrich / 71,753 unchanged |
| Source rows | 29,939 represented exactly once |
| EventDialog | 17,210 complete row payloads |
| SQLite integrity | `ok` |
| Default DB SHA-256 | `3426A60131652D4797BF0A44A124B4CF74587A0645CF6E11C6598D3CD1E08B49` |
| Wave 1 backup SHA-256 | `5403E4AA92D36C92ED7D04CD17AD1A56DC0BCB547D5E32C412A6E6986C7E3862` |
| Full-catalog live test | 1 passed (146.69s) |
| Inherited SEDB suite | 189 passed (86.01s) |

Catalog fingerprint:
`CD59082E7C2D92F0296EA5DCB91F33270470366DCD6A31F2BDD632A3A0A955FE`.

Machine evidence:
[`evidence/full-catalog-acceptance.json`](evidence/full-catalog-acceptance.json)
and [`evidence/wave1-backup-manifest.json`](evidence/wave1-backup-manifest.json).

## Historical Wave 1 verification

Status: `WANXIANG_CANON_WAVE1_PASS`

This status accepts only the local Wave 1 character/art foundation for Steam
BuildID `25006280`. It does not accept gameplay redesign, game runtime behavior,
Workshop loading, image quality, or the planned narrative/context waves.

## Accepted result

| Gate | Fresh result |
| --- | --- |
| Project suite with live acceptance | 40 passed, 0 failed (20.08s) |
| Inherited SEDB suite | 189 passed, 0 failed (47.18s) |
| Python compile gate | exit 0 |
| Source selection | 1,967 entities, exact topology |
| First real bootstrap | 1,967 entities / 39,600 cells created |
| Fresh plan | 0 new / 1,967 unchanged / 0 conflict / 0 missing |
| Fresh bootstrap replay | `no_op`, 0 entities / 0 cells created |
| SEDB schema | 118 fields / 9 Task Views |
| SQLite integrity | `ok` |
| Research-tree preservation | exact path/length/mtime signature match |
| Consumed source hashes | 13/13 unchanged |
| `current/` diff | 0 files |
| Changed files outside approved scope | 0 files |

The accepted source fingerprint is
`E9479199871688AD2C24F3F3A7336FB550FFDACB6D73A7CD4F4270FDDCB1C075`.
The ignored local database is
`D:\Ai\work together\SEDB\projects\wanxiang-character-canon\wanxiang-character-canon.sqlite`.
After the no-op replay it measured 14,749,696 bytes with SHA-256
`6843DB0E16DB57E8E110A04DABC5F95F37817A6E34C2527F2F463A8DFACF1F3B`.

## Preservation and scope

The read-only research root remained at 4,169 files and 3,612,075,730 bytes.
Its complete path/length/mtime projection remained
`0745D89D1496EDCCA7491887B8C679E68708D1C5AAA9E4C466A198B59A0A6312`
before and after the final selection/plan/bootstrap/stats replay. Every consumed
JSON, checkpoint, validation manifest, and methodology paper also retained its
SHA-256.

The unrelated untracked brief remains outside this project at 6,850 bytes and
SHA-256
`30EF85D849D6FE6F711AB0C1FC39953B03DB3C4B8DD939501C21E7B76A64DF1F`.
SEDB `current/`, existing projects, the game, Steam, Workshop, extracted PNGs,
and methodology papers were not modified.

## Reproduction

From `D:\Ai\work together\SEDB` in PowerShell:

```powershell
$env:PYTHONPATH = 'current\src;projects\wanxiang-character-canon'
python projects\wanxiang-character-canon\cli.py plan --build 25006280
python projects\wanxiang-character-canon\cli.py bootstrap --build 25006280
python projects\wanxiang-character-canon\cli.py stats
python projects\wanxiang-character-canon\cli.py search 万轻舟
python projects\wanxiang-character-canon\cli.py unresolved

$env:WANXIANG_CANON_LIVE = '1'
python -m pytest -q projects\wanxiang-character-canon\tests
```

Use `show ENTITY_ID` for full sparse cells and their source provenance; listing
commands intentionally return compact locator summaries.

## Not measured

- Gameplay balance, runtime state transitions, route reachability, and actual
  player experience.
- Runtime mod loading or any Steam/Workshop mutation.
- Runtime parity of the complete static catalog against packaged DAT data.
- Cross-Build reconciliation after a future game update.
- Visual-redesign quality or acceptance of generated/edited images.
- Independent rereading of PNG bytes; Wave 1 consumes the validated output
  manifest projection.
- A content hash of every byte in the 3.6 GB research tree. The preservation
  gate combines a full metadata signature with hashes of all 13 consumed files.
- Push, PR, release, publication, deployment, or external-provider behavior.

The machine-readable evidence is
[`evidence/wave1-verification.json`](evidence/wave1-verification.json).

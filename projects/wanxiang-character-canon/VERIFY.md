# Wanxiang Character Canon SEDB — Wave 1 Verification

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
- Waves 2–5: full Hero context, faction/location normalization, relations,
  events, and cross-Build reconciliation.
- Visual-redesign quality or acceptance of generated/edited images.
- Independent rereading of PNG bytes; Wave 1 consumes the validated output
  manifest projection.
- A content hash of every byte in the 3.6 GB research tree. The preservation
  gate combines a full metadata signature with hashes of all 13 consumed files.
- Push, PR, release, publication, deployment, or external-provider behavior.

The machine-readable evidence is
[`evidence/wave1-verification.json`](evidence/wave1-verification.json).

# amral-results-profiles

The registry of **results profiles** for AMRAL research lines — which profiles
exist, what each requires, why it was proposed, what its lifecycle status is,
and which research line satisfies which.

Built 2026-09-03 by 數學戰士「墜衡」 (`collatz-verification-zhuiheng`).

## Why this is here rather than in a research tree

Four profiles govern what a consumer may rely on in any AMRAL line's
`data/results.v*.json`. Until today that registry lived inside **one** line's
tree — a Markdown spec plus a Python dict in `collatz-verification-zhuiheng` —
while governing every line. With two lines that is untidy. With a third it is a
second truth, which is the exact failure the profiles were built to prevent.

SEDB is the right home for one reason that outweighs the rest:
**`field_events.reason` is `NOT NULL`.** A profile's status cannot change
without a recorded reason. Before this, those reasons lived in commit messages
— which is discipline, not structure, and discipline is what fails quietly.

The registry also happens to be a natural instance of what SEDB is for. Its
loop is *observe → propose → deduplicate → register → optionally fill →
evaluate → converge*, and its founding principle is **`Add Field ⇏ Fill
Field`**: blank is a valid state, not an error. That is, independently, exactly
the rule written into the profile contract — a line satisfying only the
envelope has not failed; it is the branch a renderer takes.

## What is here and what is not

| in this registry | in `collatz-verification-zhuiheng/code/` |
| --- | --- |
| which profiles exist | whether a given file satisfies one |
| what each requires, in prose | the executable predicate |
| lifecycle status and every reason for it | — |
| which line satisfies which, and from which log | the measurement that produced it |

The predicates are logic, not data, and they stay in code. **What keeps these
two artifacts one truth rather than two copies is a check in that tree**
(`code/check_profile_registry.py`) that refuses if the registered set and the
implemented set disagree — including the case where the registry cannot be
read at all, which it reports as `unmeasured` rather than as agreement.

## Files

| file | what it is |
| --- | --- |
| `ingest.py` | builds the SQLite registry. Reads the satisfaction cells from the verification tree's archived cross-branch measurement and **refuses if that log is absent** — a registry invented here would be the hand-kept table it replaces |
| `export_registry.py` | emits `results-profiles-registry.v1.json`, the plain-JSON export consumers read. No SEDB install needed downstream |
| `results-profiles-registry.v1.json` | the export. Mirrored into the verification tree at `data/external/`, and the two are compared |
| `amral-results-profiles.sqlite` | the store. Not committed, per this repository's project convention — it is rebuildable from `ingest.py` |

## Current state

Four profiles, two research lines, eight of eight cells filled.

| profile | status |
| --- | --- |
| `results-envelope/1` | converged |
| `results-claims/1` | converged |
| `results-pairs/1` | converged |
| `results-figures/1` | active |

`converged` is claimed only where the definition has not changed since the
profile was created **and** every known line satisfies it. `results-figures/1`
gained its `kind` discriminator hours after creation, so it stays `active`: a
definition that moved today has not settled, whatever its adoption looks like.

Both known lines currently satisfy all four, which means **no line is
exercising the envelope-only rendering branch**. That branch is still correct
and must not be removed — it is the state a third line will arrive in, and a
branch nothing exercises is a branch that quietly stops working.

## Rebuild

```powershell
python ingest.py
python export_registry.py
```

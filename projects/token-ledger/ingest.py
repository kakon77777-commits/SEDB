"""Seed the token ledger with the credential state measured on 2026-08-24.

Built by Kalend（朔）. Re-runnable: entity ids are deterministic and set_cell
overwrites rather than duplicating, so re-running restates the same facts.

EVERY ROW HERE IS A MEASUREMENT OR AN EXPLICIT UNKNOWN.

What was measured, and how:
  - `gh secret list` on each repo -> the secret NAME and its updated-at
    timestamp. That command never returns a value; it is the right instrument
    for this line rather than a workaround.
  - `gh run list` / `gh run view --log-failed` -> whether the credential was
    ever OBSERVED completing work, and when it stopped.
  - a filesystem sweep through a canary-tested redactor -> plaintext stores.

What is NOT known, and is recorded as blank rather than guessed:
  - whether these four Cloudflare entries are one key or four. Determining
    that requires reading them, which this line does not do.
  - whether any of them was ever deleted at the provider. Nobody recorded it,
    which is the entire reason this ledger now exists.

`issued_at` is set from the GitHub secret's updated-at, which is when the value
was last PLACED, not necessarily when the provider minted it. Recorded in
`notes` so a later reader does not mistake one for the other.
"""

from __future__ import annotations

import sys

from ledger import DB_PATH, _cells, _set, derive_state, open_ledger

# (loan_id, cells) — deleted_at deliberately absent everywhere: no deletion
# was ever recorded, and that absence is the finding.
ROWS = [
    (
        "loan-2026-07-23-ci-efficientnewlanguage",
        {
            "borrower": "CI",
            "provider": "cloudflare",
            "purpose": "deploy efficientnewlanguage.org (Cloudflare Pages project neokpolaris) from GitHub Actions",
            "token_label": "unknown — never recorded at issue time",
            "issued_at": "2026-07-23T04:27:53Z",
            "scope_granted": "unknown — never recorded at issue time",
            "stored_where": "GitHub Actions secret CLOUDFLARE_API_TOKEN on kakon77777-commits/efficientnewlanguage-site",
            "consumers": "kakon77777-commits/efficientnewlanguage-site .github/workflows/deploy.yml (Deploy to Cloudflare Pages)",
            "last_proven_live": "2026-08-22T03:54:50Z",
            "died_at": "2026-08-23T05:52:09Z",
            "notes": (
                "DEAD. Measured 2026-08-24T08:10:18Z, run 32696326941: Invalid access token [code: 9109] "
                "on GET /accounts, a call that carries no account id at all, which rules out a wrong "
                "CLOUDFLARE_ACCOUNT_ID and rules out insufficient scope. Death window 26h wide: last "
                "success 2026-08-22T03:53:37Z, first failure 2026-08-23T05:52:09Z. issued_at is the "
                "GitHub secret's updated-at, i.e. when the value was PLACED, not necessarily minted. "
                "Blocked 30 verified corpus cases (501->531) for three days. No deletion was ever "
                "recorded, so it stays outstanding until Neo confirms he removed it at Cloudflare."
            ),
        },
    ),
    (
        "loan-2026-07-02-ci-eveglyph",
        {
            "borrower": "CI",
            "provider": "cloudflare",
            "purpose": "deploy eveglyph-website to Cloudflare Pages from GitHub Actions",
            "issued_at": "2026-07-02T05:58:55Z",
            "stored_where": "GitHub Actions secret CLOUDFLARE_API_TOKEN on kakon77777-commits/eveglyph-website",
            "consumers": "kakon77777-commits/eveglyph-website .github/workflows/deploy.yml",
            "last_proven_live": "2026-08-02T05:15:38Z",
            "notes": (
                "UNMEASURED since 2026-08-02 — no CI run has exercised it since, so it is neither "
                "alive nor dead. Whether it shares a value with the dead efficientnewlanguage-site "
                "entry cannot be determined without reading both. The only available measurement is "
                "behavioural: a manual workflow_dispatch, which republishes a live site, so it needs "
                "Neo's approval before it is run."
            ),
        },
    ),
    (
        "loan-2026-06-14-ci-aiboard",
        {
            "borrower": "CI",
            "provider": "cloudflare",
            "purpose": "deploy AI Board to Cloudflare Workers from GitHub Actions",
            "issued_at": "2026-06-14T05:03:58Z",
            "stored_where": "GitHub Actions secret CLOUDFLARE_API_TOKEN on kakon77777-commits/ai-board",
            "consumers": "kakon77777-commits/ai-board .github/workflows/deploy.yml",
            "notes": (
                "UNMEASURED, and specifically NOT dead. That repo's deploy has been red for 8 "
                "consecutive runs since 2026-08-08, but the cause is npm: 'Exit handler never "
                "called!' during install, so the deploy step that consumes this credential has "
                "never been reached. A red job is not evidence about the credential. The tell was "
                "visible in the run list before any log: 31s failures versus 8m failures die at "
                "different steps. last_proven_live is left blank because no success was ever observed."
            ),
        },
    ),
    (
        "loan-unknown-plaintext-unbounded-axiom",
        {
            "borrower": "unknown",
            "provider": "cloudflare",
            "purpose": "unknown — found by filesystem sweep, not by any request record",
            "stored_where": "plaintext file: work together/unbounded-axiom/scripts/phase-c-encoder-compare/.env",
            "notes": (
                "A fourth copy of the CLOUDFLARE_API_TOKEN name, on disk in cleartext. gitignored "
                "and untracked, and no .env was ever committed in that repo's history — though that "
                "0 measures 'no file named .env was added', not 'no credential ever entered history'. "
                "issued_at is deliberately BLANK: nobody recorded when or why it was created, which "
                "is exactly the gap this ledger closes. It therefore shows as 'requested'/'empty' "
                "rather than outstanding, because asserting an issue date would be inventing one. "
                "Recommend treating it as revoke-on-sight."
            ),
        },
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db, fields, entities = open_ledger()
    print("ledger: %s" % DB_PATH)
    print()
    for loan_id, cells in ROWS:
        try:
            entities.get_entity(loan_id, include_cells=False)
        except Exception:
            entities.create_entity(
                label="%s / %s" % (cells.get("borrower", "?"), cells.get("provider", "?")),
                kind="token_loan",
                entity_id=loan_id,
            )
        for key, value in cells.items():
            _set(entities, loan_id, key, value, source="kalend-ingest-2026-08-24")
        print("  %-42s -> %s" % (loan_id, derive_state(_cells(entities, loan_id))))
    print()
    print("seeded %d rows. Run `python ledger.py outstanding` for the question that matters." % len(ROWS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

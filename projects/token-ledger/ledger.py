"""Token lending ledger — the registrar's book, built on SEDB.

Built 2026-08-24 by Kalend（朔）, the API/token stewardship line.

WHAT THIS IS
------------
Neo's actual workflow is a lending library, not an expiry calendar:

    an AI needs an API  ->  Neo generates a temporary token  ->  the AI uses it
    ->  the work completes  ->  Neo deletes the token.

Each token is temporary and typically unrestricted, and that is *safe only
because the deletion actually happens*. So the risk this book tracks is not
expiry. It is **an issued token nobody deleted**. One question matters more
than all the others:

    which tokens are still out there?      ->  `outstanding`

and, added 2026-08-25 after it was needed and missing:

    who is holding a value that just died? ->  `stale`

ROTATION IS A THIRD KIND OF ENDING
----------------------------------
`died_at` is a measurement (we watched the provider reject it). `deleted_at`
is an action (Neo removed it). `rotated_at` is neither: the credential keeps
its identity and its permissions, the console entry stays healthy, and every
stored COPY of the value dies instantly and silently.

That happened on 2026-08-24. Neo rotated a CI token right after a verified
deploy — correct by his own methodology — and nothing said out loud that the
repo secret was now holding a dead value. The next push failed 12h35m later
and two lines spent an hour deciding whether the token had expired. The answer
was knowable at rotation time by anyone who looked at the list of copies. So
now `rotate` prints that list.

TIERS, AND WHY THE AXIS IS NOT DURATION
---------------------------------------
The tier is decided by ONE question: is a human present when the credential is
USED? Attended means obtaining a new value and using it happen inside a single
span of human attention, so use-and-destroy is safe. Unattended means a
pipeline reads the stored value at a moment nobody chose, and — until the
provider can mint a credential at that moment, which Cloudflare cannot as of
2026-08-25 — the value must stand.

`check_lending_rules()` enforces the consequence: a T3_DISPOSABLE credential
cannot be registered as what an unattended consumer reads, because destroying
it breaks that consumer's next run. It validates BEFORE the first write; an
earlier version checked at the end and left half-written rows behind a message
that said REFUSED.

WHY STATE IS DERIVED AND NEVER STORED
-------------------------------------
Measured against a fresh SEDB database, 2026-08-24: `cells` holds exactly one
row per (entity, field) and `set_cell` OVERWRITES it. Three writes of a
`state` cell left one row, `"deleted"` — the two earlier transitions were gone.
A ledger whose whole purpose is history cannot keep its history in a cell.

Control run in the same probe: writes to *different* fields on the same entity
accumulate normally (2 fields -> 2 cells). So the usable shape is write-once
cells on separate fields.

Therefore each lifecycle moment gets its own write-once field —
`requested_at`, `issued_at`, `completed_at`, `died_at`, `deleted_at` — and the
state is a function of which are filled. Nothing is ever overwritten, so nothing is ever
lost, and blank is a legal state. That last part is SEDB's founding invariant:

    Add Field  =/=>  Fill Field

THE HARD BOUNDARY, ENFORCED IN CODE
-----------------------------------
This ledger records lifecycle, never content. It has never held a token value
and it is built so that it cannot: `_reject_secret_shaped` scans every value on
its way in and raises. The boundary is not left to the operator's discipline —
a credential pasted here fails loudly instead of being stored quietly.
Run `python ledger.py selftest` to see it refuse a planted canary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService

DB_PATH = Path(__file__).with_name("token-ledger.sqlite")

# --------------------------------------------------------------------------
# Schema. Every field is write-once by convention; the five *_at fields are
# the lifecycle and everything else is descriptive metadata about the loan.
#
# `died_at` and `deleted_at` are deliberately separate. One is a MEASUREMENT
# (we watched the provider reject it); the other is an ACTION Neo took. A
# credential can be dead and still sitting in the console as an uncleaned
# entry, and that combination is the one worth showing loudly.
# --------------------------------------------------------------------------

LIFECYCLE_FIELDS = ["requested_at", "issued_at", "completed_at", "rotated_at", "died_at", "deleted_at"]

FIELDS = [
    # --- lifecycle: write-once, state is derived from which of these are set
    ("requested_at", "Requested at", "text", "UTC ISO-8601. An AI asked for this credential."),
    ("issued_at", "Issued at", "text", "UTC ISO-8601. Neo generated it in the provider console."),
    ("completed_at", "Completed at", "text", "UTC ISO-8601. The borrower reported the work done."),
    ("died_at", "Died at", "text",
     "UTC ISO-8601 of the first OBSERVED rejection. A measurement, not a deletion — the entry may "
     "still exist at the provider. Bound it: put the last success and first failure in `notes`."),
    ("rotated_at", "Rotated at", "text",
     "UTC ISO-8601. The VALUE was replaced while the credential kept its identity. This is not a "
     "deletion and not a death: the console entry stays active and correctly scoped, and every stored "
     "copy silently becomes stale. Recording it is what turns a future 9109 into a known consequence "
     "instead of an investigation."),
    ("deleted_at", "Deleted at", "text", "UTC ISO-8601. Neo revoked/deleted it at the provider."),
    # --- who and what for
    ("borrower", "Borrower", "text", "Which AI identity needed it (Mo-Sheng, Colophon, ...). 'CI' for a pipeline."),
    ("borrower_session", "Borrower session", "text", "Session id of the borrower, when known."),
    ("purpose", "Purpose", "text", "What the credential was needed FOR, in one line."),
    ("provider", "Provider", "text", "cloudflare / github / anthropic / openai / ..."),
    ("token_label", "Token label", "text", "The NAME shown in the provider console. Never the value."),
    # --- scope and placement
    ("scope_requested", "Scope requested", "text", "Permissions the borrower asked for."),
    ("scope_granted", "Scope granted", "text", "Permissions actually ticked at creation."),
    ("unlimited_scope", "Unlimited scope", "boolean", "True if issued with full/unrestricted permissions."),
    ("expires_at", "Expires at", "text", "Provider-side TTL, if one was set. Blank means none."),
    ("stored_where", "Stored where", "text", "GitHub secret / env file / handed to the AI only / ..."),
    ("consumers", "Consumers", "text", "Pipelines or processes that read it. 'If this dies, who stops?'"),
    # --- registrar controls
    ("tier", "Tier", "text",
     "T0_STANDING / T1_LONG / T2_SHORT / T3_DISPOSABLE. Replaces the old `durable` boolean, which was "
     "a crippled two-level scheme. Tier is decided by `attended`, not by duration - see the axis note."),
    ("attended", "Attended at use", "boolean",
     "THE AXIS. Is a human present at the moment this credential is USED? Attended -> it may be "
     "short-lived, because obtaining a new value and using it happen inside one span of human "
     "attention. Unattended (a push-triggered pipeline) -> it must stand, because the use moment is "
     "unpredictable and, until the provider supports OIDC, nothing can mint a credential at that "
     "moment. Verified 2026-08-25: Cloudflare+Wrangler has no OIDC (workers-sdk#11434 open)."),
    ("stored_copies", "Stored copies", "text",
     "Every place holding this credential's VALUE, as a list. Rotation invalidates all of them at "
     "once, so they have to be enumerable rather than prose. This is the field that answers 'who is "
     "now holding a dead value'."),
    ("durable", "Durable", "boolean",
     "DEPRECATED, kept so old rows still read. Superseded by `tier`. Do not set on new rows."),
    ("deletion_confirmed_by", "Deletion confirmed by", "text", "Who confirmed the provider-side delete."),
    ("last_proven_live", "Last proven live", "text", "UTC ISO-8601 of the last OBSERVED successful use."),
    ("failure_visibility", "Failure visibility", "text",
     "HOW would we find out this credential died? 'blocks CI' / 'silent — consumer skips when unset' / "
     "'probe only'. A consumer that no-ops on a missing secret makes DELETION invisible; one that "
     "swallows errors makes REJECTION invisible. Both together mean CI can never report on it."),
    ("notes", "Notes", "text", "Anything a future reader needs. Never a value."),
]

# --------------------------------------------------------------------------
# Tiers and the lending rules they carry.
#
# The axis is NOT duration. It is: IS A HUMAN PRESENT WHEN THIS IS USED?
#
#   attended   -> obtaining a new value and using it happen inside one span of
#                 human attention, so there is no window in which a stale value
#                 sits waiting to be read. Use-and-destroy is safe here.
#   unattended -> a push-triggered pipeline reads the stored value at a moment
#                 nobody chose. Until the provider can mint a credential at that
#                 moment (Cloudflare has no OIDC as of 2026-08-25), the value
#                 must stand. Rotating it after each use breaks the NEXT run,
#                 every time.
#
# This axis was reached the hard way: 2026-08-24 a CI token was named
# CI-DO-NOT-DELETE- and was rotated anyway - not ignored, just a different verb.
# A rule phrased against one action does not cover its neighbours, so the tier
# declares an invariant instead of forbidding a list of verbs.
# --------------------------------------------------------------------------

TIERS = {
    "T0_STANDING":   {"attended": False, "may_destroy_after_use": False,
                      "why": "read by an unattended pipeline; must be valid at an unpredictable moment"},
    "T1_LONG":       {"attended": True,  "may_destroy_after_use": False,
                      "why": "long-lived but always used with a human present"},
    "T2_SHORT":      {"attended": True,  "may_destroy_after_use": False,
                      "why": "short-lived, expiry MUST be recorded and reminded"},
    "T3_DISPOSABLE": {"attended": True,  "may_destroy_after_use": True,
                      "why": "borrowed for one task, destroyed when that task reports done"},
}


class LendingRuleViolation(ValueError):
    """A registration that the tier's own invariant forbids."""


def check_lending_rules(tier, attended, consumers):
    """Refuse registrations whose tier contradicts how the credential is used."""
    if tier and tier not in TIERS:
        raise LendingRuleViolation(
            "unknown tier %r; must be one of %s" % (tier, ", ".join(sorted(TIERS))))
    if not tier:
        return
    spec = TIERS[tier]
    if attended is not None and bool(attended) != spec["attended"]:
        raise LendingRuleViolation(
            "tier %s requires attended=%s, got attended=%s. The tier is decided by whether a human "
            "is present at USE time, not by how long the credential lives."
            % (tier, spec["attended"], bool(attended)))
    if spec["may_destroy_after_use"] and consumers:
        raise LendingRuleViolation(
            "tier %s is destroyed when the borrower reports done, so it cannot be the credential an "
            "unattended consumer reads: %s. Destroying it breaks that consumer's NEXT run. Register "
            "this as T0_STANDING, or give the consumer its own standing credential."
            % (tier, consumers))


# --------------------------------------------------------------------------
# The write-side guard. This is the boundary made mechanical.
# --------------------------------------------------------------------------

# Known credential prefixes.
#
# NOTE, learned from this file's own selftest: an earlier version wrapped this
# whole alternation in `\b(...)`, which silently disabled the PEM rule — `\b`
# cannot match before a leading `-`, so `-----BEGIN RSA PRIVATE KEY-----` was
# accepted. A guard's dead branch looks exactly like a guard with nothing to
# catch. Word boundaries now sit on the alternatives that are actually words.
_KNOWN_PREFIX = re.compile(
    r"(?:"
    r"\bsk-[A-Za-z0-9_\-]{16,}"          # OpenAI / Anthropic style
    r"|\bgh[pousr]_[A-Za-z0-9]{16,}"     # GitHub PAT / OAuth / server / refresh
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"   # Slack
    r"|\bAKIA[0-9A-Z]{16}"               # AWS access key id
    r"|\bAIza[0-9A-Za-z_\-]{35}"         # Google API key
    r"|\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."  # JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"               # no \b: starts with '-'
    r")"
)

# Generic bare-token shape, in two rules because one rule could not separate a
# token from a human-readable label. The selftest's false positive was
# `efficientnewlanguage-site-deploy-2026-08-24`: 43 chars, but hyphen-separated
# lowercase words, which is a NAME. Length alone does not discriminate.
#
# Rule A — an unbroken alphanumeric run. Labels break on hyphens; bare tokens
#          usually do not.
_BLOB_UNBROKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{28,}(?![A-Za-z0-9])")
# Rule B — a long run that DOES contain separators, but is dense with mixed
#          case and digits the way base64/url-safe tokens are, and unlike a
#          slug, which is lowercase words plus digits at most.
_BLOB_SEPARATED = re.compile(r"(?<![\w/.])[A-Za-z0-9_\-]{28,}(?![\w])")


def _looks_like_bare_token(value: str) -> str | None:
    m = _BLOB_UNBROKEN.search(value)
    if m:
        return m.group(0)
    for m in _BLOB_SEPARATED.finditer(value):
        run = m.group(0)
        seps = sum(run.count(c) for c in "-_")
        has_upper = any(c.isupper() for c in run)
        has_lower = any(c.islower() for c in run)
        has_digit = any(c.isdigit() for c in run)
        # a slug is lowercase+digits with many separators; a token mixes case
        # and digits and separates rarely
        if has_upper and has_lower and has_digit and seps <= 3:
            return run
    return None

# Fields whose legitimate contents may resemble a blob (git SHAs, session ids).
_BLOB_TOLERANT = {"borrower_session", "notes", "consumers"}


class CredentialRefused(ValueError):
    """Raised when a value on its way into the ledger looks like a secret."""


def _reject_secret_shaped(field_key: str, value) -> None:
    if not isinstance(value, str):
        return
    m = _KNOWN_PREFIX.search(value)
    if m:
        raise CredentialRefused(
            "refusing to store field %r: value matches a known credential prefix (%s...). "
            "This ledger records lifecycle, never content." % (field_key, m.group(0)[:8])
        )
    if field_key in _BLOB_TOLERANT:
        return
    run = _looks_like_bare_token(value)
    if run:
        raise CredentialRefused(
            "refusing to store field %r: contains a %d-char opaque run, which is the shape of a "
            "bare token. If this is legitimate metadata, put it in `notes`. "
            "This ledger records lifecycle, never content." % (field_key, len(run))
        )


# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_ledger(db_path: Path | str = DB_PATH):
    db = Database(str(db_path))
    fields = FieldService(db)
    entities = EntityService(db)
    existing = {f["key"] for f in fields.list_fields(limit=500)}
    for key, label, vtype, desc in FIELDS:
        if key not in existing:
            fields.create_field(key=key, label=label, value_type=vtype, description=desc)
    return db, fields, entities


def _set(entities: EntityService, loan_id: str, key: str, value, *, source: str = "kalend") -> None:
    _reject_secret_shaped(key, value)
    entities.set_cell(loan_id, key, value, source=source)


def _cells(entities: EntityService, loan_id: str) -> dict:
    ent = entities.get_entity(loan_id, include_cells=True)
    raw = ent.get("cells") or {}
    out = {}
    for k, v in raw.items():
        out[k] = v.get("value") if isinstance(v, dict) else v
    return out


def derive_state(cells: dict) -> str:
    """State is a FUNCTION of which lifecycle cells are filled. Never stored."""
    if cells.get("deleted_at"):
        return "closed"
    if cells.get("issued_at"):
        # A rotation leaves the credential healthy and every stored copy dead.
        # It outranks the other live states because it is the only one where
        # nothing looks wrong at the provider and something IS wrong downstream.
        if cells.get("rotated_at") and not cells.get("died_at"):
            return "outstanding:ROTATED-COPIES-STALE"
        # `died_at` is a MEASUREMENT (we watched it get rejected); `deleted_at`
        # is an ACTION Neo took. A credential can be dead and still exist as an
        # entry nobody cleaned up, so these must not collapse into one state.
        if cells.get("died_at"):
            return "outstanding:DEAD-NOT-DELETED"
        if cells.get("durable"):
            return "outstanding:durable"
        if cells.get("completed_at"):
            return "outstanding:AWAITING-DELETE"
        return "outstanding:in-use"
    if cells.get("requested_at"):
        return "requested"
    return "empty"


STATE_NOTE = {
    "outstanding:ROTATED-COPIES-STALE": "the VALUE was replaced — the provider entry is healthy and "
                                        "every stored copy is now dead. Nothing upstream looks wrong.",
    "outstanding:DEAD-NOT-DELETED": "observed rejected, and no deletion recorded — it stopped working "
                                    "but the entry is probably still sitting in the provider console",
    "outstanding:AWAITING-DELETE": "work is done and the token still exists — this is the risk row",
    "outstanding:in-use": "issued, borrower has not reported completion yet",
    "outstanding:durable": "deliberately long-lived (e.g. CI) — do not sweep",
    "requested": "asked for, not yet generated",
    "closed": "deleted at the provider",
}


# --------------------------------------------------------------------------
# Registrar operations
# --------------------------------------------------------------------------


def op_request(args) -> int:
    db, fields, entities = open_ledger()
    loan_id = args.id or "loan-%s-%s" % (_now()[:10], args.borrower.lower().replace(" ", "-"))
    entities.create_entity(label="%s / %s" % (args.borrower, args.provider), kind="token_loan", entity_id=loan_id)
    _set(entities, loan_id, "requested_at", args.at or _now())
    _set(entities, loan_id, "borrower", args.borrower)
    _set(entities, loan_id, "provider", args.provider)
    _set(entities, loan_id, "purpose", args.purpose)
    if args.scope:
        _set(entities, loan_id, "scope_requested", args.scope)
    if args.session:
        _set(entities, loan_id, "borrower_session", args.session)
    print("requested: %s" % loan_id)
    return 0


def op_issue(args) -> int:
    db, fields, entities = open_ledger()
    cells = _cells(entities, args.id)
    if cells.get("issued_at"):
        print("REFUSED: %s already has issued_at=%s. Lifecycle cells are write-once."
              % (args.id, cells["issued_at"]))
        return 1
    # Validate BEFORE the first write. An earlier version checked the lending
    # rules at the END of this function, so a refused registration had already
    # written issued_at and friends: the command printed REFUSED and committed
    # anyway. A refusal that half-commits is worse than no refusal, because the
    # operator believes nothing happened. Everything below this line is only
    # reached once the registration is known to be legal.
    attended = None if args.attended is None else bool(args.attended)
    try:
        check_lending_rules(args.tier, attended, args.consumers)
    except LendingRuleViolation as e:
        print("REFUSED: %s" % e)
        print("  (nothing was written — this check runs before the first cell)")
        return 1
    _set(entities, args.id, "issued_at", args.at or _now())
    if args.label:
        _set(entities, args.id, "token_label", args.label)
    if args.scope_granted:
        _set(entities, args.id, "scope_granted", args.scope_granted)
    if args.stored_where:
        _set(entities, args.id, "stored_where", args.stored_where)
    if args.consumers:
        _set(entities, args.id, "consumers", args.consumers)
    if args.expires:
        _set(entities, args.id, "expires_at", args.expires)
    _set(entities, args.id, "unlimited_scope", bool(args.unlimited))
    if args.tier:
        _set(entities, args.id, "tier", args.tier)
    if attended is not None:
        _set(entities, args.id, "attended", attended)
    if args.copy:
        _set(entities, args.id, "stored_copies", list(args.copy))
    if args.durable:
        _set(entities, args.id, "durable", True)
    print("issued: %s" % args.id)
    if args.unlimited and not args.durable:
        print("  note: unlimited scope with no TTL — safe only if it gets deleted. "
              "It will show as outstanding until `deleted` is recorded.")
    return 0


def op_complete(args) -> int:
    db, fields, entities = open_ledger()
    cells = _cells(entities, args.id)
    if not cells.get("issued_at"):
        print("REFUSED: %s was never issued — cannot complete a loan that does not exist." % args.id)
        return 1
    if cells.get("completed_at"):
        print("REFUSED: %s already completed at %s." % (args.id, cells["completed_at"]))
        return 1
    _set(entities, args.id, "completed_at", args.at or _now())
    print("completed: %s  -> now AWAITING-DELETE" % args.id)
    print("  the token still exists at the provider. It stays on the outstanding list until deleted.")
    return 0


def op_deleted(args) -> int:
    db, fields, entities = open_ledger()
    cells = _cells(entities, args.id)
    if not cells.get("issued_at"):
        print("REFUSED: %s was never issued." % args.id)
        return 1
    if cells.get("deleted_at"):
        print("REFUSED: %s already deleted at %s." % (args.id, cells["deleted_at"]))
        return 1
    if cells.get("durable") and not args.force:
        print("REFUSED: %s is marked durable (%s). Deleting it breaks its consumers: %s"
              % (args.id, cells.get("token_label", "?"), cells.get("consumers", "unknown")))
        print("  pass --force if you really deleted it, and rotate the consumers first.")
        return 1
    _set(entities, args.id, "deleted_at", args.at or _now())
    _set(entities, args.id, "deletion_confirmed_by", args.by)
    print("closed: %s" % args.id)
    return 0


def op_rotate(args) -> int:
    """Record that the VALUE was replaced, and name every copy that just died.

    This is the command that did not exist on 2026-08-24. Neo rotated a CI
    token right after a verified deploy — correct by his own methodology — and
    nothing said out loud that the repo secret was now holding a dead value.
    The next push failed 12h later and two lines spent an hour deciding whether
    it had expired. The answer was knowable at rotation time, by anyone who
    looked at the list of copies.
    """
    db, fields, entities = open_ledger()
    cells = _cells(entities, args.id)
    if not cells.get("issued_at"):
        print("REFUSED: %s was never issued." % args.id)
        return 1
    if cells.get("deleted_at"):
        print("REFUSED: %s is closed; a deleted credential cannot be rotated." % args.id)
        return 1
    _set(entities, args.id, "rotated_at", args.at or _now())
    copies = cells.get("stored_copies") or []
    if isinstance(copies, str):
        copies = [copies]
    print("rotated: %s at %s" % (args.id, args.at or _now()))
    print()
    if copies:
        print("  THESE COPIES ARE NOW DEAD — every one holds the previous value:")
        for c in copies:
            print("     x %s" % c)
    elif cells.get("stored_where"):
        print("  THIS COPY IS NOW DEAD (no enumerated list, falling back to `stored_where`):")
        print("     x %s" % cells["stored_where"])
    else:
        print("  no stored copies recorded — so this ledger CANNOT tell you what just broke.")
        print("  That absence is the finding. Register copies with `issue --copy`.")
    print()
    if cells.get("consumers"):
        print("  and these consumers read one of them: %s" % cells["consumers"])
    if cells.get("attended") is False or cells.get("tier") == "T0_STANDING":
        print()
        print("  WARNING: this is an UNATTENDED credential. Its next use happens at a moment nobody")
        print("  chooses, so it will fail then, not now. Update every copy above before that moment.")
    return 0


def op_stale(args) -> int:
    db, fields, entities = open_ledger()
    rows = [(i, c) for i, c, st in _rows(entities) if st == "outstanding:ROTATED-COPIES-STALE"]
    if not rows:
        print("no credential has been rotated without its copies being refreshed.")
        return 0
    print("ROTATED — copies holding a dead value   (%s)" % _now())
    print()
    for lid, c in rows:
        copies = c.get("stored_copies") or ([c["stored_where"]] if c.get("stored_where") else [])
        if isinstance(copies, str):
            copies = [copies]
        print("  %s   rotated %s" % (lid, c.get("rotated_at", "?")))
        print("     tier=%s attended=%s" % (c.get("tier", "-"), c.get("attended", "-")))
        for x in copies:
            print("     x %s" % x)
        print()
    return 0


def _rows(entities: EntityService):
    for ent in entities.list_entities(limit=2000):
        if ent.get("kind") != "token_loan":
            continue
        c = _cells(entities, ent["id"])
        yield ent["id"], c, derive_state(c)


def op_outstanding(args) -> int:
    db, fields, entities = open_ledger()
    rows = [(i, c, s) for i, c, s in _rows(entities) if s.startswith("outstanding")]
    order = {"outstanding:DEAD-NOT-DELETED": 0, "outstanding:AWAITING-DELETE": 1,
             "outstanding:in-use": 2, "outstanding:durable": 3}
    rows.sort(key=lambda r: (order.get(r[2], 9), r[0]))
    if not rows:
        print("nothing outstanding — every issued token has a recorded deletion.")
        return 0
    print("OUTSTANDING TOKENS — issued and not recorded as deleted   (%s)" % _now())
    print()
    for loan_id, c, state in rows:
        print("  %-38s %s" % (loan_id, state))
        print("      %s" % STATE_NOTE.get(state, ""))
        print("      borrower=%s  provider=%s  label=%s"
              % (c.get("borrower", "?"), c.get("provider", "?"), c.get("token_label", "-")))
        print("      purpose=%s" % c.get("purpose", "-"))
        print("      issued=%s  completed=%s  died=%s  unlimited=%s  expires=%s"
              % (c.get("issued_at", "-"), c.get("completed_at", "-"), c.get("died_at", "-"),
                 c.get("unlimited_scope", "-"), c.get("expires_at", "none")))
        if c.get("stored_where"):
            print("      stored=%s" % c["stored_where"])
        if c.get("consumers"):
            print("      if it dies, who stops: %s" % c["consumers"])
        print()
    awaiting = sum(1 for _, _, s in rows if s == "outstanding:AWAITING-DELETE")
    dead = sum(1 for _, _, s in rows if s == "outstanding:DEAD-NOT-DELETED")
    print("  %d outstanding: %d observed DEAD with no deletion recorded, %d done being used and "
          "still live." % (len(rows), dead, awaiting))
    return 0


def op_list(args) -> int:
    db, fields, entities = open_ledger()
    rows = list(_rows(entities))
    if not rows:
        print("ledger is empty.")
        return 0
    print("%-38s %-26s %-14s %s" % ("loan id", "state", "provider", "borrower"))
    for loan_id, c, state in sorted(rows, key=lambda r: r[0]):
        print("%-38s %-26s %-14s %s" % (loan_id, state, c.get("provider", "?"), c.get("borrower", "?")))
    return 0


def op_show(args) -> int:
    db, fields, entities = open_ledger()
    c = _cells(entities, args.id)
    print("%s   state=%s" % (args.id, derive_state(c)))
    print("  %s" % STATE_NOTE.get(derive_state(c), ""))
    print()
    for key, label, _vt, _d in FIELDS:
        if key in c:
            print("  %-22s %s" % (key, c[key]))
    return 0


def op_selftest(args) -> int:
    """Prove the write-side guard refuses credential-shaped input."""
    print("=== ledger write-guard selftest ===")
    canaries = [
        ("scope_granted", "sk-ant-CANARYaaaaaaaaaaaaaaaaaaaaaaaa", "known prefix (Anthropic)"),
        ("token_label", "ghp_CANARYbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "known prefix (GitHub PAT)"),
        ("purpose", "AIzaCANARYcccccccccccccccccccccccccccccccc", "known prefix (Google)"),
        ("notes", "-----BEGIN RSA PRIVATE KEY-----", "PEM private key, even in a tolerant field"),
        ("token_label", "CANARYddddddddddddddddddddddddddddd", "generic opaque blob, no known prefix"),
        # Rule B: a Cloudflare-style token DOES carry separators. Rule A alone
        # would miss it, so this case is what keeps Rule B from being dead code.
        ("scope_granted", "CANARY_v1-Xk9mQ2pL_7bTzR4wN8sVaE3jH6yU5cF0dG1i",
         "url-safe token WITH separators (Rule B, not Rule A)"),
        ("purpose", "the value is CANARYeeeeeeeeeeeeeeeeeeeeeeeeeee ok?",
         "opaque blob embedded mid-sentence, not the whole value"),
    ]
    refused = 0
    for key, value, why in canaries:
        try:
            _reject_secret_shaped(key, value)
            print("  LEAK   %-16s %s  <-- accepted, should have been refused" % (key, why))
        except CredentialRefused:
            refused += 1
            print("  refused %-16s %s" % (key, why))
    print()
    legit = [
        ("scope_granted", "Account · Cloudflare Pages · Edit"),
        ("purpose", "deploy efficientnewlanguage.org from CI"),
        # the false positive that failed the first run of this selftest
        ("token_label", "efficientnewlanguage-site-deploy-2026-08-24"),
        ("token_label", "eveglyph-website-pages-deploy-2026-08-24-temp"),
        ("stored_where", "GitHub Actions secret CLOUDFLARE_API_TOKEN"),
        ("issued_at", "2026-08-24T10:00:00Z"),
        ("borrower", "Mo-Sheng"),
        ("purpose", "publish rounds 97-99 to efficientnewlanguage.org, 531 corpus cases"),
        ("consumers", "kakon77777-commits/efficientnewlanguage-site .github/workflows/deploy.yml"),
        ("notes", "site_sha 45de97d597614f7d472b1592381852105bd7d340 was the target build"),
    ]
    passed = 0
    for key, value in legit:
        try:
            _reject_secret_shaped(key, value)
            passed += 1
            print("  accepted %-16s %s" % (key, value[:52]))
        except CredentialRefused as e:
            print("  FALSE POSITIVE %-16s %s   (%s)" % (key, value[:40], e))
    print()
    ok = refused == len(canaries) and passed == len(legit)
    print("canaries refused: %d/%d    legitimate metadata accepted: %d/%d"
          % (refused, len(canaries), passed, len(legit)))
    print("SELFTEST: %s" % ("PASS" if ok else "FAIL"))
    print()
    print("Both halves matter: a guard that refuses everything would pass the first")
    print("count and make the ledger unusable. See feedback-two-fixes-one-green-test.")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Token lending ledger (SEDB). Lifecycle only — never a value.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("request", help="an AI asks for a credential")
    r.add_argument("--borrower", required=True)
    r.add_argument("--provider", required=True)
    r.add_argument("--purpose", required=True)
    r.add_argument("--scope", default="")
    r.add_argument("--session", default="")
    r.add_argument("--id", default="")
    r.add_argument("--at", default="")
    r.set_defaults(func=op_request)

    i = sub.add_parser("issue", help="Neo generated it")
    i.add_argument("id")
    i.add_argument("--label", default="", help="the NAME in the provider console, never the value")
    i.add_argument("--scope-granted", dest="scope_granted", default="")
    i.add_argument("--stored-where", dest="stored_where", default="")
    i.add_argument("--consumers", default="")
    i.add_argument("--expires", default="")
    i.add_argument("--unlimited", action="store_true")
    i.add_argument("--durable", action="store_true", help="DEPRECATED, use --tier")
    i.add_argument("--tier", default="", choices=["", "T0_STANDING", "T1_LONG", "T2_SHORT", "T3_DISPOSABLE"])
    i.add_argument("--attended", dest="attended", action="store_true", default=None,
                   help="a human is present when this credential is USED")
    i.add_argument("--unattended", dest="attended", action="store_false",
                   help="read by a pipeline at a moment nobody chooses")
    i.add_argument("--copy", action="append", default=[],
                   help="a place holding the VALUE; repeatable. Rotation kills all of them at once.")
    i.add_argument("--at", default="")
    i.set_defaults(func=op_issue)

    c = sub.add_parser("complete", help="borrower reported the work done")
    c.add_argument("id")
    c.add_argument("--at", default="")
    c.set_defaults(func=op_complete)

    d = sub.add_parser("deleted", help="Neo deleted it at the provider")
    d.add_argument("id")
    d.add_argument("--by", default="Neo")
    d.add_argument("--at", default="")
    d.add_argument("--force", action="store_true")
    d.set_defaults(func=op_deleted)

    ro = sub.add_parser("rotate", help="the VALUE was replaced — names every copy that just died")
    ro.add_argument("id")
    ro.add_argument("--at", default="")
    ro.set_defaults(func=op_rotate)

    sub.add_parser("stale", help="copies holding a dead value after a rotation").set_defaults(func=op_stale)
    sub.add_parser("outstanding", help="THE question: what is still out there").set_defaults(func=op_outstanding)
    sub.add_parser("list", help="every loan").set_defaults(func=op_list)
    sub.add_parser("selftest", help="prove the write guard refuses secrets").set_defaults(func=op_selftest)

    s = sub.add_parser("show", help="one loan in full")
    s.add_argument("id")
    s.set_defaults(func=op_show)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

"""Build the AMRAL results-profile registry as a SEDB database.

數學戰士「墜衡」 / AMRAL Research Lab.

WHAT THIS IS. Four profiles govern what a consumer may rely on in any AMRAL
research line's `data/results.v*.json`. Until now that registry lived inside
ONE line's tree — a Markdown spec plus a Python dict in
`collatz-verification-zhuiheng` — while governing every line. With two lines
that is untidy; with a third it is a second truth, which is the failure this
whole contract exists to prevent.

WHAT MOVES AND WHAT DOES NOT. The predicates stay in code: "does this file have
a non-empty explicit_non_claims" is executable logic, not data. What moves here
is the REGISTRY — which profiles exist, what each requires, why it was
proposed, what its lifecycle status is, and which line satisfies which. SEDB is
the right home for exactly one reason that matters: `field_events.reason` is
NOT NULL, so a profile's status cannot change without a recorded reason. Today
those reasons live in commit messages, which is discipline, not structure.

WHERE THE NUMBERS COME FROM. The satisfaction cells are read from the archived
cross-branch measurement in the verification tree, not typed here. If that log
is missing this script refuses rather than inventing a registry.

Usage:  python ingest.py
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SEDB_SRC = HERE.parent.parent / "current" / "src"
sys.path.insert(0, str(SEDB_SRC))

from sedb.db import Database                     # noqa: E402
from sedb.entities import EntityService          # noqa: E402
from sedb.fields import FieldService             # noqa: E402

DB_PATH = HERE / "amral-results-profiles.sqlite"
MEASUREMENT = (HERE.parent.parent.parent / "amral-research-trees"
               / "collatz-verification-zhuiheng" / "data" / "gate-logs"
               / "results-profiles.json")

ARM = "數學戰士「墜衡」 / collatz-verification-zhuiheng"

# key -> (label, description, converged_reason or None)
#
# `converged` is claimed only where the definition has not changed since the
# profile was created AND every known line satisfies it. results-figures/1
# gained its `kind` discriminator hours after creation, so it stays `active`:
# a definition that moved today has not settled, whatever its adoption looks
# like.
PROFILES = {
    "results-envelope/1": (
        "Envelope",
        "The six keys every AMRAL results file already agreed on before there "
        "was a contract: schema_version, research_line_id, "
        "researcher.display_name, date, problem.id, and a global_status "
        "carrying a BOOLEAN solved and a non-empty statement. solved must be "
        "typed because \"false\" is truthy, and a renderer reading a string "
        "there would print \"solved\" for a line that claims nothing.",
        "both known lines satisfied it from the moment it was written, and its "
        "definition has not changed since; it describes what the files already "
        "agreed on rather than asking them to move",
    ),
    "results-claims/1": (
        "Structured claims and boundaries",
        "Envelope plus verified_claims (each with id and claim) and "
        "explicit_non_claims (non-empty strings). A line outside this profile "
        "still states its boundaries in global_status.statement and its report "
        "prose, and MUST still be rendered with them; failing this profile is "
        "a rendering branch, never a licence to drop a boundary.",
        "the second line adopted it on 2026-09-03 by transcribing boundaries "
        "its own README already stated, recomputing nothing; both known lines "
        "now satisfy it and the definition has not changed since creation",
    ),
    "results-pairs/1": (
        "Figures that must not stand alone",
        "Envelope plus render_pairs: value, against, and a stated why, each "
        "path resolving to a number in the same document. \"1441 defects "
        "caught\" reads identically whether 1441 or 2000 were planted, and "
        "which of two numbers is load-bearing is a fact about the line, not "
        "something a renderer can infer.",
        "created and adopted by both known lines on 2026-09-03 with its "
        "definition unchanged since. The cross-profile rule added later "
        "constrains results-figures/1, not this one, so nothing about this "
        "definition has moved.",
    ),
    "results-figures/1": (
        "A line's own headline figures",
        "Envelope plus headline_figures: path, label, and a kind of \"number\" "
        "or \"range\". Nothing declared here may also belong to a pair — a "
        "paired figure offered standalone is the bare-numerator defect "
        "reintroduced by the mechanism built to prevent it.",
        None,
    ),
}

PROPOSED_BECAUSE = {
    "results-envelope/1":
        "schema_version 1 did not identify a shape: two files declared it and "
        "shared only six keys, so a renderer dispatching on the integer would "
        "break on one of them",
    "results-claims/1":
        "a claim-box UI needs claims and boundaries in structured fields; one "
        "line had them only in prose, so a structural reader saw a line with "
        "no stated boundary, the opposite of what that line says",
    "results-pairs/1":
        "the verification sub-site rendered three correct numbers, each "
        "without the figure that gives it meaning; a build-time check "
        "comparing rendered values against source verifies fidelity, not "
        "sufficiency, and cannot catch a field that was simply not rendered",
    "results-figures/1":
        "a renderer that must guess which fields are a line's headlines "
        "hardcodes one line's shape; when a second line arrived its entire "
        "body of work rendered as two empty section headings",
}


def measured() -> dict[str, list[str]]:
    """research_line_id -> profiles it satisfies, from the archived log."""
    if not MEASUREMENT.exists():
        raise SystemExit(
            f"missing {MEASUREMENT}\n"
            "This registry records a measurement it does not perform. Run the "
            "verification tree's validate_results_profiles.py first; a registry "
            "invented here would be exactly the hand-kept table it replaces.")
    doc = json.loads(MEASUREMENT.read_text(encoding="utf-8"))
    return {row["research_line_id"]: row["satisfies"]
            for row in doc["files"] if row.get("research_line_id")}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    lines = measured()
    if DB_PATH.exists():
        DB_PATH.unlink()

    db = Database(DB_PATH)
    fields = FieldService(db)
    entities = EntityService(db)

    # Fields are the profiles. Every one starts `proposed`, because every one
    # was: none of these existed this morning, and recording them as born
    # `active` would erase the only history this registry is for.
    ids = {}
    for key, (label, description, _) in PROFILES.items():
        f = fields.create_field(key=key, label=label, value_type="boolean",
                                description=description, status="proposed",
                                namespace="amral-results")
        ids[key] = f["id"]
        fields.transition(f["id"], "active",
                          reason=PROPOSED_BECAUSE[key],
                          evidence={"spec": "collatz-verification-zhuiheng/"
                                            "reports/RESULTS-PROFILES.md"},
                          evaluator=ARM)

    # Entities are the research lines.
    line_ids = {}
    for line_id in sorted(lines):
        e = entities.create_entity(label=line_id, kind="research-line")
        line_ids[line_id] = e["id"]

    # Cells are the measurement, cited to the log it was read from.
    filled = 0
    for line_id, satisfied in lines.items():
        for key in PROFILES:
            if key in satisfied:
                entities.set_cell(line_ids[line_id], key, True,
                                  source=str(MEASUREMENT.name))
                filled += 1
            # A profile a line does not satisfy is left BLANK, not written
            # false. Blank is a valid state: it is the branch a renderer takes,
            # not a failure to record.

    # Convergence, claimed only where earned and always with a reason SEDB
    # refuses to store as empty.
    converged = []
    for key, (_, _, reason) in PROFILES.items():
        if reason is None:
            continue
        holders = [l for l, s in lines.items() if key in s]
        if len(holders) != len(lines):
            continue
        fields.transition(ids[key], "converged", reason=reason,
                          evidence={"satisfied_by": sorted(holders),
                                    "measured_in": MEASUREMENT.name},
                          evaluator=ARM)
        converged.append(key)

    print(f"wrote {DB_PATH.name}")
    print(f"  research lines : {len(lines)}  {sorted(lines)}")
    print(f"  profiles       : {len(PROFILES)}")
    print(f"  cells filled   : {filled} of {len(lines) * len(PROFILES)} possible")
    print(f"  converged      : {converged}")
    print(f"  still active   : {[k for k in PROFILES if k not in converged]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

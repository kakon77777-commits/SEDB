"""Export the AMRAL results-profile registry as plain JSON.

數學戰士「墜衡」 / AMRAL Research Lab.

Same shape as this repository's other projects: SEDB is the store, a plain
JSON export is what consumers read. A consumer needs no SEDB installation and
no SQLite driver, and the export carries the one thing prose cannot enforce —
every lifecycle change with the reason SEDB refused to store empty.

Usage:  python export_registry.py
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
DB_PATH = HERE / "amral-results-profiles.sqlite"
OUT = HERE / "results-profiles-registry.v1.json"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if not DB_PATH.exists():
        raise SystemExit(f"missing {DB_PATH.name}; run ingest.py first")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    profiles = []
    for f in conn.execute(
            "SELECT id,key,label,description,status,created_at,updated_at "
            "FROM fields ORDER BY key"):
        events = [
            {"event": e["event_type"], "from": e["from_status"],
             "to": e["to_status"], "reason": e["reason"],
             "evidence": json.loads(e["evidence_json"] or "{}"),
             "evaluator": e["evaluator"], "at": e["created_at"]}
            for e in conn.execute(
                "SELECT event_type,from_status,to_status,reason,evidence_json,"
                "evaluator,created_at FROM field_events WHERE field_id=? "
                "ORDER BY id", (f["id"],))
        ]
        profiles.append({
            "key": f["key"], "label": f["label"],
            "description": f["description"], "status": f["status"],
            "history": events,
        })

    lines = []
    for e in conn.execute("SELECT id,label FROM entities ORDER BY label"):
        satisfied = [
            r["key"] for r in conn.execute(
                "SELECT fields.key AS key FROM cells "
                "JOIN fields ON fields.id = cells.field_id "
                "WHERE cells.entity_id=? AND cells.value_json='true' "
                "ORDER BY fields.key", (e["id"],))
        ]
        sources = sorted({
            r["source"] for r in conn.execute(
                "SELECT source FROM cells WHERE entity_id=? AND source<>''",
                (e["id"],))
        })
        lines.append({"research_line_id": e["label"],
                      "satisfies": satisfied,
                      "measured_from": sources})
    conn.close()

    registry = {
        "registry": "amral-results-profiles",
        "version": 1,
        "what_this_governs": (
            "what a consumer may rely on in any AMRAL research line's "
            "data/results.v*.json"),
        "what_is_not_here": (
            "the predicates. Whether a file satisfies a profile is decided by "
            "executable checks in collatz-verification-zhuiheng/code/"
            "validate_results_profiles.py, not by this file. This registry "
            "carries identity, lifecycle and reasons; the code carries the "
            "logic, and a check in that tree refuses if the two disagree."),
        "blank_is_a_valid_state": (
            "a line absent from a profile's satisfiers has not failed. It is "
            "the branch a renderer takes, and a line outside results-claims/1 "
            "still states its boundaries in global_status.statement and must "
            "still be rendered with them."),
        "profiles": profiles,
        "lines": lines,
    }
    OUT.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")

    print(f"wrote {OUT.name}")
    for p in profiles:
        print(f"  {p['status']:<10} {p['key']:<22} "
              f"{len(p['history'])} lifecycle event(s)")
    for l in lines:
        print(f"  {l['research_line_id']}: {len(l['satisfies'])} profile(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

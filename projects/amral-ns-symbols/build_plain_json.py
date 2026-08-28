"""Build the plain, standalone JSON symbol reference for AMRAL.

This is a genuine sibling of the SEDB edition, not a rendering of it:
the output JSON has zero dependency on sedb/sqlite to read or use, and is
meant to live in AMRAL's own project space rather than under this SEDB
consumer project. Reusing the SYMBOLS list from ingest.py here is purely
an authoring convenience (avoids retyping 71 reviewed entries and letting
the two copies drift) -- SEDB itself is untouched by this script, and the
JSON output does not reference or require SEDB at all.

Output path lives under amral's `public/` (2026-08-28, per Neo's explicit
choice to commit+push+deploy this file rather than leave it local-only):
the amral Cloudflare Worker is an assets-only Worker serving exactly
`public/` (see wrangler.jsonc), so anything meant to be fetchable on the
live site must sit inside that directory. Previously this wrote to
`amral/data/symbols/...`, which is outside `public/` and was therefore
never actually servable even once committed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingest import SYMBOLS

OUT_PATH = Path(r"D:\Ai\work together\amral\public\data\symbols\ns-symbols.json")

FIELD_ORDER = [
    "latex",
    "series",
    "first_appearance",
    "label_zh",
    "label_en",
    "definition_zh",
    "definition_en",
    "defining_relation",
    "notes",
]


def build_entry(symbol: dict) -> dict:
    entry = {"id": symbol["key"]}
    for field in FIELD_ORDER:
        if field == "series":
            entry["series"] = symbol.get("series", "NS")
            continue
        value = symbol.get(field)
        if value:
            entry[field] = value
    return entry


def main() -> None:
    payload = {
        "$comment_zh": "AMRAL 符號全域對照表：符號、定義、出處，純文字/JSON，不依賴 SEDB。",
        "$comment_en": "AMRAL global symbol reference: symbol, definition, source. Plain "
        "JSON, no SEDB dependency to read or use.",
        "generated_by": "見證 (Claude Code / AMRAL session), 2026-08-24",
        "count": len(SYMBOLS),
        "symbols": [build_entry(s) for s in SYMBOLS],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Wrote {OUT_PATH} ({len(SYMBOLS)} symbols)")


if __name__ == "__main__":
    main()

"""Generate the flat, human-facing global symbol cross-reference table
(symbol -> basic definition -> source) from the SEDB database.

SEDB is the source of truth; this file is a rendered VIEW over it, not a
separately hand-maintained copy. Re-run after every ingest.py update.
"""

from __future__ import annotations

import re
from pathlib import Path

from sedb.db import Database
from sedb.entities import EntityService

DB_PATH = Path(__file__).parent / "amral-ns-symbols.sqlite"
OUT_PATH = Path(__file__).parent / "SYMBOL_INDEX.md"

# list_entities() clamps its limit at 10000 internally; pass a generous fixed
# ceiling here rather than importing ingest.py just to size this exactly, so
# growth (new rounds) doesn't require editing this constant.
FETCH_LIMIT = 10000


def _round_sort_key(tag: str) -> tuple:
    if tag == "framework":
        return (-1, "", "")
    m = re.match(r"C(\d+)(?:-([A-Za-z]+))?$", tag)
    if not m:
        return (999, tag, "")  # unrecognized tags sort last, still rendered
    return (int(m.group(1)), m.group(2) or "", "")


def main() -> None:
    db = Database(DB_PATH)
    es = EntityService(db)
    entities = es.list_entities(limit=FETCH_LIMIT)

    by_round: dict[str, list[dict]] = {}
    for stub in entities:
        e = es.get_entity(stub["id"])
        v = e["values"]
        tag = v.get("first_appearance", "framework")
        by_round.setdefault(tag, []).append(v)

    round_order = sorted(by_round.keys(), key=_round_sort_key)

    lines: list[str] = []
    lines.append("# AMRAL NS 符號全域對照表 / AMRAL NS Global Symbol Index")
    lines.append("")
    lines.append(
        "自動由 SEDB 資料庫產生，勿手動編輯——改 `ingest.py` 再重跑 `export_index.py`。"
    )
    lines.append(
        "Auto-generated from the SEDB database; do not hand-edit -- change `ingest.py` "
        "and re-run `export_index.py` instead."
    )
    lines.append("")
    lines.append(f"共 {len(entities)} 個符號 / {len(entities)} symbols total.")
    lines.append("")

    for tag in round_order:
        rows = by_round.get(tag, [])
        if not rows:
            continue
        heading = "框架共用符號 (Framework)" if tag == "framework" else f"{tag}"
        lines.append(f"## {heading}")
        lines.append("")
        lines.append("| 符號 Symbol | 中文定義 | Definition (EN) | 出處 Source |")
        lines.append("|---|---|---|---|")
        for v in rows:
            latex = (v.get("latex") or "").replace("|", "\\|").replace("\n", " ")
            zh = (v.get("definition_zh") or v.get("label_zh") or "").replace("|", "\\|")
            en = (v.get("definition_en") or v.get("label_en") or "").replace("|", "\\|")
            src = v.get("first_appearance") or ""
            lines.append(f"| `{latex}` | {zh} | {en} | {src} |")
        lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(entities)} symbols across {len(round_order)} sections)")


if __name__ == "__main__":
    main()

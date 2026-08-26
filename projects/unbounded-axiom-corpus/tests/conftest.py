from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
SEDB_ROOT = PROJECT_DIR.parents[1]
for import_root in (PROJECT_DIR, SEDB_ROOT / "current" / "src"):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)


def paper(item_id: str, month: str = "2026-04", **overrides):
    result = {
        "id": item_id,
        "title": f"Paper {item_id}",
        "source_file": f"content/papers/2026/{month}/Paper-{item_id}.md",
        "language": "zh-Hant",
        "created": "2026-04-01",
        "year": 2026,
        "month": month,
        "hash": "sha256:" + ("a" * 64),
        "canonical_url": f"/p/{item_id}/",
        "date_confidence": "explicit",
        "date_basis": (
            "git-first-add (publication/upload date; "
            "not the author's in-text writing date)"
        ),
    }
    result.update(overrides)
    return result


@pytest.fixture
def write_registry(tmp_path: Path):
    def write(items, *, version="0.2", count=None):
        path = tmp_path / "papers.json"
        path.write_text(
            json.dumps(
                {
                    "version": version,
                    "count": len(items) if count is None else count,
                    "items": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    return write

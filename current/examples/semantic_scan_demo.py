from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sedb.db import Database
from sedb.fields import FieldService
from sedb.semantic import SemanticDedupService


def build_semantic_demo(path: str | Path, field_count: int = 10_000) -> dict:
    path = Path(path)
    if path.exists():
        path.unlink()
    db = Database(path)
    fields = FieldService(db)
    semantic = SemanticDedupService(db)

    if field_count < 4:
        raise ValueError("field_count must be >= 4")

    specs = [
        {"key": "author_country", "label": "Author country", "value_type": "text"},
        {"key": "country_author", "label": "Country author", "value_type": "text"},
        {"key": "source_quality", "label": "Source quality", "value_type": "text"},
        {"key": "quality_source", "label": "Quality source", "value_type": "text"},
    ]
    for index in range(4, field_count):
        specs.append(
            {
                "key": f"field_{index:05d}",
                "label": f"Field {index:05d}",
                "value_type": "text",
                "description": "Synthetic sparse registry field for bounded scan validation.",
            }
        )
    fields.bulk_create_fields(specs)

    start = time.perf_counter()
    found = semantic.scan_field_similarity(
        namespace="global",
        threshold=0.95,
        max_neighbors=6,
    )
    elapsed = time.perf_counter() - start

    expected_pairs = [
        {"author_country", "country_author"},
        {"source_quality", "quality_source"},
    ]
    with db.connect() as conn:
        key_by_id = {row["id"]: row["key"] for row in conn.execute("SELECT id,key FROM fields")}
    found_key_pairs = [
        {key_by_id[item["source_ref"]], key_by_id[item["candidate_field_id"]]}
        for item in found
    ]
    expected_found = sum(1 for pair in expected_pairs if pair in found_key_pairs)

    return {
        "fields": field_count,
        "max_neighbors": 6,
        "threshold": 0.95,
        "persisted_candidates": len(found),
        "expected_duplicate_pairs_found": expected_found,
        "elapsed_seconds": round(elapsed, 6),
        "all_pairs_if_naive": field_count * (field_count - 1) // 2,
        "bounded_pair_upper_bound": field_count * 6,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="semantic-scan-10k.sqlite")
    parser.add_argument("--fields", type=int, default=10_000)
    args = parser.parse_args()
    result = build_semantic_demo(args.db, args.fields)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

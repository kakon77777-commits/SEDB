from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from sedb.db import Database
from sedb.entities import EntityService
from sedb.family import FieldFamilyService
from sedb.fields import FieldService


def _reset(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        path.unlink()
    return path


def _create_permutation_group(fields: FieldService, tokens: tuple[str, str, str]) -> list[dict]:
    a, b, c = tokens
    specs = [
        (f"{a}_{b}_{c}", f"{a} {b} {c}"),
        (f"{b}_{c}_{a}", f"{b} {c} {a}"),
        (f"{c}_{a}_{b}", f"{c} {a} {b}"),
    ]
    return [
        fields.create_field(
            key=key, label=label.title(), value_type="number",
            description=f"{a} {b} {c}",
        )
        for key, label in specs
    ]


def build_family_demo(path: str | Path) -> dict:
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    families = FieldFamilyService(db)
    entities = EntityService(db)

    duplicate_group = _create_permutation_group(fields, ("source", "evidence", "quality"))
    related_group = _create_permutation_group(fields, ("model", "runtime", "latency"))
    split_group = _create_permutation_group(fields, ("author", "country", "origin"))
    reject_group = _create_permutation_group(fields, ("model", "cost", "budget"))

    entity = entities.create_entity(label="Demo row", kind="demo")
    entities.set_cell(entity["id"], duplicate_group[1]["key"], 7, source="demo")
    entities.set_cell(entity["id"], related_group[0]["key"], 11, source="demo")

    proposals = []
    for group in (duplicate_group, related_group, split_group, reject_group):
        proposal = families.propose_from_seed(
            group[0]["id"], seed_threshold=0.95, min_coherence=0.95,
            max_neighbors=12, max_members=6, evaluator="demo:family",
        )
        if proposal is None:
            raise RuntimeError(f"demo group did not form: {group[0]['key']}")
        proposals.append(proposal)

    fields_before = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    cells_before = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)

    duplicate_review = families.review_proposal(
        proposals[0]["id"], "duplicate_family",
        reason="Demo-confirmed duplicate semantic family", evaluator="demo:review",
    )
    related_review = families.review_proposal(
        proposals[1]["id"], "related_family",
        reason="Demo-confirmed related semantic family", evaluator="demo:review",
    )
    split_ids = [m["field_id"] for m in proposals[2]["members"]]
    split_review = families.review_proposal(
        proposals[2]["id"], "split", reason="Demo partition review",
        partitions=[split_ids[:2], split_ids[2:]], evaluator="demo:review",
    )
    reject_review = families.review_proposal(
        proposals[3]["id"], "reject", reason="Demo rejected family hypothesis",
        evaluator="demo:review",
    )

    rows = families.list_families(limit=20)
    return {
        "database": str(path),
        "proposals": len(proposals),
        "reviews": 4,
        "review_decisions": [
            duplicate_review["review"]["decision"], related_review["review"]["decision"],
            split_review["review"]["decision"], reject_review["review"]["decision"],
        ],
        "families_by_type": dict(sorted(Counter(row["family_type"] for row in rows).items())),
        "field_count_before_reviews": fields_before,
        "field_count_after_reviews": int(db.scalar("SELECT COUNT(*) FROM fields") or 0),
        "cell_count_before_reviews": cells_before,
        "cell_count_after_reviews": int(db.scalar("SELECT COUNT(*) FROM cells") or 0),
        "split_created_family": split_review["family"] is not None,
    }


def benchmark_family_registry(
    path: str | Path, field_count: int = 10_000, max_neighbors: int = 6
) -> dict:
    if field_count < 6:
        raise ValueError("field_count must be >= 6")
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    families = FieldFamilyService(db)

    generic_count = field_count - 6
    fields.bulk_create_fields(
        {
            "key": f"f_{hashlib.sha256(str(i).encode()).hexdigest()[:16]}",
            "label": hashlib.sha256(f"label:{i}".encode()).hexdigest()[:18],
            "value_type": "number",
            "description": "",
        }
        for i in range(generic_count)
    )
    planted_a = _create_permutation_group(fields, ("source", "evidence", "quality"))
    planted_b = _create_permutation_group(fields, ("model", "runtime", "latency"))

    start = time.perf_counter()
    proposals = families.scan_registry(
        namespace="global", seed_threshold=0.95, min_coherence=0.95,
        max_neighbors=max_neighbors, max_members=6, limit_fields=field_count,
        max_proposals=20, evaluator="benchmark:family-v1",
    )
    elapsed = time.perf_counter() - start
    member_sets = [{m["field_id"] for m in p["members"]} for p in proposals]
    planted_sets = [{f["id"] for f in planted_a}, {f["id"] for f in planted_b}]
    found = sum(1 for target in planted_sets if target in member_sets)

    return {
        "database": str(path),
        "fields": field_count,
        "naive_all_pairs": field_count * (field_count - 1) // 2,
        "max_neighbors": max_neighbors,
        "bounded_pair_upper_bound": field_count * max_neighbors,
        "proposals": len(proposals),
        "planted_families": 2,
        "planted_families_found": found,
        "elapsed_seconds": round(elapsed, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SEDB v0.3B field-family demo data.")
    parser.add_argument("--db", default="sedb-family-governance-v0.3b.sqlite")
    parser.add_argument("--benchmark-db", default="sedb-family-10k-v0.3b.sqlite")
    parser.add_argument("--fields", type=int, default=10_000)
    parser.add_argument("--max-neighbors", type=int, default=6)
    args = parser.parse_args()
    result = {
        "governance_demo": build_family_demo(args.db),
        "registry_benchmark": benchmark_family_registry(
            args.benchmark_db, args.fields, args.max_neighbors
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

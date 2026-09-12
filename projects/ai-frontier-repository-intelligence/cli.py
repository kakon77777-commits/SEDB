"""CLI for the AI Frontier Repository Intelligence SEDB catalog.

Run from D:\\Ai\\work together\\SEDB with
    PYTHONPATH=current\\src;projects\\ai-frontier-repository-intelligence

Commands (each prints one UTF-8 JSON document):
    init                 idempotent schema bootstrap (fields + task views)
    stats                counts by kind, cells, integrity
    show <entity_id>     one entity with its cells
    find <kind> [k=v]... entities of a kind filtered by equal cell values
    chain <asset_rev_id> provenance chain (FINAL_HANDOFF verification questions)
    taxonomy             seed taxonomy v1 categories (idempotent)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from config import TAXONOMY_V1, TAXONOMY_VERSION, ProjectConfig, default_config
from store import ImmutableConflict, RepoIntelStore, SchemaConflictError, StorageError


def _jsonable(value):
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def category_records():
    recs = []
    for slug, name, parent in TAXONOMY_V1:
        recs.append({
            "entity_id": f"cat_{slug.replace('-', '_')}",
            "kind": "af_category",
            "label": name,
            "values": {
                "af_category_slug": slug,
                "af_display_name": name,
                "af_parent_category_id": f"cat_{parent.replace('-', '_')}" if parent else None,
                "af_taxonomy_version": TAXONOMY_VERSION,
                "af_category_status": "active",
                "af_provenance_source": "system",
            },
        })
    return recs


def build_parser():
    p = argparse.ArgumentParser(description="AI Frontier Repository Intelligence SEDB catalog")
    p.add_argument("--db", type=Path, default=default_config().database_path)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("stats")
    sub.add_parser("taxonomy")
    s = sub.add_parser("show"); s.add_argument("entity_id")
    f = sub.add_parser("find"); f.add_argument("kind"); f.add_argument("filters", nargs="*")
    c = sub.add_parser("chain"); c.add_argument("asset_revision_id")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = ProjectConfig(database_path=args.db)
    try:
        store = RepoIntelStore.open(config)
        if args.command == "init":
            out = {"status": "ready", **_jsonable(store.ensure_schema())}
        elif args.command == "stats":
            out = store.stats()
        elif args.command == "taxonomy":
            store.ensure_schema()
            out = {"status": "seeded", **_jsonable(store.write(category_records(), source="taxonomy-v1-seed", confidence=1.0))}
        elif args.command == "show":
            out = store.get(args.entity_id) or {"status": "not_found", "entity_id": args.entity_id}
        elif args.command == "find":
            filters = dict(f.split("=", 1) for f in args.filters)
            out = {"count": 0, "entities": []}
            found = store.find(args.kind, **filters)
            out = {"count": len(found), "entities": found}
        elif args.command == "chain":
            out = store.provenance_chain(args.asset_revision_id)
        else:  # pragma: no cover
            raise ValueError(args.command)
        code = 0
    except SchemaConflictError as exc:
        out, code = {"status": "schema_conflict", "message": str(exc), "details": exc.details}, 3
    except ImmutableConflict as exc:
        out, code = {"status": "immutable_conflict", "entity_id": exc.entity_id, "differences": exc.differences}, 4
    except StorageError as exc:
        out, code = {"status": exc.reason_code, "message": str(exc)}, 5
    sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

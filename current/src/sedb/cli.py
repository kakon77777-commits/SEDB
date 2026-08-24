from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .db import Database
from .entities import EntityService
from .fields import FieldService
from .server import create_server
from .views import ViewService


DEMO_FIELDS = [
    ("title", "Title", "text"),
    ("year", "Year", "integer"),
    ("verified", "Verified", "boolean"),
    ("country", "Country", "text"),
    ("author_count", "Author count", "integer"),
    ("ai_assisted", "AI assisted", "boolean"),
    ("corpus_size", "Corpus size", "integer"),
    ("source_url", "Source URL", "text"),
    ("notes", "Notes", "text"),
    ("confidence", "Confidence", "number"),
]


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_demo(db_path: str | Path, field_count: int = 10_000) -> dict:
    if field_count < 1:
        raise ValueError("field_count must be >= 1")
    db = Database(db_path)
    fields = FieldService(db)
    entities = EntityService(db)
    views = ViewService(db)
    if views.stats()["fields"] or views.stats()["entities"]:
        raise ValueError("demo database must be empty")

    specs = []
    for index in range(field_count):
        if index < len(DEMO_FIELDS):
            key, label, value_type = DEMO_FIELDS[index]
            specs.append({"key": key, "label": label, "value_type": value_type})
        else:
            specs.append(
                {
                    "key": f"dynamic_{index:05d}",
                    "label": f"Dynamic Field {index:05d}",
                    "value_type": "text",
                    "description": "Unfilled logical field generated for wide-schema demonstration.",
                }
            )
    fields.bulk_create_fields(specs)

    e1 = entities.create_entity(label="AI-Native Research Corpus", kind="research_corpus", entity_id="demo-corpus")
    e2 = entities.create_entity(label="Hyperprolific Researcher Candidate", kind="researcher", entity_id="demo-researcher")
    e3 = entities.create_entity(label="Sparse Comparison Record", kind="record", entity_id="demo-sparse")

    demo_values = {
        e1["id"]: {
            "title": "SEDB 10K-field demonstration",
            "year": 2026,
            "verified": True,
            "notes": "Only a few cells are present although the global field registry is wide.",
        },
        e2["id"]: {
            "country": "Taiwan",
            "ai_assisted": True,
            "corpus_size": 3000,
            "confidence": 0.75,
        },
        e3["id"]: {
            "verified": False,
        },
    }
    existing_keys = {spec["key"] for spec in specs}
    for entity_id, values in demo_values.items():
        for key, value in values.items():
            if key in existing_keys:
                entities.set_cell(entity_id, key, value, source="demo")

    view_keys = [key for key, _, _ in DEMO_FIELDS if key in existing_keys][: min(8, field_count)]
    if view_keys:
        views.create_view("Research Audit", view_keys, query_text="Demo task projection")
    return views.stats()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sedb",
        description="SEDB local-first unbounded dynamic field database",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize an empty SEDB SQLite database")
    init.add_argument("--db", default="sedb.sqlite")

    demo = sub.add_parser("demo", help="create a sparse demonstration database")
    demo.add_argument("--db", default="sedb-demo.sqlite")
    demo.add_argument("--fields", type=int, default=10_000)

    stats = sub.add_parser("stats", help="print database statistics")
    stats.add_argument("--db", default="sedb.sqlite")

    serve = sub.add_parser("serve", help="run the local browser application")
    serve.add_argument("--db", default="sedb.sqlite")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        db = Database(args.db)
        _print_json(ViewService(db).stats())
        return 0
    if args.command == "demo":
        _print_json(build_demo(args.db, args.fields))
        return 0
    if args.command == "stats":
        db = Database(args.db)
        _print_json(ViewService(db).stats())
        return 0
    if args.command == "serve":
        server = create_server(args.db, host=args.host, port=args.port)
        host, port = server.server_address
        print(f"SEDB local UI: http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

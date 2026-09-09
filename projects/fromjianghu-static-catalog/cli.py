from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from config import ProjectConfig, default_config
from source import SourceValidationError, load_catalog
from store import CatalogStore, SchemaConflictError, StorageError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise SourceValidationError("invalid_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    defaults = default_config()
    parser = JsonArgumentParser(description="FromJianghu static SEDB catalog")
    parser.add_argument("--source-root", type=Path, default=defaults.source_root)
    parser.add_argument("--db", type=Path, default=defaults.database_path)
    parser.add_argument(
        "--contract",
        type=Path,
        help="Optional JSON source-hash and expected-count contract for controlled fixtures.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    commands.add_parser("bootstrap")
    commands.add_parser("stats")
    commands.add_parser("classify")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=30)
    show = commands.add_parser("show")
    show.add_argument("entity_id")
    return parser


def _config(args) -> ProjectConfig:
    defaults = default_config()
    source_hashes = dict(defaults.source_hashes)
    expected_counts = dict(defaults.expected_entity_counts)
    if args.contract is not None:
        try:
            payload = json.loads(args.contract.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceValidationError("contract_read_error", str(exc)) from exc
        if not isinstance(payload, dict):
            raise SourceValidationError("invalid_contract", "contract root must be an object")
        source_hashes = payload.get("source_hashes")
        expected_counts = payload.get("expected_entity_counts", payload.get("entity_counts"))
        if not isinstance(source_hashes, dict) or not isinstance(expected_counts, dict):
            raise SourceValidationError(
                "invalid_contract",
                "contract requires source_hashes and expected_entity_counts objects",
            )
    return ProjectConfig(
        source_root=args.source_root,
        database_path=args.db,
        source_hashes=source_hashes,
        expected_entity_counts=expected_counts,
    )


def _diff_payload(plan) -> dict:
    return {
        "new": len(plan.new),
        "unchanged": len(plan.unchanged),
        "conflict": len(plan.conflicts),
        "missing_from_source": len(plan.missing_from_source),
    }


def _details(plan) -> dict:
    return {
        "new_sample": [record.entity_id for record in plan.new[:20]],
        "conflicts": [asdict(item) for item in plan.conflicts[:20]],
        "missing_from_source": [asdict(item) for item in plan.missing_from_source[:20]],
    }


def run_command(args) -> tuple[int, dict]:
    config = _config(args)
    if args.command in {"plan", "bootstrap"}:
        snapshot = load_catalog(config)
        preplan = CatalogStore.read_only_plan(config, snapshot)
        base = {
            "result_version": 1,
            "command": args.command,
            "source": {
                "catalog_fingerprint": snapshot.fingerprint,
                "entity_count": len(snapshot.records),
                "entity_counts": dict(snapshot.entity_counts),
                "source_file_count": len(snapshot.source_hashes),
            },
            "diff": _diff_payload(preplan),
            "details": _details(preplan),
        }
        if args.command == "plan":
            return (4 if preplan.blocked else 0), {
                **base,
                "status": "blocked" if preplan.blocked else "ready",
                "reason_code": "source_conflict" if preplan.blocked else None,
                "database_exists": config.database_path.exists(),
                "write_performed": False,
            }
        if preplan.blocked:
            return 4, {
                **base,
                "status": "blocked",
                "reason_code": "source_conflict",
                "write": {"created_entities": 0, "created_cells": 0},
                "no_op": False,
            }
        store = CatalogStore.open(config)
        schema = store.ensure_schema()
        plan = store.plan(snapshot)
        if plan.blocked:
            return 4, {
                **base,
                "status": "blocked",
                "reason_code": "source_conflict_after_schema_preflight",
                "write": {"created_entities": 0, "created_cells": 0},
                "no_op": False,
                "integrity": store.integrity_check(),
            }
        written = store.apply(plan)
        no_op = not plan.new
        return 0, {
            **base,
            "diff": _diff_payload(plan),
            "status": "no_op" if no_op else "imported",
            "reason_code": None,
            "schema": asdict(schema),
            "write": {
                "created_entities": written.created_entities,
                "created_cells": written.created_cells,
            },
            "no_op": no_op,
            "integrity": written.integrity,
        }

    if not config.database_path.is_file():
        raise StorageError("database_missing", f"database not found: {config.database_path}")
    store = CatalogStore.open(config)
    store.ensure_schema()
    if args.command == "stats":
        return 0, {
            "result_version": 1,
            "command": "stats",
            "status": "ok",
            "stats": store.stats(),
        }
    if args.command == "classify":
        return 0, {
            "result_version": 1,
            "command": "classify",
            "status": "ok",
            "classification": store.classify(),
            "integrity": store.integrity_check(),
        }
    if args.command == "search":
        return 0, {
            "result_version": 1,
            "command": "search",
            "status": "ok",
            "query": args.query,
            "results": store.views.search(args.query, limit=args.limit),
            "integrity": store.integrity_check(),
        }
    if args.command == "show":
        return 0, {
            "result_version": 1,
            "command": "show",
            "status": "ok",
            "entity": store.entities.get_entity(args.entity_id),
            "integrity": store.integrity_check(),
        }
    raise SourceValidationError("invalid_arguments", f"unsupported command: {args.command}")


def _error_payload(command, reason_code, message, details):
    return {
        "result_version": 1,
        "command": command,
        "status": "error",
        "reason_code": reason_code,
        "message": message,
        "details": details,
    }


def _configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    encoding = str(getattr(sys.stdout, "encoding", "") or "").replace("-", "").casefold()
    if callable(reconfigure) and encoding not in {"utf8", "utf8sig"}:
        reconfigure(encoding="utf-8", errors="strict")


def main(argv=None) -> int:
    _configure_stdout_utf8()
    args = None
    try:
        args = build_parser().parse_args(argv)
        code, payload = run_command(args)
    except SourceValidationError as exc:
        code = 2
        payload = _error_payload(
            getattr(args, "command", None), exc.reason_code, str(exc), exc.details
        )
    except SchemaConflictError as exc:
        code = 3
        payload = _error_payload(
            getattr(args, "command", None), exc.reason_code, str(exc), exc.details
        )
    except StorageError as exc:
        code = 5
        payload = _error_payload(
            getattr(args, "command", None), exc.reason_code, str(exc), exc.details
        )
    except Exception as exc:
        code = 1
        payload = _error_payload(
            getattr(args, "command", None), "unexpected_error", str(exc), []
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

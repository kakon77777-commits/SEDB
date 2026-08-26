from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from config import ProjectConfig, default_config
from source import SourceValidationError, load_month
from store import CorpusStore, SchemaConflictError, StorageError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise SourceValidationError("invalid_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Unbounded Axiom corpus SEDB month bootstrap"
    )
    defaults = default_config()
    parser.add_argument(
        "--source",
        type=Path,
        default=defaults.source_registry,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=defaults.database_path,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("init")
    bootstrap = subcommands.add_parser("bootstrap")
    bootstrap.add_argument("--month", required=True)
    subcommands.add_parser("stats")
    return parser


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _jsonable(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def plan_details(plan):
    return {
        "new": [paper.paper_id for paper in plan.new],
        "unchanged": list(plan.unchanged),
        "conflicts": _jsonable(plan.conflicts),
        "missing_from_source": _jsonable(plan.missing_from_source),
    }


def run_command(args) -> tuple[int, dict]:
    config = ProjectConfig(args.source, args.db)
    store = CorpusStore.open(config)

    if args.command == "init":
        result = store.ensure_schema()
        return 0, {
            "result_version": 1,
            "command": "init",
            "status": "initialized",
            "reason_code": None,
            "init": _jsonable(result),
        }

    if args.command == "stats":
        store.ensure_schema()
        return 0, {
            "result_version": 1,
            "command": "stats",
            "status": "ok",
            "reason_code": None,
            "stats": store.stats(),
        }

    init = store.ensure_schema()
    selected = load_month(config.source_registry, args.month)
    plan = store.plan(selected)
    counts = {
        "new": len(plan.new),
        "unchanged": len(plan.unchanged),
        "conflict": len(plan.conflicts),
        "missing_from_source": len(plan.missing_from_source),
    }
    base = {
        "result_version": 1,
        "command": "bootstrap",
        "source": {
            "registry_version": selected.registry_version,
            "registry_count": selected.registry_count,
            "month": selected.month,
            "selected_count": len(selected.papers),
        },
        "diff": counts,
        "details": plan_details(plan),
        "init": _jsonable(init),
    }

    if plan.blocked:
        reasons = [item.reason_code for item in plan.conflicts]
        if "month_reassignment" in reasons:
            reason = "month_reassignment"
        elif plan.conflicts:
            reason = "source_conflict"
        else:
            reason = "missing_from_source"
        return 4, {
            **base,
            "status": "blocked",
            "reason_code": reason,
            "write": {
                "created_entities": 0,
                "created_cells": 0,
            },
            "no_op": False,
            "integrity": store.integrity_check(),
        }

    written = store.apply(plan)
    no_op = not plan.new
    return 0, {
        **base,
        "status": "no_op" if no_op else "imported",
        "reason_code": None,
        "write": {
            "created_entities": written.created_entities,
            "created_cells": written.created_cells,
        },
        "no_op": no_op,
        "integrity": written.integrity,
    }


def _error_payload(command, reason_code, message, details):
    return {
        "result_version": 1,
        "command": command,
        "status": "error",
        "reason_code": reason_code,
        "message": message,
        "details": details,
    }


def main(argv=None) -> int:
    args = None
    try:
        args = build_parser().parse_args(argv)
        code, payload = run_command(args)
    except SourceValidationError as exc:
        code = 2
        payload = _error_payload(
            getattr(args, "command", None),
            exc.reason_code,
            str(exc),
            exc.details,
        )
    except SchemaConflictError as exc:
        code = 3
        payload = _error_payload(
            getattr(args, "command", None),
            "schema_conflict",
            str(exc),
            exc.details,
        )
    except StorageError as exc:
        code = 5
        payload = _error_payload(
            getattr(args, "command", None),
            exc.reason_code,
            str(exc),
            exc.details,
        )
    except Exception as exc:
        code = 1
        payload = _error_payload(
            getattr(args, "command", None),
            "unexpected_error",
            str(exc),
            [],
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Sequence

from config import ProjectConfig, default_config
from store import (
    PROJECT_ENTITY_KINDS,
    CanonStore,
    DiffPlan,
    SchemaConflictError,
    StorageError,
)
from source import SourceValidationError, load_snapshot


class CLIUsageError(ValueError):
    pass


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIUsageError(message)


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def _emit(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(
        prog="wanxiang-character-canon",
        description="Read-only source adapter and local SEDB character canon.",
    )
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--db", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize and verify project fields/views.")

    plan = commands.add_parser("plan", help="Compute a read-only source diff.")
    plan.add_argument("--build", type=int)
    bootstrap = commands.add_parser(
        "bootstrap", help="Validate and atomically create missing records."
    )
    bootstrap.add_argument("--build", type=int)

    commands.add_parser("stats", help="Report project and database counts.")
    search = commands.add_parser("search", help="Search canon records and stored links.")
    search.add_argument("query")
    show = commands.add_parser("show", help="Show one record and stored links.")
    show.add_argument("entity_id")
    commands.add_parser("unresolved", help="List gap and ambiguous candidate records.")
    return parser


def _config_from_args(args, base: ProjectConfig) -> ProjectConfig:
    return replace(
        base,
        source_root=args.source_root or base.source_root,
        database_path=args.db or base.database_path,
        build_id=getattr(args, "build", None) or base.build_id,
    )


def _plan_payload(plan: DiffPlan) -> dict[str, Any]:
    conflicts = [
        {
            "entity_id": conflict.entity_id,
            "reason_code": conflict.reason_code,
            "differences": [asdict(difference) for difference in conflict.differences],
        }
        for conflict in plan.conflicts
    ]
    return {
        "build_id": plan.build_id,
        "new": len(plan.new),
        "new_entity_ids": [entity.entity_id for entity in plan.new],
        "unchanged": len(plan.unchanged),
        "conflicts": conflicts,
        "missing_from_source": list(plan.missing_from_source),
        "blocked": plan.blocked,
        "source_fingerprint": plan.source_fingerprint,
    }


def _blocked_reason(plan: DiffPlan) -> str:
    if plan.conflicts:
        return plan.conflicts[0].reason_code
    if plan.missing_from_source:
        return "missing_from_source"
    return "blocked_plan"


def _load_records(store: CanonStore) -> dict[str, dict[str, Any]]:
    kinds = sorted(PROJECT_ENTITY_KINDS)
    marks = ",".join("?" for _ in kinds)
    with store.db.connect() as conn:
        records = {
            row["id"]: {
                "id": row["id"],
                "kind": row["kind"],
                "label": row["label"],
                "values": {},
            }
            for row in conn.execute(
                f"SELECT id,kind,label FROM entities WHERE kind IN ({marks})",
                tuple(kinds),
            ).fetchall()
        }
        if records:
            rows = conn.execute(
                f"""
                SELECT c.entity_id,f.key,c.value_json
                FROM cells c
                JOIN fields f ON f.id=c.field_id
                JOIN entities e ON e.id=c.entity_id
                WHERE f.namespace=? AND e.kind IN ({marks})
                """,
                (store.config.namespace, *kinds),
            ).fetchall()
            for row in rows:
                if row["entity_id"] in records:
                    records[row["entity_id"]]["values"][row["key"]] = json.loads(
                        row["value_json"]
                    )
    return records


def _record_matches(record: dict[str, Any], query: str) -> bool:
    needle = query.casefold()
    if needle in record["id"].casefold() or needle in record["label"].casefold():
        return True
    projection = json.dumps(record["values"], ensure_ascii=False, sort_keys=True)
    return needle in projection.casefold()


def _linked_ids(
    record: dict[str, Any], records: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    identities: set[str] = set()
    forms: set[str] = set()
    assets: set[str] = set()
    unresolved: set[str] = set()
    values = record["values"]

    if record["kind"] == "wanxiang_character_identity":
        forms.update(
            entity_id
            for entity_id in values.get("linked_form_ids", [])
            if entity_id in records
        )
    elif record["kind"] == "wanxiang_character_form_snapshot":
        identity_id = values.get("identity_entity_id")
        if identity_id in records:
            identities.add(identity_id)
        forms.add(record["id"])
    elif record["kind"] in {
        "wanxiang_visual_asset_snapshot",
        "wanxiang_visual_candidate_snapshot",
        "wanxiang_source_gap_snapshot",
    }:
        numeric_id = values.get("resource_numeric_id", values.get("hero_id"))
        if numeric_id is not None:
            forms.update(
                item["id"]
                for item in records.values()
                if item["kind"] == "wanxiang_character_form_snapshot"
                and item["values"].get("hero_id") == numeric_id
            )

    hero_ids = {
        records[form_id]["values"].get("hero_id")
        for form_id in forms
        if form_id in records
    }
    hero_ids.discard(None)
    for form_id in tuple(forms):
        identity_id = records[form_id]["values"].get("identity_entity_id")
        if identity_id in records:
            identities.add(identity_id)
    for item in records.values():
        item_values = item["values"]
        item_numeric_id = item_values.get(
            "resource_numeric_id", item_values.get("hero_id")
        )
        if item_numeric_id not in hero_ids:
            continue
        if item["kind"] == "wanxiang_visual_asset_snapshot":
            assets.add(item["id"])
        elif item["kind"] in {
            "wanxiang_visual_candidate_snapshot",
            "wanxiang_source_gap_snapshot",
        }:
            unresolved.add(item["id"])
    return {
        "identities": identities,
        "forms": forms,
        "assets": assets,
        "unresolved": unresolved,
    }


def _search(store: CanonStore, query: str, *, limit: int = 200) -> list[dict[str, Any]]:
    records = _load_records(store)
    matched = {
        entity_id
        for entity_id, record in records.items()
        if _record_matches(record, query)
    }
    expanded = set(matched)
    for entity_id in tuple(matched):
        links = _linked_ids(records[entity_id], records)
        for linked in links.values():
            expanded.update(linked)
    return [
        records[entity_id]
        for entity_id in sorted(
            expanded,
            key=lambda item: (
                records[item]["kind"],
                records[item]["label"],
                item,
            ),
        )[:limit]
    ]


def _show(store: CanonStore, entity_id: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    records = _load_records(store)
    record = records.get(entity_id)
    if record is None:
        raise KeyError(f"entity not found: {entity_id}")
    links = _linked_ids(record, records)
    entity = store.entities.get_entity(entity_id)
    return entity, {key: sorted(value) for key, value in links.items()}


def _unresolved(store: CanonStore) -> list[dict[str, Any]]:
    records = _load_records(store)
    return sorted(
        (
            record
            for record in records.values()
            if record["kind"]
            in {
                "wanxiang_source_gap_snapshot",
                "wanxiang_visual_candidate_snapshot",
            }
        ),
        key=lambda record: (record["kind"], record["label"], record["id"]),
    )


def _run(args, config: ProjectConfig) -> tuple[int, dict[str, Any]]:
    if args.command == "init":
        result = CanonStore.open(config).ensure_schema()
        return 0, {"status": "initialized", **asdict(result)}

    if args.command == "plan":
        selection = load_snapshot(config)
        plan = CanonStore.open(config).plan(selection)
        payload = _plan_payload(plan)
        if plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(plan),
                **payload,
            }
        return 0, {"status": "ready", **payload}

    if args.command == "bootstrap":
        first_selection = load_snapshot(config)
        store = CanonStore.open(config)
        initialized = store.ensure_schema()
        first_plan = store.plan(first_selection)
        if first_plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(first_plan),
                **_plan_payload(first_plan),
            }

        verified_selection = load_snapshot(config)
        verified_plan = store.plan(verified_selection)
        if verified_plan.source_fingerprint != first_plan.source_fingerprint:
            return 3, {
                "status": "blocked",
                "reason_code": "source_changed_during_bootstrap",
                "initial_fingerprint": first_plan.source_fingerprint,
                "verified_fingerprint": verified_plan.source_fingerprint,
            }
        if verified_plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(verified_plan),
                **_plan_payload(verified_plan),
            }
        written = store.apply(verified_plan)
        return 0, {
            "status": "created" if written.created_entities else "no_op",
            "build_id": verified_plan.build_id,
            "source_fingerprint": written.source_fingerprint,
            "created_entities": written.created_entities,
            "created_cells": written.created_cells,
            "integrity": written.integrity,
            "schema": asdict(initialized),
        }

    store = CanonStore.open(config)
    if args.command == "stats":
        return 0, {"status": "ok", **store.stats()}
    if args.command == "search":
        results = _search(store, args.query)
        return 0, {
            "status": "ok",
            "query": args.query,
            "count": len(results),
            "results": results,
        }
    if args.command == "show":
        entity, links = _show(store, args.entity_id)
        return 0, {"status": "ok", "entity": entity, "links": links}
    if args.command == "unresolved":
        results = _unresolved(store)
        return 0, {"status": "ok", "count": len(results), "results": results}
    raise CLIUsageError(f"unsupported command: {args.command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    base_config: ProjectConfig | None = None,
) -> int:
    _configure_utf8()
    try:
        args = _parser().parse_args(argv)
        config = _config_from_args(args, base_config or default_config())
        exit_code, payload = _run(args, config)
    except SourceValidationError as exc:
        exit_code = 2
        payload = {
            "status": "error",
            "reason_code": exc.reason_code,
            "message": str(exc),
        }
    except CLIUsageError as exc:
        exit_code = 2
        payload = {
            "status": "error",
            "reason_code": "usage_error",
            "message": str(exc),
        }
    except SchemaConflictError as exc:
        exit_code = 3
        payload = {
            "status": "blocked",
            "reason_code": exc.reason_code,
            "message": str(exc),
            "details": exc.details,
        }
    except StorageError as exc:
        conflict_codes = {
            "blocked_plan",
            "build_id_mismatch",
            "duplicate_source_entity",
            "invalid_source_entity",
        }
        exit_code = 3 if exc.reason_code in conflict_codes else 4
        payload = {
            "status": "blocked" if exit_code == 3 else "error",
            "reason_code": exc.reason_code,
            "message": str(exc),
            "details": exc.details,
        }
    except KeyError as exc:
        exit_code = 4
        payload = {
            "status": "error",
            "reason_code": "not_found",
            "message": str(exc),
        }
    except Exception as exc:
        exit_code = 4
        payload = {
            "status": "error",
            "reason_code": "storage_failure",
            "message": str(exc),
        }
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

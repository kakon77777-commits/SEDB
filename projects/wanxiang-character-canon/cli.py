from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Sequence

from catalog_config import CatalogContract, default_catalog_contract
from catalog_source import CatalogSourceError, compose_full_catalog
from backup import BackupError, create_verified_backup
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


SUMMARY_VALUE_KEYS = (
    "normalized_name_key",
    "identity_status",
    "linked_form_ids",
    "identity_entity_id",
    "hero_id",
    "name_zh",
    "role_class",
    "resource_numeric_id",
    "resource_path",
    "mapping_status",
    "extraction_status",
    "png_path",
    "related_expected_path",
    "gap_kind",
    "gap_expected_path",
    "gap_reason",
    "source_table",
    "source_record_id",
    "source_row",
    "source_row_sha256",
    "next_dialog_id",
    "next_event_id",
    "guide_steps",
    "edge_source_entity_id",
    "edge_source_table",
    "edge_source_field",
    "edge_slot",
    "edge_target_table",
    "edge_target_source_id",
    "edge_target_entity_id",
    "edge_resolution_status",
    "edge_rule_id",
)


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
    catalog_plan = commands.add_parser(
        "catalog-plan", help="Compute a read-only full static-catalog diff."
    )
    catalog_plan.add_argument("--build", type=int)
    catalog_bootstrap = commands.add_parser(
        "catalog-bootstrap",
        help="Atomically add the full static catalog and reference graph.",
    )
    catalog_bootstrap.add_argument("--build", type=int)

    commands.add_parser("stats", help="Report project and database counts.")
    search = commands.add_parser("search", help="Search canon records and stored links.")
    search.add_argument("query")
    show = commands.add_parser("show", help="Show one record and stored links.")
    show.add_argument("entity_id")
    commands.add_parser("unresolved", help="List gap and ambiguous candidate records.")
    table = commands.add_parser("table", help="List compact records from one AllExcel table.")
    table.add_argument("table")
    table.add_argument("--id", dest="source_id")
    table.add_argument("--limit", type=int, default=50)
    edges = commands.add_parser("edges", help="List static reference edges for an entity.")
    edges.add_argument("entity_id")
    edges.add_argument("--direction", choices=("in", "out", "both"), default="both")
    edges.add_argument("--limit", type=int, default=200)
    dialog = commands.add_parser("dialog", help="Show one complete EventDialog row.")
    dialog.add_argument("dialog_id")
    route = commands.add_parser("route", help="Show one Relation row and its edges.")
    route.add_argument("relation_id")
    return parser


def _config_from_args(args, base: ProjectConfig) -> ProjectConfig:
    return replace(
        base,
        source_root=args.source_root or base.source_root,
        database_path=args.db or base.database_path,
        build_id=getattr(args, "build", None) or base.build_id,
    )


def _plan_payload(plan: DiffPlan) -> dict[str, Any]:
    new_entity_ids = [entity.entity_id for entity in plan.new]
    sample_limit = 20
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
        "new_entity_id_sample": new_entity_ids[:sample_limit],
        "new_entity_ids_omitted": max(0, len(new_entity_ids) - sample_limit),
        "enrich": len(plan.enrich),
        "enrich_entity_id_sample": [
            item.entity_id for item in plan.enrich[:sample_limit]
        ],
        "enrich_entity_ids_omitted": max(0, len(plan.enrich) - sample_limit),
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


def _record_summary(record: dict[str, Any], *, match: str = "") -> dict[str, Any]:
    result = {
        "id": record["id"],
        "kind": record["kind"],
        "label": record["label"],
        "values": {
            key: record["values"][key]
            for key in SUMMARY_VALUE_KEYS
            if key in record["values"]
        },
    }
    if match:
        result["match"] = match
    return result


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
        _record_summary(
            records[entity_id],
            match="direct" if entity_id in matched else "stored_link",
        )
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
    return [
        _record_summary(record)
        for record in sorted(
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
    ]


def _source_id_matches(value: Any, query: str) -> bool:
    if str(value) == query:
        return True
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == query


def _table_records(
    store: CanonStore,
    table: str,
    *,
    source_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    records = _load_records(store)
    matched = [
        record
        for record in records.values()
        if str(record["values"].get("source_table", "")).casefold()
        == table.casefold()
        and (
            source_id is None
            or _source_id_matches(
                record["values"].get("source_record_id"), source_id
            )
        )
    ]
    matched.sort(
        key=lambda record: (
            record["values"].get("source_row", 0),
            record["id"],
        )
    )
    return [_record_summary(record) for record in matched[: max(1, min(limit, 500))]]


def _edge_listing(
    store: CanonStore,
    entity_id: str,
    *,
    direction: str = "both",
    limit: int = 200,
) -> dict[str, Any]:
    records = _load_records(store)
    if entity_id not in records:
        raise KeyError(f"entity not found: {entity_id}")
    edges = []
    for record in records.values():
        if record["kind"] != "wanxiang_reference_edge_snapshot":
            continue
        values = record["values"]
        outgoing = values.get("edge_source_entity_id") == entity_id
        incoming = values.get("edge_target_entity_id") == entity_id
        if (direction in {"out", "both"} and outgoing) or (
            direction in {"in", "both"} and incoming
        ):
            edges.append(record)
    edges.sort(key=lambda record: record["id"])
    bounded = edges[: max(1, min(limit, 1000))]
    return {
        "entity_id": entity_id,
        "direction": direction,
        "count": len(edges),
        "results": [_record_summary(record) for record in bounded],
        "omitted": max(0, len(edges) - len(bounded)),
    }


def _full_table_record(
    store: CanonStore,
    table: str,
    source_id: str,
) -> dict[str, Any]:
    records = _table_records(store, table, source_id=source_id, limit=2)
    if len(records) != 1:
        raise KeyError(f"{table} record not found or ambiguous: {source_id}")
    return store.entities.get_entity(records[0]["id"])


def _run(
    args,
    config: ProjectConfig,
    catalog_contract: CatalogContract,
) -> tuple[int, dict[str, Any]]:
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

    if args.command == "catalog-plan":
        selection = compose_full_catalog(
            config,
            catalog_contract,
            include_edges=True,
        )
        plan = CanonStore.open(config).plan(selection)
        payload = {
            **_plan_payload(plan),
            "pre_edge_entities": (
                len(selection.entities)
                - selection.counts.get("wanxiang_reference_edge_snapshot", 0)
            ),
            "edge_count": selection.counts.get(
                "wanxiang_reference_edge_snapshot", 0
            ),
            "full_entities": len(selection.entities),
        }
        if plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(plan),
                **payload,
            }
        return 0, {"status": "ready", **payload}

    if args.command == "catalog-bootstrap":
        first_selection = compose_full_catalog(
            config,
            catalog_contract,
            include_edges=True,
        )
        store = CanonStore.open(config)
        initialized = store.ensure_schema()
        first_plan = store.plan(first_selection)
        if first_plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(first_plan),
                **_plan_payload(first_plan),
            }
        verified_selection = compose_full_catalog(
            config,
            catalog_contract,
            include_edges=True,
        )
        verified_plan = store.plan(verified_selection)
        if verified_plan.source_fingerprint != first_plan.source_fingerprint:
            return 3, {
                "status": "blocked",
                "reason_code": "source_changed_during_catalog_bootstrap",
                "initial_fingerprint": first_plan.source_fingerprint,
                "verified_fingerprint": verified_plan.source_fingerprint,
            }
        if verified_plan.blocked:
            return 3, {
                "status": "blocked",
                "reason_code": _blocked_reason(verified_plan),
                **_plan_payload(verified_plan),
            }
        backup_payload = None
        if verified_plan.new or verified_plan.enrich:
            existing_entities = int(
                store.db.scalar("SELECT COUNT(*) FROM entities") or 0
            )
            catalog_entities = int(
                store.db.scalar(
                    """
                    SELECT COUNT(*) FROM entities
                    WHERE kind IN (
                        'wanxiang_table_row_snapshot',
                        'wanxiang_treasure_snapshot',
                        'wanxiang_hero_sentinel_snapshot',
                        'wanxiang_reference_edge_snapshot'
                    )
                    """
                )
                or 0
            )
            if existing_entities and catalog_entities == 0:
                backup_path = (
                    config.database_path.parent
                    / "local-backups"
                    / f"wave1-{config.build_id}.sqlite"
                )
                backup_result = create_verified_backup(config, backup_path)
                backup_payload = {
                    **asdict(backup_result),
                    "path": str(backup_result.path),
                }
        written = store.apply(verified_plan)
        return 0, {
            "status": (
                "created"
                if written.created_entities or written.enriched_entities
                else "no_op"
            ),
            "build_id": verified_plan.build_id,
            "source_fingerprint": written.source_fingerprint,
            "created_entities": written.created_entities,
            "enriched_entities": written.enriched_entities,
            "created_cells": written.created_cells,
            "integrity": written.integrity,
            "pre_edge_entities": (
                len(verified_selection.entities)
                - verified_selection.counts.get(
                    "wanxiang_reference_edge_snapshot", 0
                )
            ),
            "edge_count": verified_selection.counts.get(
                "wanxiang_reference_edge_snapshot", 0
            ),
            "full_entities": len(verified_selection.entities),
            "schema": asdict(initialized),
            "backup": backup_payload,
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
    if args.command == "table":
        results = _table_records(
            store,
            args.table,
            source_id=args.source_id,
            limit=args.limit,
        )
        return 0, {
            "status": "ok",
            "table": args.table,
            "source_id": args.source_id,
            "count": len(results),
            "results": results,
        }
    if args.command == "edges":
        return 0, {
            "status": "ok",
            **_edge_listing(
                store,
                args.entity_id,
                direction=args.direction,
                limit=args.limit,
            ),
        }
    if args.command == "dialog":
        entity = _full_table_record(store, "EventDialog", args.dialog_id)
        return 0, {
            "status": "ok",
            "entity": entity,
            "edges": _edge_listing(store, entity["id"], direction="out"),
        }
    if args.command == "route":
        entity = _full_table_record(store, "Relation", args.relation_id)
        return 0, {
            "status": "ok",
            "entity": entity,
            "edges": _edge_listing(store, entity["id"], direction="out"),
        }
    raise CLIUsageError(f"unsupported command: {args.command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    base_config: ProjectConfig | None = None,
    base_catalog_contract: CatalogContract | None = None,
) -> int:
    _configure_utf8()
    try:
        args = _parser().parse_args(argv)
        config = _config_from_args(args, base_config or default_config())
        exit_code, payload = _run(
            args,
            config,
            base_catalog_contract or default_catalog_contract(),
        )
    except (SourceValidationError, CatalogSourceError) as exc:
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
    except BackupError as exc:
        exit_code = 4
        payload = {
            "status": "error",
            "reason_code": exc.reason_code,
            "message": str(exc),
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

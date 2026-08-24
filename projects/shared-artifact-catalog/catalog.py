from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from copy_artifact import copy_artifact
from export_catalog import write_catalog
from ingest import ingest_registered_packages
from paths import CatalogConfig
from schema import CatalogStore
from taxonomy import (
    propose_category,
    register_additive_category,
    search_records,
    show_record,
)
from temporal import CtclClient, create_temporal_anchor, reconcile_pending
from translation import complete_translation, start_translation


DEFAULT_CONFIG = Path(__file__).with_name("catalog-config.json")


def _config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SEDB shared artifact catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    _config_argument(init)

    ingest = subparsers.add_parser("ingest")
    _config_argument(ingest)

    export = subparsers.add_parser("export")
    export.add_argument("--output", type=Path)
    _config_argument(export)

    reconcile = subparsers.add_parser("reconcile-time")
    _config_argument(reconcile)

    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--category")
    search.add_argument("--language")
    _config_argument(search)

    show = subparsers.add_parser("show")
    show.add_argument("record_id")
    _config_argument(show)

    propose = subparsers.add_parser("propose-category")
    propose.add_argument("--key", required=True)
    propose.add_argument("--definition", required=True)
    propose.add_argument("--examples", nargs="+", required=True)
    propose.add_argument("--why", required=True)
    propose.add_argument("--proposer-claim", default="")
    propose.add_argument("--host-task-id", default="unresolved")
    propose.add_argument("--parent-category-id", default="")
    _config_argument(propose)

    register = subparsers.add_parser("register-category")
    register.add_argument("proposal_id")
    register.add_argument("--registrar", required=True)
    _config_argument(register)

    copy_command = subparsers.add_parser("copy")
    copy_command.add_argument("record_id")
    copy_command.add_argument("--destination", type=Path, required=True)
    copy_command.add_argument(
        "--mode",
        choices=["package", "component", "dependency_closure"],
        required=True,
    )
    copy_command.add_argument("--include-required", action="store_true")
    copy_command.add_argument("--purpose", required=True)
    copy_command.add_argument("--responsibility-ref", required=True)
    copy_command.add_argument("--requester-claim", default="")
    copy_command.add_argument("--host-task-id", default="unresolved")
    _config_argument(copy_command)

    translate_start = subparsers.add_parser("translate-start")
    translate_start.add_argument("source_component_id")
    translate_start.add_argument("--target-language", required=True)
    translate_start.add_argument("--scope", required=True)
    translate_start.add_argument("--translator-claim", default="")
    translate_start.add_argument("--host-task-id", default="unresolved")
    _config_argument(translate_start)

    translate_complete = subparsers.add_parser("translate-complete")
    translate_complete.add_argument("job_id")
    translate_complete.add_argument("--translator-claim", default="")
    translate_complete.add_argument("--host-task-id", default="unresolved")
    _config_argument(translate_complete)
    return parser


def _open(config_path: Path) -> tuple[CatalogConfig, CatalogStore]:
    config = CatalogConfig.load(config_path)
    store = CatalogStore.open(config.database_path)
    store.ensure_schema()
    return config, store


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config, store = _open(args.config)
        if args.command == "init":
            translation_root = config.catalog_root / config.translation_zone
            translation_root.mkdir(parents=True, exist_ok=True)
            result = {
                "database_path": str(config.database_path),
                "translation_workspace": str(translation_root),
                "initialized": True,
            }
        elif args.command == "ingest":
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            result = asdict(
                ingest_registered_packages(config, store, client)
            )
        elif args.command == "export":
            output = args.output or (
                config.catalog_root / "ARTIFACT_CATALOG.md"
            )
            result = asdict(write_catalog(store, output))
        elif args.command == "reconcile-time":
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            result = reconcile_pending(store, client)
        elif args.command == "search":
            result = search_records(
                store,
                args.query,
                category=args.category,
                language=args.language,
            )
        elif args.command == "show":
            result = show_record(store, args.record_id)
        elif args.command == "propose-category":
            result = propose_category(
                store,
                key=args.key,
                definition=args.definition,
                examples=args.examples,
                insufficiency_reason=args.why,
                proposer_claim=args.proposer_claim,
                host_task_id=args.host_task_id,
                parent_category_id=args.parent_category_id,
            )
        elif args.command == "register-category":
            proposal = store.get_record(args.proposal_id)
            if proposal["kind"] != "classification_proposal":
                raise ValueError("proposal id is not a classification proposal")
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            anchor = create_temporal_anchor(
                store,
                client,
                "taxonomy_registration",
                timezone_name=config.timezone,
            )
            values = proposal["values"]
            result = register_additive_category(
                store,
                values["stable_key"],
                values["title"],
                values["definition"],
                values.get("parent_category_id", ""),
                args.registrar,
                anchor["id"],
            )
        elif args.command == "copy":
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            result = asdict(
                copy_artifact(
                    store=store,
                    config=config,
                    record_id=args.record_id,
                    destination=args.destination,
                    mode=args.mode,
                    include_required=args.include_required,
                    purpose=args.purpose,
                    responsibility_ref=args.responsibility_ref,
                    requester_claim=args.requester_claim,
                    host_task_id=args.host_task_id,
                    temporal_client=client,
                )
            )
        elif args.command == "translate-start":
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            result = asdict(
                start_translation(
                    store=store,
                    config=config,
                    source_component_id=args.source_component_id,
                    target_language=args.target_language,
                    translation_scope=args.scope,
                    translator_claim=args.translator_claim,
                    host_task_id=args.host_task_id,
                    temporal_client=client,
                )
            )
        elif args.command == "translate-complete":
            client = CtclClient(
                config.ctcl_base_url, config.ctcl_timeout_seconds
            )
            result = asdict(
                complete_translation(
                    store=store,
                    config=config,
                    job_id=args.job_id,
                    translator_claim=args.translator_claim,
                    host_task_id=args.host_task_id,
                    temporal_client=client,
                )
            )
        else:
            raise ValueError(f"unsupported command: {args.command}")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=_json_default,
            )
        )
        return 0
    except (KeyError, ValueError, PermissionError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

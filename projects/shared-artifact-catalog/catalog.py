from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from paths import CatalogConfig
from schema import CatalogStore
from taxonomy import (
    propose_category,
    register_additive_category,
    search_records,
    show_record,
)
from temporal import CtclClient, create_temporal_anchor


DEFAULT_CONFIG = Path(__file__).with_name("catalog-config.json")


def _config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SEDB shared artifact catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        if args.command == "search":
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

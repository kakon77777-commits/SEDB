from __future__ import annotations

import argparse
import json

from sedb.cli import build_demo


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sparse SEDB demonstration database.")
    parser.add_argument("--db", default="sedb-demo.sqlite")
    parser.add_argument("--fields", type=int, default=10_000)
    args = parser.parse_args()
    stats = build_demo(args.db, args.fields)
    print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

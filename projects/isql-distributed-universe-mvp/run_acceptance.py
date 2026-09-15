from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from isql_distributed_universe_mvp import (
    SyntheticUniverseConfig,
    acceptance_passes,
    run_synthetic_acceptance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the D15 distributed-universe synthetic acceptance harness")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--objects", type=int, default=256)
    parser.add_argument("--topics", type=int, default=16)
    parser.add_argument("--active", type=int, default=4)
    parser.add_argument("--artifact-size", type=int, default=4096)
    parser.add_argument("--chunk-size", type=int, default=256)
    parser.add_argument("--range-offset", type=int, default=64)
    parser.add_argument("--range-length", type=int, default=64)
    args = parser.parse_args()

    config = SyntheticUniverseConfig(
        object_count=args.objects,
        topic_count=args.topics,
        active_entities=args.active,
        artifact_size=args.artifact_size,
        chunk_size=args.chunk_size,
        range_offset=args.range_offset,
        range_length=args.range_length,
    )

    if args.workdir is None:
        with tempfile.TemporaryDirectory() as td:
            report = run_synthetic_acceptance(Path(td), config)
    else:
        args.workdir.mkdir(parents=True, exist_ok=True)
        report = run_synthetic_acceptance(args.workdir, config)

    payload = report.to_dict()
    payload["report_sha256"] = report.report_sha256
    payload["acceptance_passed"] = acceptance_passes(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["acceptance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

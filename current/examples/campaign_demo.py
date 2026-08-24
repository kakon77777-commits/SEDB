from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from sedb.agent import AgentService
from sedb.campaign import CampaignService
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService


def _reset(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        path.unlink()
    return path


def _external_packet(key: str, label: str, value_type: str, evidence: str) -> dict:
    return {
        "suggestions": [
            {
                "key": key,
                "label": label,
                "value_type": value_type,
                "reason": f"campaign evidence {evidence}",
                "confidence": 0.9,
                "evidence_refs": [evidence],
            }
        ]
    }


def _link(campaigns: CampaignService, campaign_id: str, payload: dict, run: dict, label: str) -> None:
    work = campaigns.add_work_item(campaign_id, payload)
    campaigns.link_run(campaign_id, work["id"], run["id"], agent_label=label)


def build_campaign_demo(path: str | Path) -> dict:
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    agents = AgentService(db)
    campaigns = CampaignService(db)

    paper = fields.create_field(key="paper", label="Paper")
    fields.create_field(key="country", label="Country")
    entity = entities.create_entity(label="Existing paper", kind="paper")
    entities.set_cell(entity["id"], paper["key"], "P000", source="demo")

    before_fields = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    before_cells = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)
    campaign = campaigns.create_campaign(
        name="Multi-Agent Field Review",
        task_text="Compare independent advisory suggestions without canonical mutation.",
        budget={"max_runs": 12, "max_work_items": 12, "max_agent_steps": 100, "max_proposals": 20, "max_cost_units": 20},
        evaluator="demo:campaign",
    )

    observation = {"publication_type": "preprint"}
    run1 = agents.run_deterministic(observation, score_proposals=False, assess_existing=False)
    run2 = agents.run_deterministic(observation, score_proposals=False, assess_existing=False)
    run3 = agents.run_external(
        _external_packet("publication_type", "Publication Type", "text", "external:publication-type"),
        score_proposals=False,
        assess_existing=False,
    )
    _link(campaigns, campaign["id"], observation, run1, "det-a")
    _link(campaigns, campaign["id"], observation, run2, "det-b")
    _link(campaigns, campaign["id"], {"source": "external-publication"}, run3, "ext-c")

    run4 = agents.run_external(
        _external_packet("review_status", "Review Status", "text", "external:review-text"),
        score_proposals=False,
        assess_existing=False,
    )
    run5 = agents.run_external(
        _external_packet("review_status", "Review Status", "boolean", "external:review-bool"),
        score_proposals=False,
        assess_existing=False,
    )
    _link(campaigns, campaign["id"], {"source": "review-text"}, run4, "ext-d")
    _link(campaigns, campaign["id"], {"source": "review-bool"}, run5, "ext-e")

    packets = campaigns.aggregate_campaign(campaign["id"])
    completed = campaigns.complete_campaign(campaign["id"])
    after_fields = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    after_cells = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)

    return {
        "database": str(path),
        "campaign_id": campaign["id"],
        "campaign_status": completed["status"],
        "field_count_before": before_fields,
        "field_count_after": after_fields,
        "cell_count_before": before_cells,
        "cell_count_after": after_cells,
        "linked_runs": completed["counters"]["runs"],
        "work_items": completed["counters"]["work_items"],
        "packet_count": len(packets),
        "packet_statuses": [p["status"] for p in packets],
        "raw_support_max": max(p["metrics"]["raw_support"] for p in packets),
        "independent_support_min": min(p["metrics"]["independent_support"] for p in packets),
        "packets": packets,
    }


def benchmark_campaign_coordination(
    path: str | Path, run_count: int = 80, key_count: int = 8
) -> dict:
    if run_count < 1:
        raise ValueError("run_count must be >= 1")
    if key_count < 1 or key_count > run_count:
        raise ValueError("key_count must be between 1 and run_count")
    path = _reset(path)
    db = Database(path)
    agents = AgentService(db)
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(
        name="Bounded Campaign Benchmark",
        task_text="Measure bounded advisory coordination.",
        budget={
            "max_runs": run_count,
            "max_work_items": run_count,
            "max_agent_steps": run_count * 4,
            "max_proposals": run_count,
            "max_cost_units": run_count,
        },
        evaluator="benchmark:campaign-v1",
    )
    before_fields = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    before_cells = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)
    start = time.perf_counter()
    for i in range(run_count):
        key = f"signal_{i % key_count:02d}"
        packet = _external_packet(key, key.replace("_", " ").title(), "integer", f"bench:{i}")
        run = agents.run_external(packet, score_proposals=False, assess_existing=False)
        _link(campaigns, campaign["id"], {"index": i, "key": key}, run, f"agent-{i:04d}")
    packets = campaigns.aggregate_campaign(campaign["id"])
    completed = campaigns.complete_campaign(campaign["id"])
    elapsed = time.perf_counter() - start
    return {
        "database": str(path),
        "runs": completed["counters"]["runs"],
        "work_items": completed["counters"]["work_items"],
        "key_count": key_count,
        "packet_count": len(packets),
        "packet_statuses": sorted({p["status"] for p in packets}),
        "field_count_before": before_fields,
        "field_count_after": int(db.scalar("SELECT COUNT(*) FROM fields") or 0),
        "cell_count_before": before_cells,
        "cell_count_after": int(db.scalar("SELECT COUNT(*) FROM cells") or 0),
        "campaign_status": completed["status"],
        "elapsed_seconds": round(elapsed, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SEDB v0.4A campaign coordination demos.")
    parser.add_argument("--db", default="sedb-campaign-governance-v0.4a.sqlite")
    parser.add_argument("--benchmark-db", default="sedb-campaign-benchmark-v0.4a.sqlite")
    parser.add_argument("--runs", type=int, default=80)
    parser.add_argument("--keys", type=int, default=8)
    args = parser.parse_args()
    result = {
        "governance_demo": build_campaign_demo(args.db),
        "campaign_benchmark": benchmark_campaign_coordination(args.benchmark_db, args.runs, args.keys),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

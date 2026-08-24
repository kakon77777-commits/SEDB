from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from sedb.agent import AgentService
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.governance import FieldGovernanceService


def _reset(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        path.unlink()
    return path


def build_agent_demo(path: str | Path) -> dict:
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    governance = FieldGovernanceService(db)
    agent = AgentService(db)

    paper = fields.create_field(key="paper", label="Paper")
    country = fields.create_field(key="country", label="Country")
    governance.add_alias(country["id"], "author_country", reason="Demo alias")
    entity = entities.create_entity(label="Existing paper", kind="paper")
    entities.set_cell(entity["id"], paper["key"], "P000", source="demo")

    fields_before = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    cells_before = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)
    proposals_before = int(db.scalar("SELECT COUNT(*) FROM field_proposals") or 0)

    deterministic = agent.run_deterministic(
        {
            "records": [
                {
                    "paper": "P001",
                    "author_country": "Taiwan",
                    "publication_type": "preprint",
                    "ai_assistance_disclosed": True,
                }
            ]
        },
        evaluator="demo:deterministic-agent",
        score_proposals=True,
        assess_existing=True,
    )

    external = agent.run_external(
        {
            "suggestions": [
                {
                    "key": "dataset_license",
                    "label": "Dataset License",
                    "value_type": "text",
                    "reason": "External advisory backend identified license metadata.",
                    "confidence": 0.9,
                    "evidence_refs": ["external:demo#/license"],
                }
            ]
        },
        evaluator="demo:external-agent",
        score_proposals=False,
        assess_existing=False,
    )

    denied_run = agent.create_run(
        backend="external-suggestion-v1", evaluator="demo:denied-capability"
    )
    denied_receipt = agent.execute_intent(
        denied_run["id"],
        "set_cell",
        {"entity_id": entity["id"], "field": paper["key"], "value": "forbidden"},
        evidence_refs=["demo:denied"],
    )

    before_budget_proposals = int(db.scalar("SELECT COUNT(*) FROM field_proposals") or 0)
    budget_run = agent.run_deterministic(
        {"budget_only_signal": 1},
        budget={"max_steps": 1, "max_observations": 1, "max_proposals": 10},
        evaluator="demo:budget",
        score_proposals=False,
        assess_existing=False,
    )
    after_budget_proposals = int(db.scalar("SELECT COUNT(*) FROM field_proposals") or 0)

    fields_after = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    cells_after = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)
    proposals_after = int(db.scalar("SELECT COUNT(*) FROM field_proposals") or 0)

    return {
        "database": str(path),
        "field_count_before_runs": fields_before,
        "field_count_after_runs": fields_after,
        "cell_count_before_runs": cells_before,
        "cell_count_after_runs": cells_after,
        "proposals_created": proposals_after - proposals_before,
        "deterministic_run_id": deterministic["id"],
        "deterministic_run_status": deterministic["status"],
        "deterministic_outcomes": [a["outcome"] for a in deterministic["actions"]],
        "external_run_id": external["id"],
        "external_run_status": external["status"],
        "external_outcomes": [a["outcome"] for a in external["actions"]],
        "denied_run_id": denied_run["id"],
        "denied_mutation_receipts": 1 if denied_receipt["outcome"] == "DENIED" else 0,
        "denied_intent": denied_receipt["intent"],
        "budget_run_id": budget_run["id"],
        "budget_run_status": budget_run["status"],
        "budget_run_proposals_created": after_budget_proposals - before_budget_proposals,
        "agent_runs": int(db.scalar("SELECT COUNT(*) FROM field_agent_runs") or 0),
        "agent_actions": int(db.scalar("SELECT COUNT(*) FROM field_agent_actions") or 0),
        "utility_assessments": int(db.scalar("SELECT COUNT(*) FROM field_utility_assessments") or 0),
        "semantic_candidates": int(db.scalar("SELECT COUNT(*) FROM semantic_candidates") or 0),
    }


def benchmark_agent_observation(
    path: str | Path, record_count: int = 2_000, field_width: int = 20
) -> dict:
    if record_count < 1:
        raise ValueError("record_count must be >= 1")
    if field_width < 1 or field_width > 50:
        raise ValueError("field_width must be between 1 and 50")
    path = _reset(path)
    db = Database(path)
    agent = AgentService(db)
    records = [
        {f"signal_{j:02d}": i * (j + 1) for j in range(field_width)}
        for i in range(record_count)
    ]
    before_fields = int(db.scalar("SELECT COUNT(*) FROM fields") or 0)
    before_cells = int(db.scalar("SELECT COUNT(*) FROM cells") or 0)
    start = time.perf_counter()
    run = agent.run_deterministic(
        {"records": records},
        evaluator="benchmark:agent-v1",
        budget={
            "max_steps": field_width + 5,
            "max_observations": 1,
            "max_proposals": field_width + 2,
            "max_candidate_scores": 0,
            "max_family_proposals": 0,
            "max_assessments": 0,
        },
        score_proposals=False,
        assess_existing=False,
        propose_families=False,
    )
    elapsed = time.perf_counter() - start
    return {
        "database": str(path),
        "records": record_count,
        "field_width": field_width,
        "proposals_created": int(db.scalar("SELECT COUNT(*) FROM field_proposals") or 0),
        "field_count_before": before_fields,
        "field_count_after": int(db.scalar("SELECT COUNT(*) FROM fields") or 0),
        "cell_count_before": before_cells,
        "cell_count_after": int(db.scalar("SELECT COUNT(*) FROM cells") or 0),
        "run_status": run["status"],
        "steps": run["counters"]["steps"],
        "elapsed_seconds": round(elapsed, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SEDB v0.3C governed Agent demo data.")
    parser.add_argument("--db", default="sedb-agent-governance-v0.3c.sqlite")
    parser.add_argument("--benchmark-db", default="sedb-agent-observation-v0.3c.sqlite")
    parser.add_argument("--records", type=int, default=2_000)
    parser.add_argument("--field-width", type=int, default=20)
    args = parser.parse_args()
    result = {
        "governance_demo": build_agent_demo(args.db),
        "observation_benchmark": benchmark_agent_observation(
            args.benchmark_db, args.records, args.field_width
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

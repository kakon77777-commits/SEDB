#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from sedb.autonomy import AutonomyService
from sedb.campaign import CampaignService
from sedb.db import Database
from sedb.fields import FieldService


def _make_packet(db: Database, status: str) -> str:
    campaign = CampaignService(db).create_campaign(name=f"Autonomy {status}")
    group_id = uuid4().hex
    packet_id = uuid4().hex
    now = "2026-08-23T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_agent_advisory_groups(
                id,campaign_id,namespace,normalized_key,raw_support,independent_support,
                backend_count,evidence_root_count,conflict_count,basis_count,min_pair_score,
                avg_pair_score,metrics_json,evidence_json,created_at
            ) VALUES(?,?, 'global','review_status',4,3,2,3,1,1,0.4,0.7,'{}','{}',?)
            """,
            (group_id, campaign["id"], now),
        )
        conn.execute(
            """
            INSERT INTO field_agent_consensus_packets(
                id,campaign_id,group_id,policy_version,status,summary,metrics_json,
                evidence_json,basis_sha256,created_at
            ) VALUES(?,?,?,'consensus-v1',?,'fixture','{}','{}','basis',?)
            """,
            (packet_id, campaign["id"], group_id, status, now),
        )
    return packet_id


def run_demo(db_path: str | Path) -> dict:
    path = Path(db_path)
    if path.exists():
        path.unlink()
    db = Database(path)
    fields = FieldService(db)
    autonomy = AutonomyService(db)
    env = autonomy.ensure_default_envelope()

    before = int(db.scalar("SELECT COUNT(*) FROM fields"))
    proposal = fields.create_proposal(
        key="ai_assistance_disclosed",
        label="AI assistance disclosed",
        value_type="boolean",
        reason="Repeated independent observation",
        proposed_by="agent:campaign",
    )
    committed = autonomy.execute_autonomously(
        {
            "type": "accept_proposal",
            "proposal_id": proposal["id"],
            "reason": "Inside delegated local canonical autonomy surface",
        },
        env["id"],
        evaluator="agent:autonomy-demo",
    )
    after_commit = int(db.scalar("SELECT COUNT(*) FROM fields"))
    committed_field = committed["commit"]["mutation"]["target_field_id"]

    conflict_proposal = fields.create_proposal(
        key="review_status",
        label="Review status",
        reason="Conflicting Agent interpretations",
        proposed_by="agent:campaign",
    )
    conflict_packet = _make_packet(db, "incompatible")
    conflict = autonomy.execute_autonomously(
        {
            "type": "accept_proposal",
            "proposal_id": conflict_proposal["id"],
            "reason": "Must not override semantic conflict",
        },
        env["id"],
        evidence={"consensus_packet_id": conflict_packet},
        evaluator="agent:autonomy-demo",
    )

    novel_action = {
        "type": "novel_index_rebalance",
        "properties": {
            "external": False,
            "shared_world": True,
            "reversible": True,
            "cost_units": 1,
            "resource_owner": "local_database",
            "authority_domain": "sedb.canonical",
            "public_commitment": False,
            "irreversible": False,
        },
    }
    novel_decision = autonomy.decide(novel_action, env["id"], evaluator="agent:autonomy-demo")
    novel_failure = ""
    try:
        autonomy.commit_decision(novel_decision["id"])
    except RuntimeError as exc:
        novel_failure = "CAPABILITY_MISSING" if "CAPABILITY_MISSING" in str(exc) else type(exc).__name__

    rollback = autonomy.rollback_commit(committed["commit"]["id"], evaluator="agent:autonomy-demo")
    rolled_status = fields.get_field(committed_field)["status"]
    stats = autonomy.stats()

    return {
        "db_path": str(path),
        "canonical_fields_before": before,
        "canonical_fields_after_commit": after_commit,
        "conflict_decision": conflict["decision"]["decision"],
        "conflict_commit": conflict["commit"],
        "novel_decision": novel_decision["decision"],
        "novel_commit_failure": novel_failure,
        "commit_count": stats["commit_count"],
        "rollback_count": stats["rollback_count"],
        "rolled_back_field_status": rolled_status,
        "commit_id": committed["commit"]["id"],
        "rollback_id": rollback["id"],
        "autonomy_stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="sedb-autonomy-v0.4b.sqlite")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.db), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

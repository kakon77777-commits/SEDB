"""Evidence-aware multi-Agent campaign coordination above the governed Agent runtime."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .agent import AgentService, canonical_json, json_sha256
from .db import Database
from .naming import normalize_field_key
from .semantic import score_field_pair


CAMPAIGN_POLICY_VERSION = "campaign-v1"
CONSENSUS_POLICY_VERSION = "consensus-v1"
DEFAULT_CAMPAIGN_BUDGET = {
    "max_runs": 20,
    "max_work_items": 100,
    "max_agent_steps": 10000,
    "max_proposals": 1000,
    "max_cost_units": 1000,
}
DEFAULT_CAMPAIGN_COUNTERS = {
    "work_items": 0,
    "runs": 0,
    "agent_steps": 0,
    "proposals": 0,
    "cost_units": 0,
}
TERMINAL_CAMPAIGN_STATUSES = {"completed", "budget_exhausted", "failed"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | str | None = None) -> datetime:
    if value is None:
        return _utc_now()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    result = datetime.fromisoformat(text)
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    return _dt(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_campaign(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["budget"] = json.loads(item.pop("budget_json"))
    item["counters"] = json.loads(item.pop("counters_json"))
    return item


def _decode_work_item(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


class CampaignService:
    """Bounded coordinator. It never grants canonical mutation authority."""

    def __init__(self, db: Database):
        self.db = db

    def _normalize_budget(self, budget: dict[str, Any] | None) -> dict[str, int]:
        result = dict(DEFAULT_CAMPAIGN_BUDGET)
        if budget:
            unknown = set(budget) - set(DEFAULT_CAMPAIGN_BUDGET)
            if unknown:
                raise ValueError(f"unknown campaign budget keys: {sorted(unknown)}")
            for key, value in budget.items():
                try:
                    parsed = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"campaign budget {key} must be an integer") from exc
                if parsed < 0:
                    raise ValueError(f"campaign budget {key} cannot be negative")
                result[key] = parsed
        return result

    def _require_campaign_row(self, conn: Any, campaign_id: str) -> Any:
        row = conn.execute(
            "SELECT * FROM field_agent_campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        return row

    @staticmethod
    def _require_nonterminal(row: Any) -> None:
        if row["status"] in TERMINAL_CAMPAIGN_STATUSES:
            raise ValueError(f"campaign is terminal: {row['status']}")

    def _mark_budget_exhausted(self, conn: Any, campaign_id: str, dimension: str, now: str) -> None:
        conn.execute(
            "UPDATE field_agent_campaigns SET status='budget_exhausted',completed_at=?,last_error=? WHERE id=?",
            (now, f"campaign budget exhausted: {dimension}", campaign_id),
        )

    def create_campaign(
        self,
        *,
        name: str,
        task_text: str = "",
        namespace: str = "global",
        budget: dict[str, Any] | None = None,
        evaluator: str = "system:campaign",
    ) -> dict[str, Any]:
        name = str(name).strip()
        if not name:
            raise ValueError("campaign name is required")
        namespace = str(namespace).strip() or "global"
        now = _iso()
        campaign_id = uuid4().hex
        basis = AgentService(self.db)._registry_basis(namespace)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO field_agent_campaigns(
                    id,name,task_text,namespace,policy_version,status,budget_json,counters_json,
                    basis_sha256,evaluator,created_at
                ) VALUES(?,?,?,?,?,'created',?,?,?,?,?)
                """,
                (
                    campaign_id,
                    name,
                    str(task_text),
                    namespace,
                    CAMPAIGN_POLICY_VERSION,
                    canonical_json(self._normalize_budget(budget)),
                    canonical_json(DEFAULT_CAMPAIGN_COUNTERS),
                    json_sha256(basis),
                    str(evaluator),
                    now,
                ),
            )
        return self.get_campaign(campaign_id)

    def add_work_item(self, campaign_id: str, payload: Any) -> dict[str, Any]:
        now = _iso()
        exhausted = False
        with self.db.connect() as conn:
            campaign = self._require_campaign_row(conn, campaign_id)
            self._require_nonterminal(campaign)
            budget = json.loads(campaign["budget_json"])
            counters = json.loads(campaign["counters_json"])
            if counters["work_items"] >= budget["max_work_items"]:
                self._mark_budget_exhausted(conn, campaign_id, "max_work_items", now)
                exhausted = True
            if exhausted:
                row = None
            else:
                ordinal = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(ordinal),-1)+1 FROM field_agent_work_items WHERE campaign_id=?",
                        (campaign_id,),
                    ).fetchone()[0]
                )
                item_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO field_agent_work_items(
                        id,campaign_id,ordinal,payload_json,payload_sha256,status,created_at
                    ) VALUES(?,?,?,?,?,'pending',?)
                    """,
                    (item_id, campaign_id, ordinal, canonical_json(payload), json_sha256(payload), now),
                )
                counters["work_items"] += 1
                conn.execute(
                    "UPDATE field_agent_campaigns SET counters_json=? WHERE id=?",
                    (canonical_json(counters), campaign_id),
                )
                row = conn.execute(
                    "SELECT * FROM field_agent_work_items WHERE id=?", (item_id,)
                ).fetchone()
        if exhausted:
            raise ValueError("campaign budget exhausted: max_work_items")
        return _decode_work_item(row)

    def claim_work_item(
        self,
        campaign_id: str,
        work_item_id: str,
        *,
        agent_label: str,
        lease_seconds: int = 300,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        agent_label = str(agent_label).strip()
        if not agent_label:
            raise ValueError("agent_label is required")
        lease_seconds = int(lease_seconds)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _dt(now)
        now_text = _iso(instant)
        expires_text = _iso(instant + timedelta(seconds=lease_seconds))
        with self.db.connect() as conn:
            campaign = self._require_campaign_row(conn, campaign_id)
            self._require_nonterminal(campaign)
            item = conn.execute(
                "SELECT * FROM field_agent_work_items WHERE id=? AND campaign_id=?",
                (work_item_id, campaign_id),
            ).fetchone()
            if item is None:
                raise KeyError(f"work item not found in campaign: {work_item_id}")
            if item["status"] in {"completed", "failed"}:
                raise ValueError(f"work item is terminal: {item['status']}")

            active = conn.execute(
                "SELECT * FROM field_agent_work_claims WHERE work_item_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (work_item_id,),
            ).fetchone()
            if active is not None:
                if _dt(active["expires_at"]) <= instant:
                    conn.execute(
                        "UPDATE field_agent_work_claims SET status='expired',released_at=? WHERE id=?",
                        (now_text, active["id"]),
                    )
                    conn.execute(
                        "UPDATE field_agent_work_items SET status='pending' WHERE id=?",
                        (work_item_id,),
                    )
                else:
                    raise ValueError("work item is already actively claimed")

            token = uuid4().hex
            cur = conn.execute(
                """
                INSERT INTO field_agent_work_claims(
                    work_item_id,agent_label,lease_token,status,claimed_at,expires_at
                ) VALUES(?,?,?,'active',?,?)
                """,
                (work_item_id, agent_label, token, now_text, expires_text),
            )
            conn.execute(
                "UPDATE field_agent_work_items SET status='claimed' WHERE id=?",
                (work_item_id,),
            )
            if campaign["status"] == "created":
                conn.execute(
                    "UPDATE field_agent_campaigns SET status='running',started_at=? WHERE id=?",
                    (now_text, campaign_id),
                )
            row = conn.execute(
                "SELECT * FROM field_agent_work_claims WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return dict(row)

    def release_claim(self, lease_token: str, *, now: datetime | str | None = None) -> dict[str, Any]:
        now_text = _iso(now)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_agent_work_claims WHERE lease_token=?", (lease_token,)
            ).fetchone()
            if row is None:
                raise KeyError("work claim not found")
            if row["status"] != "active":
                raise ValueError(f"work claim is not active: {row['status']}")
            conn.execute(
                "UPDATE field_agent_work_claims SET status='released',released_at=? WHERE id=?",
                (now_text, row["id"]),
            )
            conn.execute(
                "UPDATE field_agent_work_items SET status='pending' WHERE id=? AND status='claimed'",
                (row["work_item_id"],),
            )
            updated = conn.execute(
                "SELECT * FROM field_agent_work_claims WHERE id=?", (row["id"],)
            ).fetchone()
        return dict(updated)


    def link_run(
        self,
        campaign_id: str,
        work_item_id: str,
        run_id: str,
        *,
        agent_label: str,
        claim_token: str | None = None,
        cost_units: int = 1,
    ) -> dict[str, Any]:
        cost_units = int(cost_units)
        if cost_units < 0:
            raise ValueError("cost_units cannot be negative")
        agent_label = str(agent_label).strip()
        if not agent_label:
            raise ValueError("agent_label is required")
        run = AgentService(self.db).get_run(run_id)
        if run["status"] not in {"completed", "budget_exhausted"}:
            raise ValueError("only a terminal Agent run can be linked")
        observation_hashes = [obs["payload_sha256"] for obs in run["observations"]]
        observation_root = json_sha256(sorted(observation_hashes))
        projected = {
            "runs": 1,
            "agent_steps": int(run["counters"].get("steps", 0)),
            "proposals": int(run["counters"].get("proposals", 0)),
            "cost_units": cost_units,
        }
        now = _iso()
        exhausted_dimension: str | None = None
        inserted_id: int | None = None
        with self.db.connect() as conn:
            campaign = self._require_campaign_row(conn, campaign_id)
            self._require_nonterminal(campaign)
            if conn.execute(
                "SELECT 1 FROM field_agent_campaign_runs WHERE run_id=?", (run_id,)
            ).fetchone():
                raise ValueError("Agent run is already linked")
            item = conn.execute(
                "SELECT * FROM field_agent_work_items WHERE id=? AND campaign_id=?",
                (work_item_id, campaign_id),
            ).fetchone()
            if item is None:
                raise KeyError(f"work item not found in campaign: {work_item_id}")
            if item["status"] in {"completed", "failed"}:
                raise ValueError(f"work item is terminal: {item['status']}")

            claim = None
            active_claim = conn.execute(
                "SELECT * FROM field_agent_work_claims WHERE work_item_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (work_item_id,),
            ).fetchone()
            if claim_token is not None:
                claim = conn.execute(
                    "SELECT * FROM field_agent_work_claims WHERE lease_token=? AND work_item_id=?",
                    (claim_token, work_item_id),
                ).fetchone()
                if claim is None or claim["status"] != "active":
                    raise ValueError("claim token is not active for this work item")
                if _dt(claim["expires_at"]) <= _dt(now):
                    raise ValueError("work claim lease has expired")
            elif active_claim is not None:
                raise ValueError("active work claim requires its lease token")

            budget = json.loads(campaign["budget_json"])
            counters = json.loads(campaign["counters_json"])
            checks = [
                ("max_runs", counters["runs"] + projected["runs"]),
                ("max_agent_steps", counters["agent_steps"] + projected["agent_steps"]),
                ("max_proposals", counters["proposals"] + projected["proposals"]),
                ("max_cost_units", counters["cost_units"] + projected["cost_units"]),
            ]
            for dimension, value in checks:
                if value > budget[dimension]:
                    exhausted_dimension = dimension
                    break
            if exhausted_dimension:
                self._mark_budget_exhausted(conn, campaign_id, exhausted_dimension, now)
            else:
                cur = conn.execute(
                    """
                    INSERT INTO field_agent_campaign_runs(
                        campaign_id,work_item_id,run_id,agent_label,backend,
                        observation_root_sha256,basis_sha256,cost_units,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        campaign_id,
                        work_item_id,
                        run_id,
                        agent_label,
                        run["backend"],
                        observation_root,
                        run["basis_sha256"],
                        cost_units,
                        now,
                    ),
                )
                inserted_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE field_agent_work_items SET status='completed',completed_at=? WHERE id=?",
                    (now, work_item_id),
                )
                if claim is not None:
                    conn.execute(
                        """
                        UPDATE field_agent_work_claims
                        SET status='completed',run_id=?,released_at=? WHERE id=?
                        """,
                        (run_id, now, claim["id"]),
                    )
                for key, amount in projected.items():
                    counters[key] += amount
                if campaign["status"] == "created":
                    conn.execute(
                        "UPDATE field_agent_campaigns SET status='running',started_at=?,counters_json=? WHERE id=?",
                        (now, canonical_json(counters), campaign_id),
                    )
                else:
                    conn.execute(
                        "UPDATE field_agent_campaigns SET counters_json=? WHERE id=?",
                        (canonical_json(counters), campaign_id),
                    )
        if exhausted_dimension:
            raise ValueError(f"campaign budget exhausted: {exhausted_dimension}")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_agent_campaign_runs WHERE id=?", (inserted_id,)
            ).fetchone()
        return dict(row)

    def complete_campaign(self, campaign_id: str) -> dict[str, Any]:
        now = _iso()
        with self.db.connect() as conn:
            row = self._require_campaign_row(conn, campaign_id)
            self._require_nonterminal(row)
            active_claims = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM field_agent_work_claims wc
                    JOIN field_agent_work_items wi ON wi.id=wc.work_item_id
                    WHERE wi.campaign_id=? AND wc.status='active'
                    """,
                    (campaign_id,),
                ).fetchone()[0]
            )
            if active_claims:
                raise ValueError("campaign has active work claims")
            conn.execute(
                "UPDATE field_agent_campaigns SET status='completed',completed_at=? WHERE id=?",
                (now, campaign_id),
            )
        return self.get_campaign(campaign_id)


    def _campaign_signals(self, campaign_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            links = conn.execute(
                "SELECT * FROM field_agent_campaign_runs WHERE campaign_id=? ORDER BY id",
                (campaign_id,),
            ).fetchall()
            signals: list[dict[str, Any]] = []
            for link in links:
                actions = conn.execute(
                    """
                    SELECT * FROM field_agent_actions
                    WHERE run_id=? AND intent='create_proposal'
                      AND outcome IN ('CREATED_PROPOSAL','SKIPPED_PENDING_PROPOSAL')
                    ORDER BY ordinal,id
                    """,
                    (link["run_id"],),
                ).fetchall()
                seen: set[str] = set()
                for action in actions:
                    data = json.loads(action["input_json"])
                    try:
                        key = normalize_field_key(str(data.get("key", "")))
                    except ValueError:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    evidence = json.loads(action["evidence_json"])
                    signals.append(
                        {
                            "run_id": link["run_id"],
                            "action_id": int(action["id"]),
                            "backend": link["backend"],
                            "observation_root_sha256": link["observation_root_sha256"],
                            "basis_sha256": link["basis_sha256"],
                            "namespace": self.get_campaign(campaign_id)["namespace"],
                            "key": key,
                            "label": str(data.get("label") or key),
                            "value_type": str(data.get("value_type", "text")),
                            "description": str(data.get("description", "")),
                            "reason": str(data.get("reason", "")),
                            "outcome": action["outcome"],
                            "evidence_refs": list(evidence.get("refs", [])),
                        }
                    )
        return signals

    @staticmethod
    def _pair_metrics(members: list[dict[str, Any]], semantic_floor: float) -> tuple[float, float, int]:
        if len(members) < 2:
            return 1.0, 1.0, 0
        scores: list[float] = []
        conflicts = 0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                result = score_field_pair(members[i], members[j])
                score = float(result["score"])
                scores.append(score)
                if score < semantic_floor:
                    conflicts += 1
        return min(scores), sum(scores) / len(scores), conflicts

    def aggregate_campaign(
        self,
        campaign_id: str,
        *,
        semantic_floor: float = 0.72,
    ) -> list[dict[str, Any]]:
        semantic_floor = float(semantic_floor)
        if not 0.0 <= semantic_floor <= 1.0:
            raise ValueError("semantic_floor must be between 0 and 1")
        campaign = self.get_campaign(campaign_id)
        if campaign["status"] in TERMINAL_CAMPAIGN_STATUSES:
            raise ValueError(f"campaign is terminal: {campaign['status']}")
        signals = self._campaign_signals(campaign_id)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for signal in signals:
            grouped.setdefault(signal["key"], []).append(signal)
        now = _iso()
        packets: list[dict[str, Any]] = []
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO field_agent_consensus_events(campaign_id,event_type,detail_json,created_at) VALUES(?, 'aggregation_started', ?, ?)",
                (campaign_id, canonical_json({"semantic_floor": semantic_floor, "group_count": len(grouped)}), now),
            )
            for key in sorted(grouped):
                members = grouped[key]
                raw_support = len(members)
                backends = sorted({m["backend"] for m in members})
                roots = sorted({m["observation_root_sha256"] for m in members})
                bases = sorted({m["basis_sha256"] for m in members})
                independent = sorted({(m["backend"], m["observation_root_sha256"]) for m in members})
                value_types = sorted({m["value_type"] for m in members})
                min_pair, avg_pair, conflict_count = self._pair_metrics(members, semantic_floor)
                metrics = {
                    "raw_support": raw_support,
                    "independent_support": len(independent),
                    "backend_count": len(backends),
                    "evidence_root_count": len(roots),
                    "basis_count": len(bases),
                    "conflict_count": conflict_count,
                    "min_pair_score": round(min_pair, 6),
                    "avg_pair_score": round(avg_pair, 6),
                    "value_types": value_types,
                }
                if len(bases) > 1:
                    status = "basis_incompatible"
                elif len(value_types) > 1:
                    status = "incompatible"
                elif raw_support >= 2 and len(independent) <= 1:
                    status = "insufficient_independence"
                elif conflict_count > 0:
                    status = "disputed"
                elif len(independent) >= 2 and len(backends) >= 2 and len(roots) >= 2:
                    status = "strong_agreement"
                elif len(independent) >= 2:
                    status = "weak_agreement"
                else:
                    status = "insufficient_independence"

                evidence = {
                    "backends": backends,
                    "observation_roots": roots,
                    "basis_hashes": bases,
                    "members": [
                        {
                            "run_id": m["run_id"],
                            "action_id": m["action_id"],
                            "backend": m["backend"],
                            "observation_root_sha256": m["observation_root_sha256"],
                            "basis_sha256": m["basis_sha256"],
                            "label": m["label"],
                            "value_type": m["value_type"],
                            "reason": m["reason"],
                            "outcome": m["outcome"],
                            "evidence_refs": m["evidence_refs"],
                        }
                        for m in members
                    ],
                }
                group_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO field_agent_advisory_groups(
                        id,campaign_id,namespace,normalized_key,raw_support,independent_support,
                        backend_count,evidence_root_count,conflict_count,basis_count,min_pair_score,
                        avg_pair_score,metrics_json,evidence_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        group_id,
                        campaign_id,
                        campaign["namespace"],
                        key,
                        raw_support,
                        len(independent),
                        len(backends),
                        len(roots),
                        conflict_count,
                        len(bases),
                        min_pair,
                        avg_pair,
                        canonical_json(metrics),
                        canonical_json(evidence),
                        now,
                    ),
                )
                for member in members:
                    conn.execute(
                        """
                        INSERT INTO field_agent_advisory_group_members(
                            group_id,run_id,action_id,backend,observation_root_sha256,basis_sha256,
                            normalized_key,label,value_type,reason,outcome,evidence_json,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            group_id,
                            member["run_id"],
                            member["action_id"],
                            member["backend"],
                            member["observation_root_sha256"],
                            member["basis_sha256"],
                            key,
                            member["label"],
                            member["value_type"],
                            member["reason"],
                            member["outcome"],
                            canonical_json({"refs": member["evidence_refs"]}),
                            now,
                        ),
                    )
                packet_id = uuid4().hex
                packet_basis = json_sha256(bases)
                summary = f"{key}: {status}; raw={raw_support}, independent={len(independent)}"
                conn.execute(
                    """
                    INSERT INTO field_agent_consensus_packets(
                        id,campaign_id,group_id,policy_version,status,summary,metrics_json,
                        evidence_json,basis_sha256,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        packet_id,
                        campaign_id,
                        group_id,
                        CONSENSUS_POLICY_VERSION,
                        status,
                        summary,
                        canonical_json(metrics),
                        canonical_json(evidence),
                        packet_basis,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO field_agent_consensus_events(campaign_id,packet_id,event_type,detail_json,created_at) VALUES(?,?, 'packet_created', ?, ?)",
                    (campaign_id, packet_id, canonical_json({"normalized_key": key, "status": status}), now),
                )
                packets.append(
                    {
                        "id": packet_id,
                        "campaign_id": campaign_id,
                        "group_id": group_id,
                        "policy_version": CONSENSUS_POLICY_VERSION,
                        "status": status,
                        "summary": summary,
                        "metrics": metrics,
                        "evidence": evidence,
                        "basis_sha256": packet_basis,
                        "created_at": now,
                    }
                )
            conn.execute(
                "INSERT INTO field_agent_consensus_events(campaign_id,event_type,detail_json,created_at) VALUES(?, 'aggregation_completed', ?, ?)",
                (campaign_id, canonical_json({"packet_count": len(packets)}), now),
            )
        return packets

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            campaign = self._require_campaign_row(conn, campaign_id)
            work = conn.execute(
                "SELECT * FROM field_agent_work_items WHERE campaign_id=? ORDER BY ordinal",
                (campaign_id,),
            ).fetchall()
            claims = conn.execute(
                """
                SELECT wc.* FROM field_agent_work_claims wc
                JOIN field_agent_work_items wi ON wi.id=wc.work_item_id
                WHERE wi.campaign_id=? ORDER BY wc.id
                """,
                (campaign_id,),
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM field_agent_campaign_runs WHERE campaign_id=? ORDER BY id",
                (campaign_id,),
            ).fetchall()
            packets = conn.execute(
                "SELECT * FROM field_agent_consensus_packets WHERE campaign_id=? ORDER BY created_at,id",
                (campaign_id,),
            ).fetchall()
        item = _decode_campaign(campaign)
        item["work_items"] = [_decode_work_item(row) for row in work]
        item["claims"] = [dict(row) for row in claims]
        item["runs"] = [dict(row) for row in runs]
        decoded_packets = []
        for row in packets:
            packet = dict(row)
            packet["metrics"] = json.loads(packet.pop("metrics_json"))
            packet["evidence"] = json.loads(packet.pop("evidence_json"))
            decoded_packets.append(packet)
        item["consensus_packets"] = decoded_packets
        return item

    def list_campaigns(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_agent_campaigns ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                (max(1, min(int(limit), 1000)), max(0, int(offset))),
            ).fetchall()
        return [_decode_campaign(row) for row in rows]

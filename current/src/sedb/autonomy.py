"""Reflexive autonomous canonical commit primitives.

This layer intentionally separates authority classification, Decision Receipts,
and later canonical Commit Receipts.  It uses public database state only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .agent import canonical_json
from .db import Database
from .naming import normalize_field_key
from .fields import ALLOWED_TRANSITIONS


DEFAULT_ENVELOPE_ID = "sedb-local-canonical-v1"
REQUIRED_EFFECT_PROPERTIES = {
    "external",
    "shared_world",
    "reversible",
    "cost_units",
    "resource_owner",
    "authority_domain",
    "public_commitment",
    "irreversible",
}

KNOWN_ACTION_PROPERTIES: dict[str, dict[str, Any]] = {
    "accept_proposal": {
        "external": False,
        "shared_world": True,
        "reversible": True,
        "cost_units": 2,
        "resource_owner": "local_database",
        "authority_domain": "sedb.canonical",
        "public_commitment": False,
        "irreversible": False,
    },
    "transition_field": {
        "external": False,
        "shared_world": True,
        "reversible": True,
        "cost_units": 1,
        "resource_owner": "local_database",
        "authority_domain": "sedb.canonical",
        "public_commitment": False,
        "irreversible": False,
    },
    "update_definition": {
        "external": False,
        "shared_world": True,
        "reversible": True,
        "cost_units": 1,
        "resource_owner": "local_database",
        "authority_domain": "sedb.canonical",
        "public_commitment": False,
        "irreversible": False,
    },
    "set_guardrail": {
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return default


class AutonomyService:
    def __init__(self, db: Database):
        self.db = db

    def commit_adapter_names(self) -> set[str]:
        # Capability list, not an authority whitelist.
        return set(KNOWN_ACTION_PROPERTIES)

    def install_envelope(
        self,
        *,
        envelope_id: str,
        name: str,
        version: int,
        rules: dict[str, Any],
        contract_ref: str = "",
        authority_ref: str = "",
        created_by: str = "admin:local",
    ) -> dict[str, Any]:
        envelope_id = str(envelope_id).strip()
        name = str(name).strip()
        if not envelope_id or not name:
            raise ValueError("envelope id and name are required")
        if int(version) < 1:
            raise ValueError("envelope version must be >= 1")
        now = _now()
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM autonomy_envelopes WHERE id=?", (envelope_id,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO autonomy_envelopes(
                        id,name,version,contract_ref,authority_ref,rules_json,created_by,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        envelope_id,
                        name,
                        int(version),
                        str(contract_ref),
                        str(authority_ref),
                        canonical_json(rules),
                        str(created_by),
                        now,
                    ),
                )
            else:
                current = self._decode_envelope(existing)
                desired = {
                    "id": envelope_id,
                    "name": name,
                    "version": int(version),
                    "contract_ref": str(contract_ref),
                    "authority_ref": str(authority_ref),
                    "rules": rules,
                    "created_by": str(created_by),
                }
                for key in ("name", "version", "contract_ref", "authority_ref", "rules", "created_by"):
                    if current[key] != desired[key]:
                        raise ValueError("immutable envelope id already exists with different content")
        return self.get_envelope(envelope_id)

    def ensure_default_envelope(self) -> dict[str, Any]:
        return self.install_envelope(
            envelope_id=DEFAULT_ENVELOPE_ID,
            name="SEDB Local Canonical Autonomy",
            version=1,
            contract_ref="contract:sedb-local-canonical:v1",
            authority_ref="authority:sedb-local-canonical:v1",
            created_by="system:sedb-v0.4b",
            rules={
                "authority_domains": ["sedb.canonical"],
                "resource_owners": ["local_database"],
                "allow_external": False,
                "allow_shared_world": True,
                "allow_irreversible": False,
                "max_cost_units": 10,
            },
        )

    @staticmethod
    def _decode_envelope(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["rules"] = _loads(item.pop("rules_json"), {})
        return item

    def get_envelope(self, envelope_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomy_envelopes WHERE id=?", (str(envelope_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"autonomy envelope not found: {envelope_id}")
        return self._decode_envelope(row)

    def list_envelopes(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM autonomy_envelopes ORDER BY name,version,id"
            ).fetchall()
        return [self._decode_envelope(row) for row in rows]

    def classify_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(action, dict):
            raise ValueError("action must be an object")
        action_type = str(action.get("type") or action.get("action_type") or "").strip()
        if not action_type:
            raise ValueError("action type is required")
        known = action_type in KNOWN_ACTION_PROPERTIES
        if known:
            props = dict(KNOWN_ACTION_PROPERTIES[action_type])
        else:
            supplied = action.get("properties")
            props = dict(supplied) if isinstance(supplied, dict) else {}
        missing = sorted(REQUIRED_EFFECT_PROPERTIES - set(props))
        if not missing:
            try:
                props["cost_units"] = int(props["cost_units"])
            except Exception as exc:
                raise ValueError("cost_units must be an integer") from exc
            if props["cost_units"] < 0:
                raise ValueError("cost_units must be >= 0")
        props["action_type"] = action_type
        props["known_action"] = known
        props["complete"] = not missing
        props["missing_properties"] = missing
        return props

    def _evidence_packet(self, evidence: dict[str, Any] | None) -> dict[str, Any] | None:
        evidence = evidence or {}
        packet_id = evidence.get("consensus_packet_id")
        if not packet_id:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_agent_consensus_packets WHERE id=?", (str(packet_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"consensus packet not found: {packet_id}")
        item = dict(row)
        item["metrics"] = _loads(item.pop("metrics_json"), {})
        item["evidence"] = _loads(item.pop("evidence_json"), {})
        return item

    def _basis_payload_conn(
        self,
        conn: Any,
        action: dict[str, Any],
        evidence: dict[str, Any] | None,
    ) -> dict[str, Any]:
        action_type = str(action.get("type") or action.get("action_type"))
        payload: dict[str, Any] = {"action_type": action_type}
        if action_type == "accept_proposal":
            proposal_id = str(action.get("proposal_id", ""))
            row = conn.execute(
                "SELECT * FROM field_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            payload["proposal"] = dict(row) if row is not None else None
            if row is not None:
                try:
                    normalized = normalize_field_key(row["key"])
                except ValueError:
                    normalized = ""
                matches = conn.execute(
                    "SELECT id,key,status,namespace,normalized_key FROM fields WHERE namespace=? AND normalized_key=? ORDER BY id",
                    (row["namespace"], normalized),
                ).fetchall()
                payload["canonical_matches"] = [dict(item) for item in matches]
        elif action_type in {"transition_field", "update_definition", "set_guardrail"}:
            ref = str(action.get("field_id") or action.get("field") or action.get("field_ref") or "")
            row = conn.execute(
                "SELECT id,key,label,value_type,description,status,namespace,normalized_key,updated_at FROM fields WHERE id=? OR key=? ORDER BY id LIMIT 1",
                (ref, ref),
            ).fetchone()
            payload["field"] = dict(row) if row is not None else None
            if action_type == "set_guardrail" and row is not None:
                guard = conn.execute(
                    "SELECT id,protected,reason,evaluator,created_at FROM field_guardrails WHERE field_id=? ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                payload["guardrail"] = dict(guard) if guard is not None else None
        else:
            payload["registry"] = {
                "field_count": int(conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]),
                "proposal_count": int(conn.execute("SELECT COUNT(*) FROM field_proposals").fetchone()[0]),
            }
        evidence = evidence or {}
        packet_id = evidence.get("consensus_packet_id")
        if packet_id:
            packet = conn.execute(
                "SELECT id,status,basis_sha256,metrics_json FROM field_agent_consensus_packets WHERE id=?",
                (str(packet_id),),
            ).fetchone()
            if packet is None:
                raise KeyError(f"consensus packet not found: {packet_id}")
            payload["consensus_packet"] = {
                "id": packet["id"],
                "status": packet["status"],
                "basis_sha256": packet["basis_sha256"],
                "metrics": _loads(packet["metrics_json"], {}),
            }
        return payload

    def _basis_payload(self, action: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
        with self.db.connect() as conn:
            return self._basis_payload_conn(conn, action, evidence)

    def _constraint_components(
        self,
        properties: dict[str, Any],
        evidence: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
        packet = self._evidence_packet(evidence)
        packet_status = packet["status"] if packet is not None else None
        consensus_compatible = packet_status not in {"disputed", "incompatible", "basis_incompatible"}
        reversibility_ok = not bool(properties.get("irreversible", False))
        constraints = {
            "authority_integrity": True,
            "basis_recorded": True,
            "consensus_compatible": consensus_compatible,
            "reversibility_ok": reversibility_ok,
        }
        methods = ["VERIFY"]
        if not reversibility_ok:
            methods.append("COUNTEREXAMPLE")
        if packet_status in {"disputed", "incompatible"}:
            methods.extend(["COMPARE", "STOP"])
        elif packet_status == "basis_incompatible":
            methods.append("STOP")
        risk = {
            "external": bool(properties.get("external", False)),
            "shared_world": bool(properties.get("shared_world", False)),
            "irreversible": bool(properties.get("irreversible", False)),
            "cost_units": properties.get("cost_units"),
            "consensus_status": packet_status,
        }
        return constraints, methods, risk

    def _create_constraint_snapshot(
        self,
        action: dict[str, Any],
        properties: dict[str, Any],
        basis_sha256: str,
        evidence: dict[str, Any] | None,
    ) -> dict[str, Any]:
        constraints, methods, risk = self._constraint_components(properties, evidence)
        snapshot_id = uuid4().hex
        action_sha = _sha(action)
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO autonomy_constraint_snapshots(
                    id,action_sha256,basis_sha256,constraints_json,methods_json,risk_json,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    action_sha,
                    basis_sha256,
                    canonical_json(constraints),
                    canonical_json(methods),
                    canonical_json(risk),
                    now,
                ),
            )
        return self.get_constraint_snapshot(snapshot_id)

    def get_constraint_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomy_constraint_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"constraint snapshot not found: {snapshot_id}")
        item = dict(row)
        item["constraints"] = _loads(item.pop("constraints_json"), {})
        item["methods"] = _loads(item.pop("methods_json"), [])
        item["risk"] = _loads(item.pop("risk_json"), {})
        return item

    def decide(
        self,
        action: dict[str, Any],
        envelope_id: str = DEFAULT_ENVELOPE_ID,
        *,
        evidence: dict[str, Any] | None = None,
        evaluator: str = "",
    ) -> dict[str, Any]:
        if envelope_id == DEFAULT_ENVELOPE_ID:
            self.ensure_default_envelope()
        envelope = self.get_envelope(envelope_id)
        props = self.classify_action(action)
        basis_payload = self._basis_payload(action, evidence)
        basis_sha = _sha(basis_payload)
        snapshot = self._create_constraint_snapshot(action, props, basis_sha, evidence)
        constraint_sha = _sha(
            {"constraints": snapshot["constraints"], "methods": snapshot["methods"], "risk": snapshot["risk"]}
        )
        reasons: list[str] = []
        action_type = props["action_type"]
        if not props["known_action"]:
            reasons.append("unknown_action")
        packet = self._evidence_packet(evidence)
        packet_status = packet["status"] if packet is not None else None

        if packet_status in {"disputed", "incompatible"}:
            decision = "ESCALATE"
            reasons.append("consensus_conflict")
        elif packet_status == "basis_incompatible":
            decision = "DEFER"
            reasons.append("consensus_basis_incompatible")
        elif not props["complete"]:
            decision = "DEFER"
            reasons.append("effect_classification_incomplete")
        else:
            rules = envelope["rules"]
            if bool(props["external"]) and not bool(rules.get("allow_external", False)):
                reasons.append("external_effect_not_delegated")
            if bool(props["shared_world"]) and not bool(rules.get("allow_shared_world", False)):
                reasons.append("shared_world_effect_not_delegated")
            if str(props["authority_domain"]) not in set(rules.get("authority_domains", [])):
                reasons.append("authority_domain_not_delegated")
            if str(props["resource_owner"]) not in set(rules.get("resource_owners", [])):
                reasons.append("resource_owner_not_delegated")
            if bool(props["irreversible"]) and not bool(rules.get("allow_irreversible", False)):
                reasons.append("irreversible_effect_not_delegated")
            if int(props["cost_units"]) > int(rules.get("max_cost_units", 0)):
                reasons.append("cost_exceeds_envelope")
            boundary_reasons = [
                code for code in reasons
                if code.endswith("_not_delegated") or code == "irreversible_effect_not_delegated"
            ]
            if boundary_reasons:
                decision = "ESCALATE"
            elif "cost_exceeds_envelope" in reasons:
                decision = "DEFER"
            else:
                decision = "EXECUTE"
                reasons.append("inside_autonomy_envelope")

        summary = {
            "EXECUTE": "Action is inside the delegated autonomy surface.",
            "ESCALATE": "Action crosses a relational or authority boundary.",
            "DEFER": "Action cannot be safely classified or executed under the current envelope yet.",
            "REFUSE": "Action is explicitly denied.",
            "IDLE": "No canonical action is required.",
        }[decision]
        decision_id = uuid4().hex
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO autonomy_decisions(
                    id,action_type,action_json,properties_json,decision,reason_codes_json,summary,
                    envelope_id,basis_sha256,constraint_snapshot_id,constraint_sha256,evidence_json,
                    evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id,
                    action_type,
                    canonical_json(action),
                    canonical_json(props),
                    decision,
                    canonical_json(reasons),
                    summary,
                    envelope["id"],
                    basis_sha,
                    snapshot["id"],
                    constraint_sha,
                    canonical_json(evidence or {}),
                    str(evaluator),
                    now,
                ),
            )
        return self.get_decision(decision_id)

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomy_decisions WHERE id=?", (decision_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"autonomy decision not found: {decision_id}")
        item = dict(row)
        item["action"] = _loads(item.pop("action_json"), {})
        item["properties"] = _loads(item.pop("properties_json"), {})
        item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
        item["evidence"] = _loads(item.pop("evidence_json"), {})
        return item

    def list_decisions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM autonomy_decisions ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["action"] = _loads(item.pop("action_json"), {})
            item["properties"] = _loads(item.pop("properties_json"), {})
            item["reason_codes"] = _loads(item.pop("reason_codes_json"), [])
            item["evidence"] = _loads(item.pop("evidence_json"), {})
            items.append(item)
        return items


    def _resolve_field_conn(self, conn: Any, ref: str) -> Any:
        row = conn.execute(
            "SELECT * FROM fields WHERE id=? OR key=? ORDER BY id LIMIT 1", (str(ref), str(ref))
        ).fetchone()
        if row is None:
            raise KeyError(f"field not found: {ref}")
        return row

    def _record_commit_failure(self, decision_id: str, code: str, message: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO autonomy_commit_events(decision_id,event_type,detail_json,created_at) VALUES(?,'failed',?,?)",
                (decision_id, canonical_json({"code": code, "message": message}), _now()),
            )

    def _adapter_accept_proposal(self, conn: Any, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        action = decision["action"]
        proposal_id = str(action.get("proposal_id", ""))
        reason = str(action.get("reason", "")).strip()
        if not reason:
            raise ValueError("reason is required for autonomous proposal acceptance")
        proposal = conn.execute("SELECT * FROM field_proposals WHERE id=?", (proposal_id,)).fetchone()
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if proposal["status"] != "pending":
            raise ValueError(f"proposal is not pending: {proposal['status']}")
        now = _now()
        namespace = proposal["namespace"] or "global"
        normalized = normalize_field_key(proposal["key"])
        matches = conn.execute(
            "SELECT * FROM fields WHERE namespace=? AND normalized_key=? ORDER BY id LIMIT 2",
            (namespace, normalized),
        ).fetchall()
        if len(matches) > 1:
            raise ValueError("ambiguous normalized canonical identity")
        evaluator = decision.get("evaluator", "")
        target_field_id: str
        alias_id: int | None = None
        if matches:
            target = matches[0]
            target_field_id = target["id"]
            alias = conn.execute(
                "SELECT * FROM field_aliases WHERE namespace=? AND normalized_alias=?",
                (namespace, normalized),
            ).fetchone()
            if alias is not None and alias["field_id"] != target_field_id:
                raise ValueError("alias resolves to another field")
            if alias is None:
                cur = conn.execute(
                    "INSERT INTO field_aliases(namespace,alias,normalized_alias,field_id,reason,created_at) VALUES(?,?,?,?,?,?)",
                    (namespace, proposal["key"], normalized, target_field_id, reason, now),
                )
                alias_id = int(cur.lastrowid)
            outcome = "alias_existing"
            rollback = {
                "type": "rollback_accept_proposal",
                "mode": "remove_alias" if alias_id is not None else "no_op",
                "alias_id": alias_id,
                "proposal_id": proposal_id,
                "target_field_id": target_field_id,
            }
        else:
            target_field_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO fields(
                    id,key,label,value_type,description,status,created_at,updated_at,namespace,normalized_key
                ) VALUES(?,?,?,?,?,'active',?,?,?,?)
                """,
                (
                    target_field_id, proposal["key"], proposal["label"], proposal["value_type"],
                    proposal["description"], now, now, namespace, normalized,
                ),
            )
            conn.execute(
                "INSERT INTO field_events(field_id,event_type,from_status,to_status,reason,evaluator,created_at) VALUES(?,'created',NULL,'active',?,?,?)",
                (target_field_id, reason, evaluator, now),
            )
            conn.execute(
                "INSERT INTO field_versions(field_id,version,label,value_type,description,reason,evaluator,created_at) VALUES(?,1,?,?,?,?,?,?)",
                (
                    target_field_id, proposal["label"], proposal["value_type"], proposal["description"],
                    reason, evaluator, now,
                ),
            )
            outcome = "created"
            rollback = {
                "type": "rollback_accept_proposal",
                "mode": "deprecate_created_field",
                "proposal_id": proposal_id,
                "target_field_id": target_field_id,
            }
        conn.execute("UPDATE field_proposals SET status='accepted' WHERE id=?", (proposal_id,))
        conn.execute(
            """
            INSERT INTO proposal_decisions(
                proposal_id,decision,outcome,target_field_id,reason,evidence_json,evaluator,created_at
            ) VALUES(?,'accepted',?,?,?,?,?,?)
            """,
            (
                proposal_id, outcome, target_field_id, reason,
                canonical_json(decision.get("evidence", {})), evaluator, now,
            ),
        )
        return {
            "outcome": outcome,
            "proposal_id": proposal_id,
            "target_field_id": target_field_id,
            "alias_id": alias_id,
        }, rollback

    def _adapter_transition_field(self, conn: Any, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        action = decision["action"]
        field = self._resolve_field_conn(conn, str(action.get("field_id") or action.get("field") or ""))
        to_status = str(action.get("to_status", "")).strip()
        if to_status in {"merged", "split"}:
            raise ValueError("merged/split require lineage governance")
        from_status = field["status"]
        if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
            raise ValueError(f"illegal field transition: {from_status} -> {to_status}")
        reason = str(action.get("reason", "")).strip()
        needs_reason = to_status == "converged" or (from_status == "converged" and to_status == "active")
        if needs_reason and not reason:
            raise ValueError("reason is required for convergence/reactivation")
        now = _now()
        if to_status == "converged":
            event_type, eval_decision = "converged", "converge"
        elif from_status == "converged" and to_status == "active":
            event_type, eval_decision = "reactivated", "reactivate"
        else:
            event_type, eval_decision = to_status, ""
        evaluator = decision.get("evaluator", "")
        conn.execute("UPDATE fields SET status=?,updated_at=? WHERE id=?", (to_status, now, field["id"]))
        conn.execute(
            "INSERT INTO field_events(field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                field["id"], event_type, from_status, to_status, reason,
                canonical_json(decision.get("evidence", {})), evaluator, now,
            ),
        )
        if eval_decision:
            conn.execute(
                "INSERT INTO field_evaluations(field_id,decision,reason,evidence_json,metrics_json,evaluator,reversible,created_at) VALUES(?,?,?,?,?,?,1,?)",
                (
                    field["id"], eval_decision, reason, canonical_json(decision.get("evidence", {})),
                    canonical_json({"autonomy_decision_id": decision["id"]}), evaluator, now,
                ),
            )
        return {
            "field_id": field["id"], "from_status": from_status, "to_status": to_status
        }, {
            "type": "transition_field",
            "field_id": field["id"],
            "to_status": from_status,
            "reason": f"Compensating rollback of autonomy decision {decision['id']}",
        }

    def _adapter_update_definition(self, conn: Any, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        action = decision["action"]
        field = self._resolve_field_conn(conn, str(action.get("field_id") or action.get("field") or ""))
        reason = str(action.get("reason", "")).strip()
        if not reason:
            raise ValueError("reason is required for definition updates")
        old = {"label": field["label"], "value_type": field["value_type"], "description": field["description"]}
        new = {
            "label": str(action.get("label", field["label"])),
            "value_type": str(action.get("value_type", field["value_type"])),
            "description": str(action.get("description", field["description"])),
        }
        if new == old:
            raise ValueError("definition update makes no change")
        now = _now()
        evaluator = decision.get("evaluator", "")
        version = int(conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM field_versions WHERE field_id=?", (field["id"],)).fetchone()[0])
        conn.execute(
            "UPDATE fields SET label=?,value_type=?,description=?,updated_at=? WHERE id=?",
            (new["label"], new["value_type"], new["description"], now, field["id"]),
        )
        conn.execute(
            "INSERT INTO field_versions(field_id,version,label,value_type,description,reason,evaluator,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (field["id"], version, new["label"], new["value_type"], new["description"], reason, evaluator, now),
        )
        return {"field_id": field["id"], "version": version, "before": old, "after": new}, {
            "type": "update_definition",
            "field_id": field["id"],
            **old,
            "reason": f"Compensating rollback of autonomy decision {decision['id']}",
        }

    def _adapter_set_guardrail(self, conn: Any, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        action = decision["action"]
        field = self._resolve_field_conn(conn, str(action.get("field_id") or action.get("field") or ""))
        reason = str(action.get("reason", "")).strip()
        if not reason:
            raise ValueError("reason is required for guardrail changes")
        latest = conn.execute(
            "SELECT * FROM field_guardrails WHERE field_id=? ORDER BY id DESC LIMIT 1", (field["id"],)
        ).fetchone()
        previous = bool(latest["protected"]) if latest is not None else False
        protected = bool(action.get("protected", False))
        now = _now()
        cur = conn.execute(
            "INSERT INTO field_guardrails(field_id,protected,reason,evaluator,created_at) VALUES(?,?,?,?,?)",
            (field["id"], int(protected), reason, decision.get("evaluator", ""), now),
        )
        return {"field_id": field["id"], "guardrail_id": int(cur.lastrowid), "protected": protected}, {
            "type": "set_guardrail",
            "field_id": field["id"],
            "protected": previous,
            "reason": f"Compensating rollback of autonomy decision {decision['id']}",
        }

    def _apply_adapter(self, conn: Any, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        action_type = decision["action_type"]
        if action_type == "accept_proposal":
            return self._adapter_accept_proposal(conn, decision)
        if action_type == "transition_field":
            return self._adapter_transition_field(conn, decision)
        if action_type == "update_definition":
            return self._adapter_update_definition(conn, decision)
        if action_type == "set_guardrail":
            return self._adapter_set_guardrail(conn, decision)
        raise RuntimeError(f"CAPABILITY_MISSING: no canonical commit adapter for {action_type}")

    def get_commit(self, commit_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM autonomy_commit_receipts WHERE id=?", (commit_id,)).fetchone()
        if row is None:
            raise KeyError(f"commit receipt not found: {commit_id}")
        item = dict(row)
        item["mutation"] = _loads(item.pop("mutation_json"), {})
        item["rollback_action"] = _loads(item.pop("rollback_action_json"), {})
        return item

    def list_commit_events(self, decision_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM autonomy_commit_events WHERE decision_id=? ORDER BY id", (decision_id,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = _loads(item.pop("detail_json"), {})
            result.append(item)
        return result

    def commit_decision(self, decision_id: str) -> dict[str, Any]:
        decision = self.get_decision(decision_id)
        if decision["decision"] != "EXECUTE":
            raise ValueError(f"decision is not executable: {decision['decision']}")
        with self.db.connect() as conn:
            if conn.execute("SELECT 1 FROM autonomy_commit_receipts WHERE decision_id=?", (decision_id,)).fetchone():
                raise ValueError("decision already committed")
        if decision["action_type"] not in self.commit_adapter_names():
            message = f"CAPABILITY_MISSING: no canonical commit adapter for {decision['action_type']}"
            self._record_commit_failure(decision_id, "CAPABILITY_MISSING", message)
            raise RuntimeError(message)

        try:
            with self.db.connect() as conn:
                current_basis = _sha(self._basis_payload_conn(conn, decision["action"], decision.get("evidence")))
                if current_basis != decision["basis_sha256"]:
                    raise ValueError("STALE_BASIS: canonical preconditions changed after decision")
                constraints, methods, risk = self._constraint_components(decision["properties"], decision.get("evidence"))
                current_constraint_sha = _sha({"constraints": constraints, "methods": methods, "risk": risk})
                if current_constraint_sha != decision["constraint_sha256"]:
                    raise ValueError("STALE_CONSTRAINT: public constraint basis changed after decision")
                now = _now()
                conn.execute(
                    "INSERT INTO autonomy_commit_events(decision_id,event_type,detail_json,created_at) VALUES(?,'preflight',?,?)",
                    (decision_id, canonical_json({"basis_sha256": current_basis}), now),
                )
                before_sha = current_basis
                mutation, rollback_action = self._apply_adapter(conn, decision)
                after_sha = _sha(self._basis_payload_conn(conn, decision["action"], decision.get("evidence")))
                commit_id = uuid4().hex
                tx_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO autonomy_commit_receipts(
                        id,decision_id,transaction_id,action_type,before_state_sha256,after_state_sha256,
                        mutation_json,rollback_action_json,rollback_mode,envelope_id,constraint_snapshot_id,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        commit_id, decision_id, tx_id, decision["action_type"], before_sha, after_sha,
                        canonical_json(mutation), canonical_json(rollback_action), "compensating",
                        decision["envelope_id"], decision["constraint_snapshot_id"], now,
                    ),
                )
                conn.execute(
                    "INSERT INTO autonomy_commit_events(decision_id,commit_id,event_type,detail_json,created_at) VALUES(?,?,'committed',?,?)",
                    (decision_id, commit_id, canonical_json({"transaction_id": tx_id}), now),
                )
            return self.get_commit(commit_id)
        except Exception as exc:
            code = "STALE_BASIS" if "STALE_BASIS" in str(exc) else (
                "STALE_CONSTRAINT" if "STALE_CONSTRAINT" in str(exc) else "COMMIT_FAILED"
            )
            self._record_commit_failure(decision_id, code, str(exc))
            raise

    def execute_autonomously(
        self,
        action: dict[str, Any],
        envelope_id: str = DEFAULT_ENVELOPE_ID,
        *,
        evidence: dict[str, Any] | None = None,
        evaluator: str = "",
    ) -> dict[str, Any]:
        decision = self.decide(action, envelope_id, evidence=evidence, evaluator=evaluator)
        if decision["decision"] != "EXECUTE":
            return {"decision": decision, "commit": None}
        commit = self.commit_decision(decision["id"])
        return {"decision": decision, "commit": commit}

    def _canonical_fingerprint_conn(self, conn: Any) -> str:
        payload: dict[str, Any] = {}
        for table, cols in [
            ("fields", "id,key,label,value_type,description,status,namespace,normalized_key,updated_at"),
            ("field_aliases", "id,namespace,alias,normalized_alias,field_id,reason,created_at"),
            ("field_versions", "id,field_id,version,label,value_type,description,reason,evaluator,created_at"),
            ("field_guardrails", "id,field_id,protected,reason,evaluator,created_at"),
            ("field_proposals", "id,key,label,value_type,status,namespace,created_at"),
        ]:
            rows = conn.execute(f"SELECT {cols} FROM {table} ORDER BY 1").fetchall()
            payload[table] = [dict(row) for row in rows]
        return _sha(payload)

    def get_rollback(self, rollback_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomy_rollback_receipts WHERE id=?", (rollback_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"rollback receipt not found: {rollback_id}")
        item = dict(row)
        item["mutation"] = _loads(item.pop("mutation_json"), {})
        return item

    def _apply_rollback_action(
        self,
        conn: Any,
        commit: dict[str, Any],
        *,
        evaluator: str,
    ) -> dict[str, Any]:
        action = commit["rollback_action"]
        action_type = str(action.get("type", ""))
        now = _now()
        reason = str(action.get("reason", f"Compensating rollback of commit {commit['id']}"))
        if action_type == "transition_field":
            field = self._resolve_field_conn(conn, str(action.get("field_id", "")))
            from_status = field["status"]
            to_status = str(action.get("to_status", ""))
            if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
                raise ValueError(f"rollback transition unavailable: {from_status} -> {to_status}")
            if to_status == "converged":
                event_type, eval_decision = "converged", "converge"
            elif from_status == "converged" and to_status == "active":
                event_type, eval_decision = "reactivated", "reactivate"
            else:
                event_type, eval_decision = to_status, ""
            conn.execute(
                "UPDATE fields SET status=?,updated_at=? WHERE id=?",
                (to_status, now, field["id"]),
            )
            conn.execute(
                "INSERT INTO field_events(field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    field["id"], event_type, from_status, to_status, reason,
                    canonical_json({"rollback_of_commit": commit["id"]}), evaluator, now,
                ),
            )
            if eval_decision:
                conn.execute(
                    "INSERT INTO field_evaluations(field_id,decision,reason,evidence_json,metrics_json,evaluator,reversible,created_at) VALUES(?,?,?,?,?,?,1,?)",
                    (
                        field["id"], eval_decision, reason,
                        canonical_json({"rollback_of_commit": commit["id"]}),
                        canonical_json({"compensating": True}), evaluator, now,
                    ),
                )
            return {"type": action_type, "field_id": field["id"], "from_status": from_status, "to_status": to_status}

        if action_type == "update_definition":
            field = self._resolve_field_conn(conn, str(action.get("field_id", "")))
            restored = {
                "label": str(action.get("label", field["label"])),
                "value_type": str(action.get("value_type", field["value_type"])),
                "description": str(action.get("description", field["description"])),
            }
            version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM field_versions WHERE field_id=?",
                    (field["id"],),
                ).fetchone()[0]
            )
            conn.execute(
                "UPDATE fields SET label=?,value_type=?,description=?,updated_at=? WHERE id=?",
                (restored["label"], restored["value_type"], restored["description"], now, field["id"]),
            )
            conn.execute(
                "INSERT INTO field_versions(field_id,version,label,value_type,description,reason,evaluator,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    field["id"], version, restored["label"], restored["value_type"],
                    restored["description"], reason, evaluator, now,
                ),
            )
            return {"type": action_type, "field_id": field["id"], "version": version, "restored": restored}

        if action_type == "set_guardrail":
            field = self._resolve_field_conn(conn, str(action.get("field_id", "")))
            protected = bool(action.get("protected", False))
            cur = conn.execute(
                "INSERT INTO field_guardrails(field_id,protected,reason,evaluator,created_at) VALUES(?,?,?,?,?)",
                (field["id"], int(protected), reason, evaluator, now),
            )
            return {"type": action_type, "field_id": field["id"], "guardrail_id": int(cur.lastrowid), "protected": protected}

        if action_type == "rollback_accept_proposal":
            mode = str(action.get("mode", ""))
            if mode == "deprecate_created_field":
                field = self._resolve_field_conn(conn, str(action.get("target_field_id", "")))
                from_status = field["status"]
                if from_status not in {"active", "converged"}:
                    raise ValueError(f"created field cannot be compensated from status {from_status}")
                conn.execute(
                    "UPDATE fields SET status='deprecated',updated_at=? WHERE id=?",
                    (now, field["id"]),
                )
                conn.execute(
                    "INSERT INTO field_events(field_id,event_type,from_status,to_status,reason,evidence_json,evaluator,created_at) VALUES(?,'deprecated',?,'deprecated',?,?,?,?)",
                    (
                        field["id"], from_status, reason,
                        canonical_json({"rollback_of_commit": commit["id"]}), evaluator, now,
                    ),
                )
                return {"type": action_type, "mode": mode, "field_id": field["id"], "from_status": from_status, "to_status": "deprecated"}
            if mode == "remove_alias":
                alias_id = action.get("alias_id")
                if alias_id is None:
                    raise ValueError("rollback alias id missing")
                row = conn.execute("SELECT * FROM field_aliases WHERE id=?", (int(alias_id),)).fetchone()
                if row is None:
                    raise ValueError("rollback alias no longer exists")
                conn.execute("DELETE FROM field_aliases WHERE id=?", (int(alias_id),))
                return {"type": action_type, "mode": mode, "alias_id": int(alias_id), "field_id": row["field_id"]}
            if mode == "no_op":
                return {"type": action_type, "mode": mode}
            raise ValueError(f"unsupported accept-proposal rollback mode: {mode}")

        raise ValueError(f"unsupported rollback action: {action_type}")

    def rollback_commit(self, commit_id: str, *, evaluator: str = "") -> dict[str, Any]:
        commit = self.get_commit(commit_id)
        with self.db.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM autonomy_rollback_receipts WHERE commit_id=?", (commit_id,)
            ).fetchone():
                raise ValueError("commit already rolled back")
        try:
            with self.db.connect() as conn:
                before_sha = self._canonical_fingerprint_conn(conn)
                mutation = self._apply_rollback_action(conn, commit, evaluator=str(evaluator))
                after_sha = self._canonical_fingerprint_conn(conn)
                rollback_id = uuid4().hex
                now = _now()
                conn.execute(
                    "INSERT INTO autonomy_rollback_receipts(id,commit_id,before_state_sha256,after_state_sha256,mutation_json,evaluator,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        rollback_id, commit_id, before_sha, after_sha,
                        canonical_json(mutation), str(evaluator), now,
                    ),
                )
                conn.execute(
                    "INSERT INTO autonomy_commit_events(decision_id,commit_id,event_type,detail_json,created_at) VALUES(?,?,'rolled_back',?,?)",
                    (
                        commit["decision_id"], commit_id,
                        canonical_json({"rollback_id": rollback_id, "mode": commit["rollback_mode"]}), now,
                    ),
                )
            return self.get_rollback(rollback_id)
        except Exception as exc:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO autonomy_commit_events(decision_id,commit_id,event_type,detail_json,created_at) VALUES(?,?,'rollback_failed',?,?)",
                    (
                        commit["decision_id"], commit_id,
                        canonical_json({"code": "ROLLBACK_FAILED", "message": str(exc)}), _now(),
                    ),
                )
            raise

    def stats(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            decision_rows = conn.execute(
                "SELECT decision,properties_json FROM autonomy_decisions"
            ).fetchall()
            commit_count = int(conn.execute("SELECT COUNT(*) FROM autonomy_commit_receipts").fetchone()[0])
            rollback_count = int(conn.execute("SELECT COUNT(*) FROM autonomy_rollback_receipts").fetchone()[0])
            commit_failure_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM autonomy_commit_events WHERE event_type='failed'"
                ).fetchone()[0]
            )
        counts = {name: 0 for name in ("EXECUTE", "ESCALATE", "DEFER", "REFUSE", "IDLE")}
        novel_total = 0
        novel_execute = 0
        for row in decision_rows:
            counts[row["decision"]] = counts.get(row["decision"], 0) + 1
            props = _loads(row["properties_json"], {})
            if not bool(props.get("known_action", False)):
                novel_total += 1
                if row["decision"] == "EXECUTE":
                    novel_execute += 1
        decision_count = len(decision_rows)
        governed = counts["EXECUTE"] + counts["ESCALATE"] + counts["DEFER"] + counts["REFUSE"]
        return {
            "decision_count": decision_count,
            "execute_count": counts["EXECUTE"],
            "escalate_count": counts["ESCALATE"],
            "defer_count": counts["DEFER"],
            "refuse_count": counts["REFUSE"],
            "idle_count": counts["IDLE"],
            "commit_count": commit_count,
            "commit_failure_count": commit_failure_count,
            "rollback_count": rollback_count,
            "autonomous_commit_rate": commit_count / counts["EXECUTE"] if counts["EXECUTE"] else 0.0,
            "escalation_rate": counts["ESCALATE"] / decision_count if decision_count else 0.0,
            "defer_rate": counts["DEFER"] / decision_count if decision_count else 0.0,
            "rollback_rate": rollback_count / commit_count if commit_count else 0.0,
            "novel_action_execute_rate": novel_execute / novel_total if novel_total else 0.0,
            "effective_autonomy_proxy": counts["EXECUTE"] / governed if governed else 0.0,
        }

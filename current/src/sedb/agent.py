"""Provider-neutral advisory Field Agent primitives."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .naming import normalize_field_key


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _primitive_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "json"


def _pointer_escape(token: str) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _label_from_key(key: str) -> str:
    return " ".join(part.capitalize() for part in key.split("_") if part)


class DeterministicDiscoveryBackend:
    """Reference structural discovery backend; intentionally not an LLM."""

    name = "deterministic-discovery-v1"

    def suggest(self, observation: Any) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}

        def record(parts: list[str], value: Any, pointer: str) -> None:
            if not parts:
                return
            key = normalize_field_key("_".join(parts))
            item = found.setdefault(key, {"types": set(), "evidence_refs": []})
            item["types"].add(_primitive_type(value))
            ref = f"obs:pending#{pointer or '/'}"
            if ref not in item["evidence_refs"]:
                item["evidence_refs"].append(ref)

        def walk(value: Any, parts: list[str], pointer: str) -> None:
            if isinstance(value, dict):
                for raw_key in sorted(value, key=lambda x: str(x)):
                    child = value[raw_key]
                    key = str(raw_key)
                    child_parts = parts + [key]
                    child_pointer = f"{pointer}/{_pointer_escape(key)}"
                    if isinstance(child, dict):
                        walk(child, child_parts, child_pointer)
                    elif isinstance(child, list):
                        if child and all(isinstance(item, dict) for item in child):
                            for index, item in enumerate(child):
                                walk(item, child_parts, f"{child_pointer}/{index}")
                        else:
                            record(child_parts, child, child_pointer)
                    else:
                        record(child_parts, child, child_pointer)
                return
            if isinstance(value, list):
                if value and all(isinstance(item, dict) for item in value):
                    for index, item in enumerate(value):
                        walk(item, parts, f"{pointer}/{index}")
                elif parts:
                    record(parts, value, pointer)
                return
            record(parts, value, pointer)

        # A top-level records array represents repeated records, not a field named "records".
        if isinstance(observation, dict) and isinstance(observation.get("records"), list):
            records = observation["records"]
            for index, item in enumerate(records):
                walk(item, [], f"/records/{index}")
            for key in sorted(k for k in observation if k != "records"):
                walk({key: observation[key]}, [], "")
        else:
            walk(observation, [], "")

        result: list[dict[str, Any]] = []
        for key in sorted(found):
            entry = found[key]
            types = sorted(entry["types"])
            value_type = types[0] if len(types) == 1 else "json"
            confidence = 1.0 if len(types) == 1 else 0.65
            result.append(
                {
                    "key": key,
                    "label": _label_from_key(key),
                    "value_type": value_type,
                    "description": "",
                    "reason": "Discovered as a repeated structural field in the observation packet.",
                    "confidence": confidence,
                    "evidence_refs": sorted(entry["evidence_refs"]),
                    "observed_types": types,
                }
            )
        return result


class ExternalSuggestionBackend:
    """Provider-neutral validator for suggestions produced by an external AI/runtime."""

    name = "external-suggestion-v1"

    def validate(self, packet: Any) -> list[dict[str, Any]]:
        if not isinstance(packet, dict) or not isinstance(packet.get("suggestions"), list):
            raise ValueError("external packet requires suggestions array")
        result: list[dict[str, Any]] = []
        for raw in packet["suggestions"]:
            if not isinstance(raw, dict):
                raise ValueError("suggestion must be an object")
            raw_key = str(raw.get("key", "")).strip()
            if not raw_key:
                raise ValueError("suggestion key is required")
            key = normalize_field_key(raw_key)
            label = str(raw.get("label", "")).strip()
            if not label:
                raise ValueError("suggestion label is required")
            reason = str(raw.get("reason", "")).strip()
            if not reason:
                raise ValueError("suggestion reason is required")
            value_type = str(raw.get("value_type", "text")).strip() or "text"
            try:
                confidence = float(raw.get("confidence", 0.5))
            except (TypeError, ValueError) as exc:
                raise ValueError("suggestion confidence must be numeric") from exc
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("suggestion confidence must be between 0 and 1")
            evidence_refs = raw.get("evidence_refs", [])
            if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
                raise ValueError("suggestion evidence_refs must be an array of strings")
            result.append(
                {
                    "key": key,
                    "label": label,
                    "value_type": value_type,
                    "description": str(raw.get("description", "")),
                    "reason": reason,
                    "confidence": confidence,
                    "evidence_refs": list(evidence_refs),
                }
            )
        return result

from datetime import datetime, timezone
from uuid import uuid4

from .db import Database
from .fields import FieldService
from .governance import resolve_field_row
from .semantic import SemanticDedupService
from .utility import UtilityService
from .family import FieldFamilyService


AGENT_POLICY_VERSION = "agent-v1"
DEFAULT_BUDGET = {
    "max_steps": 100,
    "max_observations": 500,
    "max_proposals": 30,
    "max_candidate_scores": 20,
    "max_family_proposals": 5,
    "max_assessments": 50,
}
DEFAULT_COUNTERS = {
    "steps": 0,
    "observations": 0,
    "proposals": 0,
    "candidate_scores": 0,
    "family_proposals": 0,
    "assessments": 0,
}
ALLOWED_AGENT_INTENTS = {
    "create_proposal",
    "score_proposal",
    "assess_field",
    "propose_family",
}
DENIED_AGENT_INTENTS = {
    "create_field",
    "decide_proposal",
    "review_candidate",
    "merge_fields",
    "split_field",
    "update_definition",
    "apply_assessment",
    "review_family",
    "set_cell",
    "delete_cell",
    "set_guardrail",
}
_COUNTER_FOR_INTENT = {
    "create_proposal": "proposals",
    "score_proposal": "candidate_scores",
    "assess_field": "assessments",
    "propose_family": "family_proposals",
}
_BUDGET_FOR_COUNTER = {
    "proposals": "max_proposals",
    "candidate_scores": "max_candidate_scores",
    "assessments": "max_assessments",
    "family_proposals": "max_family_proposals",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_run_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["budget"] = json.loads(item.pop("budget_json"))
    item["counters"] = json.loads(item.pop("counters_json"))
    return item


def _decode_observation(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def _decode_action(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["input"] = json.loads(item.pop("input_json"))
    item["output"] = json.loads(item.pop("output_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["evidence_refs"] = list(item["evidence"].get("refs", []))
    return item


def _decode_event(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["detail"] = json.loads(item.pop("detail_json"))
    return item


class AgentService:
    """Budgeted advisory runtime. It does not expose canonical mutation capabilities."""

    def __init__(self, db: Database):
        self.db = db

    def _normalize_budget(self, budget: dict[str, Any] | None) -> dict[str, int]:
        result = dict(DEFAULT_BUDGET)
        if budget:
            unknown = set(budget) - set(DEFAULT_BUDGET)
            if unknown:
                raise ValueError(f"unknown agent budget keys: {sorted(unknown)}")
            for key, value in budget.items():
                try:
                    parsed = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"agent budget {key} must be an integer") from exc
                if parsed < 0:
                    raise ValueError(f"agent budget {key} cannot be negative")
                result[key] = parsed
        return result

    def _registry_basis(self, namespace: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            fields = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT id,normalized_key,status,updated_at
                    FROM fields WHERE namespace=? ORDER BY id
                    """,
                    (namespace,),
                ).fetchall()
            ]
            aliases = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT normalized_alias,field_id
                    FROM field_aliases WHERE namespace=? ORDER BY normalized_alias,field_id
                    """,
                    (namespace,),
                ).fetchall()
            ]
            families = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT fm.family_id,fm.field_id
                    FROM field_family_members fm
                    JOIN field_families f ON f.id=fm.family_id
                    WHERE f.namespace=? AND f.status='active'
                    ORDER BY fm.family_id,fm.ordinal
                    """,
                    (namespace,),
                ).fetchall()
            ]
            task_membership = [
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT tvf.view_id,tvf.field_id,tvf.ordinal
                    FROM task_view_fields tvf
                    JOIN fields f ON f.id=tvf.field_id
                    WHERE f.namespace=?
                    ORDER BY tvf.view_id,tvf.ordinal
                    """,
                    (namespace,),
                ).fetchall()
            ]
        return {
            "namespace": namespace,
            "fields": fields,
            "aliases": aliases,
            "families": families,
            "task_membership": task_membership,
        }

    def create_run(
        self,
        *,
        backend: str,
        namespace: str = "global",
        budget: dict[str, Any] | None = None,
        input_payload: Any | None = None,
        evaluator: str = "system:agent",
    ) -> dict[str, Any]:
        backend = str(backend).strip()
        if not backend:
            raise ValueError("agent backend is required")
        namespace = str(namespace).strip() or "global"
        normalized_budget = self._normalize_budget(budget)
        counters = dict(DEFAULT_COUNTERS)
        run_id = uuid4().hex
        now = _now()
        input_value = {} if input_payload is None else input_payload
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO field_agent_runs(
                    id,backend,namespace,policy_version,status,budget_json,counters_json,
                    input_sha256,basis_sha256,evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    backend,
                    namespace,
                    AGENT_POLICY_VERSION,
                    "created",
                    canonical_json(normalized_budget),
                    canonical_json(counters),
                    json_sha256(input_value),
                    json_sha256(self._registry_basis(namespace)),
                    str(evaluator),
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
                (run_id, "created", canonical_json({"backend": backend}), now),
            )
        return self.get_run(run_id)

    def _require_run_row(self, conn: Any, run_id: str) -> Any:
        row = conn.execute("SELECT * FROM field_agent_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"agent run not found: {run_id}")
        return row

    def _start_if_needed(self, conn: Any, run: Any, now: str) -> Any:
        if run["status"] == "created":
            conn.execute(
                "UPDATE field_agent_runs SET status='running',started_at=? WHERE id=?",
                (now, run["id"]),
            )
            conn.execute(
                "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
                (run["id"], "started", "{}", now),
            )
            return self._require_run_row(conn, run["id"])
        return run

    def _mark_budget_exhausted(self, conn: Any, run_id: str, detail: dict[str, Any], now: str) -> None:
        row = self._require_run_row(conn, run_id)
        if row["status"] != "budget_exhausted":
            conn.execute(
                "UPDATE field_agent_runs SET status='budget_exhausted',completed_at=? WHERE id=?",
                (now, run_id),
            )
            conn.execute(
                "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
                (run_id, "budget_exhausted", canonical_json(detail), now),
            )

    def _next_action_ordinal(self, conn: Any, run_id: str) -> int:
        return int(
            conn.execute(
                "SELECT COALESCE(MAX(ordinal),-1)+1 FROM field_agent_actions WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )

    def record_observation(self, run_id: str, payload: Any) -> dict[str, Any]:
        now = _now()
        with self.db.connect() as conn:
            run = self._require_run_row(conn, run_id)
            if run["status"] in {"completed", "budget_exhausted", "failed"}:
                raise ValueError(f"agent run is terminal: {run['status']}")
            run = self._start_if_needed(conn, run, now)
            budget = json.loads(run["budget_json"])
            counters = json.loads(run["counters_json"])
            if counters["steps"] >= budget["max_steps"] or counters["observations"] >= budget["max_observations"]:
                self._mark_budget_exhausted(
                    conn,
                    run_id,
                    {"dimension": "observations", "counters": counters, "budget": budget},
                    now,
                )
                raise ValueError("agent observation budget exhausted")
            ordinal = counters["observations"]
            raw = canonical_json(payload)
            cur = conn.execute(
                """
                INSERT INTO field_agent_observations(run_id,ordinal,payload_json,payload_sha256,created_at)
                VALUES(?,?,?,?,?)
                """,
                (run_id, ordinal, raw, json_sha256(payload), now),
            )
            counters["observations"] += 1
            counters["steps"] += 1
            conn.execute(
                "UPDATE field_agent_runs SET counters_json=? WHERE id=?",
                (canonical_json(counters), run_id),
            )
            row = conn.execute(
                "SELECT * FROM field_agent_observations WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return _decode_observation(row)

    def execute_intent(
        self,
        run_id: str,
        intent: str,
        input_data: dict[str, Any] | None = None,
        *,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        intent = str(intent).strip()
        input_data = dict(input_data or {})
        evidence_refs = list(evidence_refs or [])
        now = _now()
        with self.db.connect() as conn:
            run = self._require_run_row(conn, run_id)
            if run["status"] in {"completed", "failed"}:
                raise ValueError(f"agent run is terminal: {run['status']}")
            run = self._start_if_needed(conn, run, now)
            budget = json.loads(run["budget_json"])
            counters = json.loads(run["counters_json"])
            ordinal = self._next_action_ordinal(conn, run_id)
            allowed = intent in ALLOWED_AGENT_INTENTS
            known_denied = intent in DENIED_AGENT_INTENTS
            capability_decision = "ALLOWED" if allowed else "DENIED"

            counter_key = _COUNTER_FOR_INTENT.get(intent)
            exhausted_dimension = None
            if counters["steps"] >= budget["max_steps"]:
                exhausted_dimension = "max_steps"
            elif allowed and counter_key:
                budget_key = _BUDGET_FOR_COUNTER[counter_key]
                if counters[counter_key] >= budget[budget_key]:
                    exhausted_dimension = budget_key

            if exhausted_dimension is not None:
                outcome = "BUDGET_EXHAUSTED"
                reason = f"Agent budget exhausted: {exhausted_dimension}."
                self._mark_budget_exhausted(
                    conn,
                    run_id,
                    {"dimension": exhausted_dimension, "intent": intent, "counters": counters, "budget": budget},
                    now,
                )
            elif allowed:
                outcome = "AUTHORIZED"
                reason = "Advisory capability authorized; no operation executed by the gate itself."
                counters["steps"] += 1
                if counter_key:
                    counters[counter_key] += 1
                conn.execute(
                    "UPDATE field_agent_runs SET counters_json=? WHERE id=?",
                    (canonical_json(counters), run_id),
                )
            else:
                outcome = "DENIED"
                if known_denied:
                    reason = "Denied: canonical mutation capability is outside autonomous agent authority."
                else:
                    reason = "Denied: unsupported autonomous agent capability."
                if counters["steps"] < budget["max_steps"]:
                    counters["steps"] += 1
                    conn.execute(
                        "UPDATE field_agent_runs SET counters_json=? WHERE id=?",
                        (canonical_json(counters), run_id),
                    )

            cur = conn.execute(
                """
                INSERT INTO field_agent_actions(
                    run_id,ordinal,intent,capability_decision,outcome,input_json,output_json,
                    reason,evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    ordinal,
                    intent,
                    capability_decision,
                    outcome,
                    canonical_json(input_data),
                    "{}",
                    reason,
                    canonical_json({"refs": evidence_refs}),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM field_agent_actions WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return _decode_action(row)

    def _insert_action_receipt(
        self,
        run_id: str,
        *,
        intent: str,
        capability_decision: str,
        outcome: str,
        input_data: dict[str, Any] | None = None,
        output_data: Any | None = None,
        reason: str = "",
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.db.connect() as conn:
            ordinal = self._next_action_ordinal(conn, run_id)
            cur = conn.execute(
                """
                INSERT INTO field_agent_actions(
                    run_id,ordinal,intent,capability_decision,outcome,input_json,output_json,
                    reason,evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    ordinal,
                    intent,
                    capability_decision,
                    outcome,
                    canonical_json(input_data or {}),
                    canonical_json({} if output_data is None else output_data),
                    str(reason),
                    canonical_json({"refs": list(evidence_refs or [])}),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM field_agent_actions WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return _decode_action(row)

    def _reserve_advisory_budget(self, run_id: str, intent: str, *, consume_specific: bool = True) -> tuple[bool, str | None]:
        """Reserve one action attempt outside the later service transaction."""
        now = _now()
        with self.db.connect() as conn:
            run = self._require_run_row(conn, run_id)
            if run["status"] in {"completed", "failed"}:
                raise ValueError(f"agent run is terminal: {run['status']}")
            if run["status"] == "budget_exhausted":
                return False, "already_exhausted"
            run = self._start_if_needed(conn, run, now)
            budget = json.loads(run["budget_json"])
            counters = json.loads(run["counters_json"])
            counter_key = _COUNTER_FOR_INTENT.get(intent)
            exhausted = None
            if counters["steps"] >= budget["max_steps"]:
                exhausted = "max_steps"
            elif consume_specific and counter_key:
                budget_key = _BUDGET_FOR_COUNTER[counter_key]
                if counters[counter_key] >= budget[budget_key]:
                    exhausted = budget_key
            if exhausted:
                self._mark_budget_exhausted(
                    conn,
                    run_id,
                    {"dimension": exhausted, "intent": intent, "counters": counters, "budget": budget},
                    now,
                )
                return False, exhausted
            counters["steps"] += 1
            if consume_specific and counter_key:
                counters[counter_key] += 1
            conn.execute(
                "UPDATE field_agent_runs SET counters_json=? WHERE id=?",
                (canonical_json(counters), run_id),
            )
        return True, None

    def _execute_advisory_operation(
        self,
        run_id: str,
        intent: str,
        input_data: dict[str, Any],
        *,
        evidence_refs: list[str] | None,
        handler: Any,
        success_outcome: str,
    ) -> dict[str, Any]:
        if intent not in ALLOWED_AGENT_INTENTS:
            return self.execute_intent(run_id, intent, input_data, evidence_refs=evidence_refs)
        allowed, exhausted = self._reserve_advisory_budget(run_id, intent, consume_specific=True)
        if not allowed:
            return self._insert_action_receipt(
                run_id,
                intent=intent,
                capability_decision="ALLOWED",
                outcome="BUDGET_EXHAUSTED",
                input_data=input_data,
                reason=f"Agent budget exhausted: {exhausted}.",
                evidence_refs=evidence_refs,
            )
        try:
            output = handler()
        except Exception as exc:
            self._insert_action_receipt(
                run_id,
                intent=intent,
                capability_decision="ALLOWED",
                outcome="ERROR",
                input_data=input_data,
                output_data={"error": str(exc)},
                reason="Advisory operation failed after authorization.",
                evidence_refs=evidence_refs,
            )
            raise
        return self._insert_action_receipt(
            run_id,
            intent=intent,
            capability_decision="ALLOWED",
            outcome=success_outcome,
            input_data=input_data,
            output_data=output,
            reason="Advisory operation executed through an allowed capability.",
            evidence_refs=evidence_refs,
        )

    def _record_skip(
        self,
        run_id: str,
        *,
        intent: str,
        outcome: str,
        input_data: dict[str, Any],
        output_data: Any | None = None,
        reason: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        allowed, exhausted = self._reserve_advisory_budget(run_id, intent, consume_specific=False)
        if not allowed:
            return self._insert_action_receipt(
                run_id,
                intent=intent,
                capability_decision="ALLOWED",
                outcome="BUDGET_EXHAUSTED",
                input_data=input_data,
                reason=f"Agent budget exhausted: {exhausted}.",
                evidence_refs=evidence_refs,
            )
        return self._insert_action_receipt(
            run_id,
            intent=intent,
            capability_decision="ALLOWED",
            outcome=outcome,
            input_data=input_data,
            output_data=output_data,
            reason=reason,
            evidence_refs=evidence_refs,
        )

    def _represented_field(self, key: str, namespace: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            try:
                return dict(resolve_field_row(conn, key, namespace))
            except KeyError:
                return None

    def _pending_proposal(self, key: str, namespace: str) -> dict[str, Any] | None:
        normalized = normalize_field_key(key)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_proposals WHERE namespace=? AND status='pending' ORDER BY created_at,id",
                (namespace,),
            ).fetchall()
        for row in rows:
            try:
                if normalize_field_key(row["key"]) == normalized:
                    return dict(row)
            except ValueError:
                continue
        return None

    def _latest_observation_id(self, run_id: str) -> int | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM field_agent_observations WHERE run_id=? ORDER BY ordinal DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return None if row is None else int(row["id"])

    @staticmethod
    def _bind_evidence_refs(refs: list[str], observation_id: int | None) -> list[str]:
        if observation_id is None:
            return list(refs)
        prefix = f"obs:{observation_id}"
        return [ref.replace("obs:pending", prefix, 1) if ref.startswith("obs:pending") else ref for ref in refs]

    def _maybe_assess_and_family(
        self,
        run_id: str,
        field: dict[str, Any],
        *,
        assess_existing: bool,
        propose_families: bool,
        family_seed_threshold: float,
        family_min_coherence: float,
        evidence_refs: list[str],
    ) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        if assess_existing and field.get("status") in {"active", "converged"}:
            receipts.append(
                self._execute_advisory_operation(
                    run_id,
                    "assess_field",
                    {"field_id": field["id"]},
                    evidence_refs=evidence_refs,
                    handler=lambda: UtilityService(self.db).assess_field(
                        field["id"], evaluator=f"agent:{run_id}"
                    ),
                    success_outcome="ASSESSED_FIELD",
                )
            )
        if propose_families and field.get("status") in {"active", "converged", "proposed"}:
            receipt = self._execute_advisory_operation(
                run_id,
                "propose_family",
                {"seed_field_id": field["id"]},
                evidence_refs=evidence_refs,
                handler=lambda: FieldFamilyService(self.db).propose_from_seed(
                    field["id"],
                    seed_threshold=family_seed_threshold,
                    min_coherence=family_min_coherence,
                    namespace=field.get("namespace", "global"),
                    evaluator=f"agent:{run_id}",
                ),
                success_outcome="PROPOSED_FAMILY",
            )
            # A valid attempt may find no coherent family; keep that fact explicit.
            if receipt["output"] is None:
                # Receipts are immutable, so express no-result through a second explanatory skip receipt.
                receipts.append(receipt)
            else:
                receipts.append(receipt)
        return receipts

    def execute_suggestions(
        self,
        run_id: str,
        suggestions: list[dict[str, Any]],
        *,
        score_proposals: bool = True,
        assess_existing: bool = True,
        propose_families: bool = False,
        score_top_k: int = 5,
        family_seed_threshold: float = 0.78,
        family_min_coherence: float = 0.72,
    ) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if run["status"] in {"completed", "budget_exhausted", "failed"}:
            raise ValueError(f"agent run is terminal: {run['status']}")
        namespace = run["namespace"]
        observation_id = self._latest_observation_id(run_id)
        receipts: list[dict[str, Any]] = []
        seen: set[str] = set()

        for raw in suggestions:
            if self.get_run(run_id)["status"] == "budget_exhausted":
                break
            suggestion = dict(raw)
            key = normalize_field_key(str(suggestion.get("key", "")))
            suggestion["key"] = key
            refs = self._bind_evidence_refs(list(suggestion.get("evidence_refs", [])), observation_id)
            normalized = normalize_field_key(key)
            if normalized in seen:
                receipts.append(
                    self._record_skip(
                        run_id,
                        intent="create_proposal",
                        outcome="SKIPPED_DUPLICATE_SUGGESTION",
                        input_data=suggestion,
                        reason="The same normalized field identity was already handled in this run batch.",
                        evidence_refs=refs,
                    )
                )
                continue
            seen.add(normalized)

            # Re-resolve immediately before proposing to close the stale-observation window.
            represented = self._represented_field(key, namespace)
            if represented is not None:
                receipts.append(
                    self._record_skip(
                        run_id,
                        intent="create_proposal",
                        outcome="SKIPPED_ALREADY_REPRESENTED",
                        input_data=suggestion,
                        output_data={"field_id": represented["id"], "key": represented["key"]},
                        reason="A canonical field or alias now represents this identity.",
                        evidence_refs=refs,
                    )
                )
                receipts.extend(
                    self._maybe_assess_and_family(
                        run_id,
                        represented,
                        assess_existing=assess_existing,
                        propose_families=propose_families,
                        family_seed_threshold=family_seed_threshold,
                        family_min_coherence=family_min_coherence,
                        evidence_refs=refs,
                    )
                )
                continue

            pending = self._pending_proposal(key, namespace)
            if pending is not None:
                receipts.append(
                    self._record_skip(
                        run_id,
                        intent="create_proposal",
                        outcome="SKIPPED_PENDING_PROPOSAL",
                        input_data=suggestion,
                        output_data={"proposal_id": pending["id"]},
                        reason="A pending proposal already represents this normalized field identity.",
                        evidence_refs=refs,
                    )
                )
                continue

            create_receipt = self._execute_advisory_operation(
                run_id,
                "create_proposal",
                suggestion,
                evidence_refs=refs,
                handler=lambda suggestion=suggestion: FieldService(self.db).create_proposal(
                    key=suggestion["key"],
                    label=str(suggestion.get("label") or suggestion["key"]),
                    reason=str(suggestion.get("reason") or "Agent-discovered field candidate"),
                    value_type=str(suggestion.get("value_type", "text")),
                    description=str(suggestion.get("description", "")),
                    proposed_by=f"agent:{run_id}",
                    namespace=namespace,
                ),
                success_outcome="CREATED_PROPOSAL",
            )
            receipts.append(create_receipt)
            if create_receipt["outcome"] != "CREATED_PROPOSAL":
                continue
            proposal = create_receipt["output"]
            if score_proposals and self.get_run(run_id)["status"] != "budget_exhausted":
                receipts.append(
                    self._execute_advisory_operation(
                        run_id,
                        "score_proposal",
                        {"proposal_id": proposal["id"], "top_k": score_top_k},
                        evidence_refs=refs,
                        handler=lambda proposal_id=proposal["id"]: SemanticDedupService(self.db).score_proposal(
                            proposal_id, top_k=score_top_k
                        ),
                        success_outcome="SCORED_PROPOSAL",
                    )
                )
        return receipts

    def _finish_run(self, run_id: str) -> None:
        now = _now()
        with self.db.connect() as conn:
            run = self._require_run_row(conn, run_id)
            if run["status"] == "budget_exhausted":
                return
            if run["status"] in {"completed", "failed"}:
                return
            conn.execute(
                "UPDATE field_agent_runs SET status='completed',completed_at=? WHERE id=?",
                (now, run_id),
            )
            conn.execute(
                "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
                (run_id, "completed", "{}", now),
            )

    def _fail_run(self, run_id: str, error: Exception) -> None:
        now = _now()
        with self.db.connect() as conn:
            run = self._require_run_row(conn, run_id)
            if run["status"] in {"completed", "budget_exhausted", "failed"}:
                return
            conn.execute(
                "UPDATE field_agent_runs SET status='failed',completed_at=?,last_error=? WHERE id=?",
                (now, str(error), run_id),
            )
            conn.execute(
                "INSERT INTO field_agent_run_events(run_id,event_type,detail_json,created_at) VALUES(?,?,?,?)",
                (run_id, "failed", canonical_json({"error": str(error)}), now),
            )

    def run_deterministic(
        self,
        observation: Any,
        *,
        namespace: str = "global",
        budget: dict[str, Any] | None = None,
        evaluator: str = "system:agent",
        score_proposals: bool = True,
        assess_existing: bool = True,
        propose_families: bool = False,
        score_top_k: int = 5,
        family_seed_threshold: float = 0.78,
        family_min_coherence: float = 0.72,
    ) -> dict[str, Any]:
        run = self.create_run(
            backend=DeterministicDiscoveryBackend.name,
            namespace=namespace,
            budget=budget,
            input_payload=observation,
            evaluator=evaluator,
        )
        try:
            obs = self.record_observation(run["id"], observation)
            suggestions = DeterministicDiscoveryBackend().suggest(observation)
            # Evidence placeholders are bound to the persisted observation by execute_suggestions.
            self.execute_suggestions(
                run["id"],
                suggestions,
                score_proposals=score_proposals,
                assess_existing=assess_existing,
                propose_families=propose_families,
                score_top_k=score_top_k,
                family_seed_threshold=family_seed_threshold,
                family_min_coherence=family_min_coherence,
            )
            self._finish_run(run["id"])
        except Exception as exc:
            self._fail_run(run["id"], exc)
            raise
        return self.get_run(run["id"])

    def run_external(
        self,
        packet: Any,
        *,
        namespace: str = "global",
        budget: dict[str, Any] | None = None,
        evaluator: str = "external:agent",
        score_proposals: bool = True,
        assess_existing: bool = True,
        propose_families: bool = False,
        score_top_k: int = 5,
        family_seed_threshold: float = 0.78,
        family_min_coherence: float = 0.72,
    ) -> dict[str, Any]:
        suggestions = ExternalSuggestionBackend().validate(packet)
        run = self.create_run(
            backend=ExternalSuggestionBackend.name,
            namespace=namespace,
            budget=budget,
            input_payload=packet,
            evaluator=evaluator,
        )
        try:
            self.record_observation(run["id"], {"external_suggestions": suggestions})
            self.execute_suggestions(
                run["id"],
                suggestions,
                score_proposals=score_proposals,
                assess_existing=assess_existing,
                propose_families=propose_families,
                score_top_k=score_top_k,
                family_seed_threshold=family_seed_threshold,
                family_min_coherence=family_min_coherence,
            )
            self._finish_run(run["id"])
        except Exception as exc:
            self._fail_run(run["id"], exc)
            raise
        return self.get_run(run["id"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = self._require_run_row(conn, run_id)
            item = _decode_run_row(row)
            observations = conn.execute(
                "SELECT * FROM field_agent_observations WHERE run_id=? ORDER BY ordinal", (run_id,)
            ).fetchall()
            actions = conn.execute(
                "SELECT * FROM field_agent_actions WHERE run_id=? ORDER BY ordinal", (run_id,)
            ).fetchall()
            events = conn.execute(
                "SELECT * FROM field_agent_run_events WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        item["observations"] = [_decode_observation(row) for row in observations]
        item["actions"] = [_decode_action(row) for row in actions]
        item["events"] = [_decode_event(row) for row in events]
        return item

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_agent_runs ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                (max(1, min(int(limit), 1000)), max(0, int(offset))),
            ).fetchall()
        return [_decode_run_row(row) for row in rows]

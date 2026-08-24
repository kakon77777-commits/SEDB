"""Deterministic field utility and lifecycle recommendation services."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from .db import Database
from .fields import FieldService
from .governance import resolve_field_row


POLICY_VERSION = "utility-v1"
POLICY = {
    "weights": {
        "coverage": 0.45,
        "task_support": 0.40,
        "inverse_semantic_redundancy": 0.15,
    },
    "minimum_age_days": 7.0,
    "converge_threshold": 0.15,
    "review_threshold": 0.35,
}

_ALLOWED_FIELD_STATUSES = {
    "proposed", "active", "converged", "merged", "split", "deprecated"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _is_after(value: str | None, reference: str | None) -> bool:
    if not value or not reference:
        return False
    return _parse_time(value) > _parse_time(reference)


def _decode_guardrail(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["protected"] = bool(item["protected"])
    return item


def _decode_assessment(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["policy"] = json.loads(item.pop("policy_json"))
    return item


def _basis_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class UtilityService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Guardrails
    # ------------------------------------------------------------------
    def set_guardrail(
        self,
        field_ref: str,
        protected: bool,
        *,
        reason: str,
        evaluator: str = "",
    ) -> dict[str, Any]:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for guardrail changes")
        now = _now()
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref)
            cur = conn.execute(
                """
                INSERT INTO field_guardrails(field_id,protected,reason,evaluator,created_at)
                VALUES(?,?,?,?,?)
                """,
                (field["id"], int(bool(protected)), reason, str(evaluator), now),
            )
            row = conn.execute(
                "SELECT * FROM field_guardrails WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return _decode_guardrail(row)

    def get_guardrail(self, field_ref: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref)
            row = conn.execute(
                """
                SELECT * FROM field_guardrails
                WHERE field_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (field["id"],),
            ).fetchone()
        return None if row is None else _decode_guardrail(row)

    def list_guardrail_history(self, field_ref: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref)
            rows = conn.execute(
                "SELECT * FROM field_guardrails WHERE field_id=? ORDER BY id",
                (field["id"],),
            ).fetchall()
        return [_decode_guardrail(row) for row in rows]

    # ------------------------------------------------------------------
    # Evidence collection
    # ------------------------------------------------------------------
    def _single_field_evidence(
        self, field_ref: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.db.connect() as conn:
            field = dict(resolve_field_row(conn, field_ref))
            total_entities = int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
            cell_row = conn.execute(
                "SELECT COUNT(*) AS n, MAX(updated_at) AS latest FROM cells WHERE field_id=?",
                (field["id"],),
            ).fetchone()
            view_row = conn.execute(
                """
                SELECT COUNT(*) AS n, MAX(v.created_at) AS latest
                FROM task_view_fields tvf
                JOIN task_views v ON v.id=tvf.view_id
                WHERE tvf.field_id=?
                """,
                (field["id"],),
            ).fetchone()
            guardrail = conn.execute(
                "SELECT * FROM field_guardrails WHERE field_id=? ORDER BY id DESC LIMIT 1",
                (field["id"],),
            ).fetchone()
            semantic_rows = conn.execute(
                """
                SELECT id,score
                FROM semantic_candidates
                WHERE source_kind='field' AND status='pending'
                  AND (source_ref=? OR candidate_field_id=?)
                ORDER BY score DESC,id
                """,
                (field["id"], field["id"]),
            ).fetchall()
            converged_row = conn.execute(
                """
                SELECT created_at
                FROM field_events
                WHERE field_id=? AND event_type='converged'
                ORDER BY id DESC
                LIMIT 1
                """,
                (field["id"],),
            ).fetchone()

        semantic_redundancy = float(semantic_rows[0]["score"]) if semantic_rows else 0.0
        context = {
            "total_entities": total_entities,
            "cell_count": int(cell_row["n"]),
            "latest_cell_at": cell_row["latest"],
            "task_view_count": int(view_row["n"]),
            "latest_task_view_at": view_row["latest"],
            "protected": bool(guardrail["protected"]) if guardrail is not None else False,
            "guardrail_id": int(guardrail["id"]) if guardrail is not None else None,
            "semantic_redundancy": semantic_redundancy,
            "semantic_candidate_ids": [int(row["id"]) for row in semantic_rows],
            "latest_converged_at": converged_row["created_at"] if converged_row is not None else None,
        }
        return field, context

    def _collect_registry_evidence(
        self, fields: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Collect registry evidence in a fixed set of aggregate SQL passes."""
        if not fields:
            return {}
        selected = {field["id"] for field in fields}
        contexts = {
            field_id: {
                "total_entities": 0,
                "cell_count": 0,
                "latest_cell_at": None,
                "task_view_count": 0,
                "latest_task_view_at": None,
                "protected": False,
                "guardrail_id": None,
                "semantic_redundancy": 0.0,
                "semantic_candidate_ids": [],
                "latest_converged_at": None,
            }
            for field_id in selected
        }

        with self.db.connect() as conn:
            total_entities = int(conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
            for context in contexts.values():
                context["total_entities"] = total_entities

            for row in conn.execute(
                "SELECT field_id,COUNT(*) AS n,MAX(updated_at) AS latest FROM cells GROUP BY field_id"
            ).fetchall():
                if row["field_id"] in contexts:
                    contexts[row["field_id"]]["cell_count"] = int(row["n"])
                    contexts[row["field_id"]]["latest_cell_at"] = row["latest"]

            for row in conn.execute(
                """
                SELECT tvf.field_id,COUNT(*) AS n,MAX(v.created_at) AS latest
                FROM task_view_fields tvf
                JOIN task_views v ON v.id=tvf.view_id
                GROUP BY tvf.field_id
                """
            ).fetchall():
                if row["field_id"] in contexts:
                    contexts[row["field_id"]]["task_view_count"] = int(row["n"])
                    contexts[row["field_id"]]["latest_task_view_at"] = row["latest"]

            for row in conn.execute(
                """
                SELECT g.*
                FROM field_guardrails g
                JOIN (
                    SELECT field_id,MAX(id) AS max_id
                    FROM field_guardrails
                    GROUP BY field_id
                ) latest ON latest.max_id=g.id
                """
            ).fetchall():
                if row["field_id"] in contexts:
                    contexts[row["field_id"]]["protected"] = bool(row["protected"])
                    contexts[row["field_id"]]["guardrail_id"] = int(row["id"])

            for row in conn.execute(
                """
                SELECT id,source_ref,candidate_field_id,score
                FROM semantic_candidates
                WHERE source_kind='field' AND status='pending'
                ORDER BY id
                """
            ).fetchall():
                for field_id in {str(row["source_ref"]), str(row["candidate_field_id"])}:
                    if field_id in contexts:
                        context = contexts[field_id]
                        context["semantic_redundancy"] = max(
                            float(context["semantic_redundancy"]), float(row["score"])
                        )
                        context["semantic_candidate_ids"].append(int(row["id"]))

            for row in conn.execute(
                """
                SELECT e.field_id,e.created_at
                FROM field_events e
                JOIN (
                    SELECT field_id,MAX(id) AS max_id
                    FROM field_events
                    WHERE event_type='converged'
                    GROUP BY field_id
                ) latest ON latest.max_id=e.id
                """
            ).fetchall():
                if row["field_id"] in contexts:
                    contexts[row["field_id"]]["latest_converged_at"] = row["created_at"]

        for context in contexts.values():
            context["semantic_candidate_ids"] = sorted(set(context["semantic_candidate_ids"]))
        return contexts

    # ------------------------------------------------------------------
    # Assessment calculation and persistence
    # ------------------------------------------------------------------
    def _make_basis_payload(
        self,
        field: dict[str, Any],
        context: dict[str, Any],
        *,
        policy_version: str = POLICY_VERSION,
    ) -> dict[str, Any]:
        return {
            "field_id": field["id"],
            "field_status": field["status"],
            "field_updated_at": field["updated_at"],
            "total_entities": context["total_entities"],
            "cell_count": context["cell_count"],
            "latest_cell_at": context["latest_cell_at"],
            "task_view_count": context["task_view_count"],
            "latest_task_view_at": context["latest_task_view_at"],
            "semantic_redundancy": round(float(context["semantic_redundancy"]), 6),
            "semantic_candidate_ids": context["semantic_candidate_ids"],
            "guardrail_id": context["guardrail_id"],
            "protected": context["protected"],
            "latest_converged_at": context["latest_converged_at"],
            "policy_version": policy_version,
        }

    def _recommend(
        self,
        field: dict[str, Any],
        metrics: dict[str, Any],
    ) -> tuple[str, str]:
        status = field["status"]
        if status not in {"active", "converged"}:
            return "keep", f"Lifecycle status {status} is not utility-actionable in utility-v1."
        if status == "converged":
            if metrics["post_convergence_cell"] or metrics["post_convergence_task_view"]:
                return (
                    "reactivate_candidate",
                    "New cell or Task View evidence appeared after the latest convergence event.",
                )
            return (
                "keep",
                "No new cell or Task View evidence appeared after the latest convergence event.",
            )
        if metrics["protected"]:
            return "keep", "Latest field guardrail is protected."
        if metrics["total_entities"] == 0:
            return (
                "insufficient_evidence",
                "No entities exist yet, so sparse coverage cannot be evaluated.",
            )
        if (
            metrics["field_age_days"] < POLICY["minimum_age_days"]
            and metrics["cell_count"] == 0
            and metrics["task_view_count"] == 0
        ):
            return (
                "insufficient_evidence",
                "Field is new and has not yet accumulated cells or Task View support.",
            )
        if (
            metrics["field_age_days"] >= POLICY["minimum_age_days"]
            and metrics["cell_count"] == 0
            and metrics["task_view_count"] == 0
            and metrics["score"] <= POLICY["converge_threshold"]
        ):
            return (
                "converge_candidate",
                "Old unprotected field has no cells or Task View support at or below the convergence threshold.",
            )
        if metrics["score"] < POLICY["review_threshold"]:
            return (
                "review",
                "Operational utility is below the review threshold but evidence does not justify automatic convergence candidacy.",
            )
        return (
            "keep",
            "Operational utility is at or above the keep threshold or has explicit task/data support.",
        )

    def _build_assessment_payload(
        self,
        field: dict[str, Any],
        context: dict[str, Any],
        *,
        evaluator: str,
        as_of: str,
    ) -> dict[str, Any]:
        age_days = max(
            0.0,
            (_parse_time(as_of) - _parse_time(field["created_at"])).total_seconds() / 86400.0,
        )
        coverage = (
            0.0
            if context["total_entities"] == 0
            else context["cell_count"] / context["total_entities"]
        )
        task_support = 1.0 if context["task_view_count"] > 0 else 0.0
        redundancy = float(context["semantic_redundancy"])
        score = (
            POLICY["weights"]["coverage"] * coverage
            + POLICY["weights"]["task_support"] * task_support
            + POLICY["weights"]["inverse_semantic_redundancy"] * (1.0 - redundancy)
        )
        score = round(max(0.0, min(1.0, score)), 6)
        converged_at = context["latest_converged_at"]
        metrics = {
            "total_entities": context["total_entities"],
            "cell_count": context["cell_count"],
            "coverage": round(coverage, 6),
            "task_view_count": context["task_view_count"],
            "task_support": task_support,
            "semantic_redundancy": round(redundancy, 6),
            "field_age_days": round(age_days, 6),
            "protected": context["protected"],
            "post_convergence_cell": _is_after(context["latest_cell_at"], converged_at),
            "post_convergence_task_view": _is_after(
                context["latest_task_view_at"], converged_at
            ),
            "score": score,
        }
        recommendation, reason = self._recommend(field, metrics)
        evidence = {
            "field_id": field["id"],
            "field_updated_at": field["updated_at"],
            "latest_cell_at": context["latest_cell_at"],
            "latest_task_view_at": context["latest_task_view_at"],
            "guardrail_id": context["guardrail_id"],
            "semantic_candidate_ids": context["semantic_candidate_ids"],
            "latest_converged_at": context["latest_converged_at"],
        }
        basis_payload = self._make_basis_payload(field, context)
        return {
            "id": uuid4().hex,
            "field_id": field["id"],
            "policy_version": POLICY_VERSION,
            "field_status": field["status"],
            "score": score,
            "recommendation": recommendation,
            "reason": reason,
            "evaluator": str(evaluator),
            "metrics": metrics,
            "evidence": evidence,
            "policy": POLICY,
            "basis_sha256": _basis_hash(basis_payload),
            "as_of": as_of,
            "created_at": _now(),
        }

    def _persist_assessment_payloads(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        rows = []
        for item in payloads:
            rows.append(
                (
                    item["id"],
                    item["field_id"],
                    item["policy_version"],
                    item["field_status"],
                    item["score"],
                    item["recommendation"],
                    item["reason"],
                    item["evaluator"],
                    json.dumps(item["metrics"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["policy"], ensure_ascii=False, sort_keys=True),
                    item["basis_sha256"],
                    item["as_of"],
                    item["created_at"],
                )
            )
        with self.db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO field_utility_assessments(
                    id,field_id,policy_version,field_status,score,recommendation,reason,evaluator,
                    metrics_json,evidence_json,policy_json,basis_sha256,as_of,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )

    def assess_field(
        self,
        field_ref: str,
        *,
        evaluator: str = "system:utility",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        field, context = self._single_field_evidence(field_ref)
        payload = self._build_assessment_payload(
            field,
            context,
            evaluator=evaluator,
            as_of=as_of or _now(),
        )
        self._persist_assessment_payloads([payload])
        return payload

    def assess_registry(
        self,
        *,
        statuses: tuple[str, ...] = ("active", "converged"),
        limit_fields: int = 1000,
        offset: int = 0,
        evaluator: str = "system:utility",
        as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        statuses = tuple(dict.fromkeys(str(status).strip() for status in statuses if str(status).strip()))
        if not statuses:
            raise ValueError("at least one field status is required")
        invalid = [status for status in statuses if status not in _ALLOWED_FIELD_STATUSES]
        if invalid:
            raise ValueError(f"unsupported field status: {invalid[0]}")
        limit_fields = max(1, min(int(limit_fields), 10000))
        offset = max(0, int(offset))
        placeholders = ",".join("?" for _ in statuses)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fields WHERE status IN ({placeholders}) ORDER BY key,id LIMIT ? OFFSET ?",
                [*statuses, limit_fields, offset],
            ).fetchall()
        fields = [dict(row) for row in rows]
        if not fields:
            return []
        contexts = self._collect_registry_evidence(fields)
        assessed_at = as_of or _now()
        payloads = [
            self._build_assessment_payload(
                field,
                contexts[field["id"]],
                evaluator=evaluator,
                as_of=assessed_at,
            )
            for field in fields
        ]
        self._persist_assessment_payloads(payloads)
        return payloads

    def get_assessment(self, assessment_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_utility_assessments WHERE id=?", (assessment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"utility assessment not found: {assessment_id}")
        return _decode_assessment(row)

    def list_assessments(
        self, field_ref: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref)
            rows = conn.execute(
                """
                SELECT * FROM field_utility_assessments
                WHERE field_id=?
                ORDER BY created_at,id
                LIMIT ?
                """,
                (field["id"], max(1, min(int(limit), 10000))),
            ).fetchall()
        return [_decode_assessment(row) for row in rows]

    # ------------------------------------------------------------------
    # Explicit lifecycle application
    # ------------------------------------------------------------------
    def apply_assessment(
        self,
        assessment_id: str,
        *,
        reason: str,
        evaluator: str = "",
    ) -> dict[str, Any]:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required to apply a utility assessment")
        assessment = self.get_assessment(assessment_id)
        recommendation = assessment["recommendation"]
        actionable = {
            ("active", "converge_candidate"): "converged",
            ("converged", "reactivate_candidate"): "active",
        }
        target_status = actionable.get((assessment["field_status"], recommendation))
        if target_status is None:
            raise ValueError(
                f"utility assessment recommendation is not actionable: {recommendation}"
            )

        field, context = self._single_field_evidence(assessment["field_id"])
        current_basis = self._make_basis_payload(
            field, context, policy_version=assessment["policy_version"]
        )
        if _basis_hash(current_basis) != assessment["basis_sha256"]:
            raise ValueError("utility assessment is stale because its evidence basis changed")

        transition_evidence = {
            "assessment_id": assessment["id"],
            "policy_version": assessment["policy_version"],
            "assessment_reason": assessment["reason"],
            "basis_sha256": assessment["basis_sha256"],
        }
        transitioned = FieldService(self.db).transition(
            field["id"],
            target_status,
            reason=reason,
            evidence=transition_evidence,
            metrics=assessment["metrics"],
            evaluator=str(evaluator),
            reversible=True,
        )
        return {"assessment": assessment, "field": transitioned}

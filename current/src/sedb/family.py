"""Reviewed semantic field-family proposals built from bounded pairwise evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from .db import Database
from .governance import resolve_field_row
from .semantic import SemanticDedupService, _blocking_rank, score_field_pair


POLICY_VERSION = "family-v1"
_ACTIVE_SOURCE_STATUSES = ("proposed", "active", "converged")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_hash(payload: Any) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _decode_json_column(item: dict[str, Any], column: str, output: str) -> None:
    item[output] = json.loads(item.pop(column))


class FieldFamilyService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Proposal decoding / evidence
    # ------------------------------------------------------------------
    def _field_basis_rows(self, conn, field_ids: list[str]) -> list[dict[str, Any]]:
        if not field_ids:
            return []
        placeholders = ",".join("?" for _ in field_ids)
        rows = conn.execute(
            f"""
            SELECT f.id,f.namespace,f.key,f.label,f.value_type,f.description,
                   f.status,f.updated_at,COALESCE(MAX(v.version),0) AS definition_version
            FROM fields f
            LEFT JOIN field_versions v ON v.field_id=f.id
            WHERE f.id IN ({placeholders})
            GROUP BY f.id
            ORDER BY f.id
            """,
            field_ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def _semantic_basis_rows(self, conn, field_ids: list[str]) -> list[dict[str, Any]]:
        if not field_ids:
            return []
        placeholders = ",".join("?" for _ in field_ids)
        rows = conn.execute(
            f"""
            SELECT c.id,c.source_kind,c.source_ref,c.candidate_field_id,c.score,c.status,
                   r.id AS review_id,r.decision AS review_decision
            FROM semantic_candidates c
            LEFT JOIN semantic_candidate_reviews r ON r.candidate_id=c.id
            WHERE c.source_kind='field'
              AND (c.source_ref IN ({placeholders}) OR c.candidate_field_id IN ({placeholders}))
            ORDER BY c.id
            """,
            [*field_ids, *field_ids],
        ).fetchall()
        return [dict(row) for row in rows]

    def _basis_payload(
        self,
        conn,
        fields: list[dict[str, Any]],
        pair_scores: dict[tuple[str, str], dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        ids = sorted(field["id"] for field in fields)
        pairs = []
        for pair in sorted(pair_scores):
            result = pair_scores[pair]
            pairs.append(
                {
                    "left_field_id": pair[0],
                    "right_field_id": pair[1],
                    "score": result["score"],
                    "signals": result["signals"],
                }
            )
        return {
            "policy_version": POLICY_VERSION,
            "parameters": parameters,
            "fields": self._field_basis_rows(conn, ids),
            "semantic_evidence": self._semantic_basis_rows(conn, ids),
            "pair_scores": pairs,
        }

    def _pair_score(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        cache: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        pair = tuple(sorted((left["id"], right["id"])))
        if pair not in cache:
            cache[pair] = score_field_pair(left, right)
        return cache[pair]

    def _decode_proposal(self, row: Any, conn) -> dict[str, Any]:
        item = dict(row)
        _decode_json_column(item, "parameters_json", "parameters")
        _decode_json_column(item, "evidence_json", "evidence")
        member_rows = conn.execute(
            """
            SELECT m.*,f.key,f.label,f.value_type,f.namespace,f.status
            FROM field_family_proposal_members m
            JOIN fields f ON f.id=m.field_id
            WHERE m.proposal_id=?
            ORDER BY m.ordinal
            """,
            (item["id"],),
        ).fetchall()
        members = []
        for member_row in member_rows:
            member = dict(member_row)
            _decode_json_column(member, "evidence_json", "evidence")
            members.append(member)
        item["members"] = members
        review = conn.execute(
            "SELECT * FROM field_family_reviews WHERE proposal_id=?", (item["id"],)
        ).fetchone()
        if review is not None:
            review_item = dict(review)
            _decode_json_column(review_item, "decision_json", "decision_data")
            _decode_json_column(review_item, "evidence_json", "evidence")
            item["review"] = review_item
        else:
            item["review"] = None
        return item

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_family_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"field family proposal not found: {proposal_id}")
            return self._decode_proposal(row, conn)

    def list_proposals(
        self,
        *,
        namespace: str | None = None,
        reviewed: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if namespace is not None:
            where.append("p.namespace=?")
            params.append(str(namespace).strip() or "global")
        if reviewed is True:
            where.append("r.id IS NOT NULL")
        elif reviewed is False:
            where.append("r.id IS NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(int(limit), 1000)))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT p.* FROM field_family_proposals p
                LEFT JOIN field_family_reviews r ON r.proposal_id=p.id
                {clause}
                ORDER BY p.created_at DESC,p.id
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [self._decode_proposal(row, conn) for row in rows]

    # ------------------------------------------------------------------
    # Proposal persistence
    # ------------------------------------------------------------------
    def _persist_group_proposal(
        self,
        *,
        seed: dict[str, Any],
        group: list[dict[str, Any]],
        cache: dict[tuple[str, str], dict[str, Any]],
        parameters: dict[str, Any],
        evaluator: str,
    ) -> dict[str, Any]:
        pair_values: list[float] = []
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                pair_values.append(float(self._pair_score(left, right, cache)["score"]))
        if not pair_values:
            raise ValueError("field family proposal requires at least two members")
        min_pair_score = min(pair_values)
        avg_pair_score = sum(pair_values) / len(pair_values)
        group_ids = {field["id"] for field in group}
        group_pair_scores = {
            pair: result
            for pair, result in cache.items()
            if pair[0] in group_ids and pair[1] in group_ids
        }
        with self.db.connect() as conn:
            basis_payload = self._basis_payload(conn, group, group_pair_scores, parameters)
            basis_sha256 = _json_hash(basis_payload)
            proposal_id = uuid4().hex
            now = _now()
            conn.execute(
                """
                INSERT INTO field_family_proposals(
                    id,namespace,policy_version,seed_field_id,member_count,min_pair_score,
                    avg_pair_score,basis_sha256,parameters_json,evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    proposal_id,
                    seed["namespace"],
                    POLICY_VERSION,
                    seed["id"],
                    len(group),
                    round(min_pair_score, 6),
                    round(avg_pair_score, 6),
                    basis_sha256,
                    json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        {"basis": basis_payload, "evaluator": str(evaluator)},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            for ordinal, member in enumerate(group):
                peer_scores = [
                    float(self._pair_score(member, other, cache)["score"])
                    for other in group
                    if other["id"] != member["id"]
                ]
                seed_score = (
                    1.0
                    if member["id"] == seed["id"]
                    else float(self._pair_score(seed, member, cache)["score"])
                )
                conn.execute(
                    """
                    INSERT INTO field_family_proposal_members(
                        proposal_id,field_id,ordinal,seed_score,min_peer_score,
                        avg_peer_score,evidence_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        proposal_id,
                        member["id"],
                        ordinal,
                        round(seed_score, 6),
                        round(min(peer_scores), 6),
                        round(sum(peer_scores) / len(peer_scores), 6),
                        json.dumps(
                            {
                                "peer_count": len(peer_scores),
                                "value_type": member["value_type"],
                                "namespace": member["namespace"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
        return self.get_proposal(proposal_id)

    # ------------------------------------------------------------------
    # Seed proposal
    # ------------------------------------------------------------------
    def propose_from_seed(
        self,
        seed_ref: str,
        *,
        seed_threshold: float = 0.78,
        min_coherence: float = 0.72,
        max_neighbors: int = 24,
        max_members: int = 8,
        namespace: str = "global",
        evaluator: str = "system:family",
    ) -> dict[str, Any] | None:
        namespace = str(namespace).strip() or "global"
        seed_threshold = max(0.0, min(float(seed_threshold), 1.0))
        min_coherence = max(0.0, min(float(min_coherence), 1.0))
        max_neighbors = max(1, min(int(max_neighbors), 100))
        max_members = max(2, min(int(max_members), 32))

        with self.db.connect() as conn:
            seed = dict(resolve_field_row(conn, seed_ref, namespace))
            if seed["namespace"] != namespace:
                raise ValueError("seed field namespace does not match requested namespace")
            if seed["status"] not in _ACTIVE_SOURCE_STATUSES:
                raise ValueError(f"seed field status is not family-proposable: {seed['status']}")
            rows = conn.execute(
                """
                SELECT * FROM fields
                WHERE namespace=? AND id<>?
                  AND status IN ('proposed','active','converged')
                  AND value_type=?
                ORDER BY normalized_key,key,id
                """,
                (namespace, seed["id"], seed["value_type"]),
            ).fetchall()
        candidates = [dict(row) for row in rows]
        if not candidates:
            return None
        blocked = sorted(
            candidates, key=lambda item: _blocking_rank(seed, item), reverse=True
        )[:max_neighbors]

        cache: dict[tuple[str, str], dict[str, Any]] = {}
        eligible: list[tuple[dict[str, Any], float]] = []
        for candidate in blocked:
            result = self._pair_score(seed, candidate, cache)
            if result["score"] >= seed_threshold:
                eligible.append((candidate, float(result["score"])))
        eligible.sort(key=lambda pair: (pair[1], pair[0]["id"]), reverse=True)

        group: list[dict[str, Any]] = [seed]
        for candidate, _ in eligible:
            if len(group) >= max_members:
                break
            if all(
                self._pair_score(candidate, existing, cache)["score"] >= min_coherence
                for existing in group
            ):
                group.append(candidate)
        if len(group) < 2:
            return None

        parameters = {
            "mode": "seed",
            "seed_threshold": round(seed_threshold, 6),
            "min_coherence": round(min_coherence, 6),
            "max_neighbors": max_neighbors,
            "max_members": max_members,
            "namespace": namespace,
        }
        return self._persist_group_proposal(
            seed=seed, group=group, cache=cache, parameters=parameters, evaluator=evaluator
        )

    # ------------------------------------------------------------------
    # Review and formal families
    # ------------------------------------------------------------------
    def _current_proposal_basis(self, conn, proposal: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        member_rows = conn.execute(
            """
            SELECT f.*
            FROM field_family_proposal_members m
            JOIN fields f ON f.id=m.field_id
            WHERE m.proposal_id=?
            ORDER BY m.ordinal
            """,
            (proposal["id"],),
        ).fetchall()
        fields = [dict(row) for row in member_rows]
        cache: dict[tuple[str, str], dict[str, Any]] = {}
        for i, left in enumerate(fields):
            for right in fields[i + 1 :]:
                self._pair_score(left, right, cache)
        parameters = json.loads(proposal["parameters_json"])
        payload = self._basis_payload(conn, fields, cache, parameters)
        return _json_hash(payload), payload

    def _decode_review(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        _decode_json_column(item, "decision_json", "decision_data")
        _decode_json_column(item, "evidence_json", "evidence")
        return item

    def get_family(self, family_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM field_families WHERE id=?", (family_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"field family not found: {family_id}")
            item = dict(row)
            member_rows = conn.execute(
                """
                SELECT m.*,f.key,f.label,f.value_type,f.namespace,f.status
                FROM field_family_members m
                JOIN fields f ON f.id=m.field_id
                WHERE m.family_id=?
                ORDER BY m.ordinal
                """,
                (family_id,),
            ).fetchall()
            item["members"] = [dict(member) for member in member_rows]
            event_rows = conn.execute(
                "SELECT * FROM field_family_events WHERE family_id=? ORDER BY id",
                (family_id,),
            ).fetchall()
            events = []
            for event_row in event_rows:
                event = dict(event_row)
                _decode_json_column(event, "evidence_json", "evidence")
                events.append(event)
            item["events"] = events
            return item

    def list_families(
        self,
        *,
        namespace: str | None = None,
        family_type: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if namespace is not None:
            where.append("namespace=?")
            params.append(str(namespace).strip() or "global")
        if family_type is not None:
            token = str(family_type).strip().lower()
            if token not in {"duplicate", "related"}:
                raise ValueError("family_type must be duplicate or related")
            where.append("family_type=?")
            params.append(token)
        if status:
            where.append("status=?")
            params.append(str(status))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(int(limit), 1000)))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM field_families {clause} ORDER BY created_at DESC,id LIMIT ?",
                params,
            ).fetchall()
        return [self.get_family(row["id"]) for row in rows]

    def review_proposal(
        self,
        proposal_id: str,
        decision: str,
        *,
        reason: str,
        evaluator: str = "",
        evidence: dict[str, Any] | None = None,
        label: str = "",
        partitions: list[list[str]] | None = None,
    ) -> dict[str, Any]:
        token = str(decision).strip().lower()
        if token not in {"duplicate_family", "related_family", "split", "reject"}:
            raise ValueError(
                "family review decision must be duplicate_family, related_family, split, or reject"
            )
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for field family review")
        evidence = evidence or {}
        now = _now()
        created_family_id: str | None = None

        with self.db.connect() as conn:
            proposal_row = conn.execute(
                "SELECT * FROM field_family_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            if proposal_row is None:
                raise KeyError(f"field family proposal not found: {proposal_id}")
            proposal = dict(proposal_row)
            if conn.execute(
                "SELECT 1 FROM field_family_reviews WHERE proposal_id=?", (proposal_id,)
            ).fetchone():
                raise ValueError(f"field family proposal already reviewed: {proposal_id}")

            current_basis_sha256, current_basis = self._current_proposal_basis(conn, proposal)
            if current_basis_sha256 != proposal["basis_sha256"]:
                raise ValueError("field family proposal is stale; regenerate before review")

            member_rows = conn.execute(
                """
                SELECT m.field_id,m.ordinal,f.label
                FROM field_family_proposal_members m
                JOIN fields f ON f.id=m.field_id
                WHERE m.proposal_id=?
                ORDER BY m.ordinal
                """,
                (proposal_id,),
            ).fetchall()
            member_ids = [row["field_id"] for row in member_rows]
            decision_data: dict[str, Any] = {}

            if token == "split":
                if not isinstance(partitions, list) or len(partitions) < 2:
                    raise ValueError("split review requires a partition with at least two groups")
                normalized_partitions: list[list[str]] = []
                flattened: list[str] = []
                for group in partitions:
                    if not isinstance(group, list) or not group:
                        raise ValueError("split partition groups must be non-empty lists")
                    normalized = [str(field_id) for field_id in group]
                    normalized_partitions.append(normalized)
                    flattened.extend(normalized)
                if len(flattened) != len(set(flattened)) or set(flattened) != set(member_ids):
                    raise ValueError("split partition must cover each proposal member exactly once")
                decision_data["partitions"] = normalized_partitions

            if token == "duplicate_family":
                placeholders = ",".join("?" for _ in member_ids)
                overlap = conn.execute(
                    f"""
                    SELECT fm.field_id,ff.id AS family_id
                    FROM field_family_members fm
                    JOIN field_families ff ON ff.id=fm.family_id
                    WHERE ff.family_type='duplicate' AND ff.status='active'
                      AND fm.field_id IN ({placeholders})
                    LIMIT 1
                    """,
                    member_ids,
                ).fetchone()
                if overlap is not None:
                    raise ValueError(
                        f"field already belongs to an active duplicate family: {overlap['field_id']}"
                    )

            cur = conn.execute(
                """
                INSERT INTO field_family_reviews(
                    proposal_id,decision,reason,decision_json,evidence_json,evaluator,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    proposal_id,
                    token,
                    reason,
                    json.dumps(decision_data, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        {**evidence, "review_basis_sha256": current_basis_sha256},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    str(evaluator),
                    now,
                ),
            )
            review_id = int(cur.lastrowid)

            if token in {"duplicate_family", "related_family"}:
                family_type = "duplicate" if token == "duplicate_family" else "related"
                created_family_id = uuid4().hex
                default_label = f"{member_rows[0]['label']} family"
                family_label = str(label).strip() or default_label
                conn.execute(
                    """
                    INSERT INTO field_families(
                        id,namespace,family_type,label,source_proposal_id,status,created_at
                    ) VALUES(?,?,?,?,?,'active',?)
                    """,
                    (
                        created_family_id,
                        proposal["namespace"],
                        family_type,
                        family_label,
                        proposal_id,
                        now,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO field_family_members(family_id,field_id,ordinal,created_at)
                    VALUES(?,?,?,?)
                    """,
                    [
                        (created_family_id, row["field_id"], int(row["ordinal"]), now)
                        for row in member_rows
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO field_family_events(
                        family_id,event_type,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,'created',?,?,?,?)
                    """,
                    (
                        created_family_id,
                        reason,
                        json.dumps(
                            {
                                **evidence,
                                "proposal_id": proposal_id,
                                "review_id": review_id,
                                "basis_sha256": current_basis_sha256,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        str(evaluator),
                        now,
                    ),
                )

            review_row = conn.execute(
                "SELECT * FROM field_family_reviews WHERE id=?", (review_id,)
            ).fetchone()
            review = self._decode_review(review_row)

        return {
            "proposal": self.get_proposal(proposal_id),
            "review": review,
            "family": None if created_family_id is None else self.get_family(created_family_id),
        }

    # ------------------------------------------------------------------
    # Bounded registry scan
    # ------------------------------------------------------------------
    def scan_registry(
        self,
        *,
        namespace: str = "global",
        seed_threshold: float = 0.78,
        min_coherence: float = 0.72,
        max_neighbors: int = 12,
        max_members: int = 8,
        limit_fields: int = 10000,
        max_proposals: int = 100,
        evaluator: str = "system:family-scan",
    ) -> list[dict[str, Any]]:
        namespace = str(namespace).strip() or "global"
        seed_threshold = max(0.0, min(float(seed_threshold), 1.0))
        min_coherence = max(0.0, min(float(min_coherence), 1.0))
        max_neighbors = max(1, min(int(max_neighbors), 100))
        max_members = max(2, min(int(max_members), 32))
        limit_fields = max(1, min(int(limit_fields), 10000))
        max_proposals = max(1, min(int(max_proposals), 1000))

        pair_candidates = SemanticDedupService(self.db).scan_field_similarity(
            namespace=namespace,
            threshold=min(seed_threshold, min_coherence),
            max_neighbors=max_neighbors,
            limit_fields=limit_fields,
        )
        if not pair_candidates:
            return []

        with self.db.connect() as conn:
            field_rows = conn.execute(
                """
                SELECT * FROM fields
                WHERE namespace=? AND status IN ('proposed','active','converged')
                ORDER BY normalized_key,key,id
                """,
                (namespace,),
            ).fetchall()
        fields = [dict(row) for row in field_rows]
        field_map = {field["id"]: field for field in fields}
        seed_ids = [field["id"] for field in fields[:limit_fields]]

        adjacency: dict[str, list[tuple[str, float]]] = {}
        for candidate in pair_candidates:
            left_id = str(candidate["source_ref"])
            right_id = str(candidate["candidate_field_id"])
            score = float(candidate["score"])
            if left_id not in field_map or right_id not in field_map:
                continue
            adjacency.setdefault(left_id, []).append((right_id, score))
            adjacency.setdefault(right_id, []).append((left_id, score))

        proposals: list[dict[str, Any]] = []
        seen_signatures: set[tuple[str, ...]] = set()
        for seed_id in seed_ids:
            if len(proposals) >= max_proposals:
                break
            seed = field_map[seed_id]
            neighbors = [
                (field_map[other_id], score)
                for other_id, score in adjacency.get(seed_id, [])
                if score >= seed_threshold
                and field_map[other_id]["value_type"] == seed["value_type"]
            ]
            neighbors.sort(key=lambda pair: (pair[1], pair[0]["id"]), reverse=True)
            if not neighbors:
                continue

            cache: dict[tuple[str, str], dict[str, Any]] = {}
            group: list[dict[str, Any]] = [seed]
            for candidate, pair_score in neighbors:
                if len(group) >= max_members:
                    break
                pair = tuple(sorted((seed["id"], candidate["id"])))
                cache[pair] = score_field_pair(seed, candidate)
                if all(
                    self._pair_score(candidate, existing, cache)["score"] >= min_coherence
                    for existing in group
                ):
                    group.append(candidate)
            if len(group) < 2:
                continue

            signature = tuple(sorted(field["id"] for field in group))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            parameters = {
                "mode": "registry_scan",
                "seed_threshold": round(seed_threshold, 6),
                "min_coherence": round(min_coherence, 6),
                "max_neighbors": max_neighbors,
                "max_members": max_members,
                "limit_fields": limit_fields,
                "max_proposals": max_proposals,
                "namespace": namespace,
            }
            proposals.append(
                self._persist_group_proposal(
                    seed=seed,
                    group=group,
                    cache=cache,
                    parameters=parameters,
                    evaluator=evaluator,
                )
            )
        return proposals


from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower()


def _tokens(value: Any) -> set[str]:
    text = _text(value).replace("_", " ").replace("-", " ").replace("/", " ").replace(".", " ")
    return {token for token in _TOKEN_RE.findall(text) if token and token not in _STOPWORDS}


def _compact(value: Any) -> str:
    return "".join(_TOKEN_RE.findall(_text(value)))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _char_similarity(left: Any, right: Any) -> float:
    a, b = _compact(left), _compact(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _field_text_score(left: Any, right: Any) -> float:
    token_score = _jaccard(_tokens(left), _tokens(right))
    char_score = _char_similarity(left, right)
    return max(token_score, char_score * 0.85)


def score_field_pair(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Return an explainable deterministic similarity score in [0, 1]."""
    key_score = _field_text_score(left.get("key", ""), right.get("key", ""))
    label_score = _field_text_score(left.get("label", ""), right.get("label", ""))
    description_score = _field_text_score(
        left.get("description", ""), right.get("description", "")
    )
    same_type = _text(left.get("value_type", "text")) == _text(right.get("value_type", "text"))
    type_score = 1.0 if same_type else 0.0
    namespace_score = (
        1.0
        if _text(left.get("namespace", "global")) == _text(right.get("namespace", "global"))
        else 0.0
    )
    base = (
        0.45 * key_score
        + 0.30 * label_score
        + 0.10 * description_score
        + 0.10 * type_score
        + 0.05 * namespace_score
    )
    type_penalty = 1.0 if same_type else 0.60
    score = max(0.0, min(1.0, base * type_penalty))
    signals = {
        "key": round(key_score, 6),
        "label": round(label_score, 6),
        "description": round(description_score, 6),
        "type": round(type_score, 6),
        "namespace": round(namespace_score, 6),
        "type_penalty": round(type_penalty, 6),
        "base_score": round(base, 6),
        "final_score": round(score, 6),
    }
    return {"score": signals["final_score"], "signals": signals}

import json
from datetime import datetime, timezone

from .db import Database
from .naming import normalize_field_key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_candidate(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["signals"] = json.loads(item.pop("signals_json"))
    return item


def _blocking_rank(source: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, float, float, str]:
    source_tokens = _tokens(f"{source.get('key', '')} {source.get('label', '')}")
    candidate_tokens = _tokens(f"{candidate.get('key', '')} {candidate.get('label', '')}")
    shared = len(source_tokens & candidate_tokens)
    source_key = _compact(source.get("key", ""))
    candidate_key = _compact(candidate.get("key", ""))
    prefix = 1.0 if source_key[:4] and source_key[:4] == candidate_key[:4] else 0.0
    same_type = 1.0 if _text(source.get("value_type")) == _text(candidate.get("value_type")) else 0.0
    cheap_char = _char_similarity(source.get("key", ""), candidate.get("key", ""))
    # Sort descending for evidence dimensions, then stable by canonical id/key.
    return (float(shared) + prefix, same_type, cheap_char, str(candidate.get("id", candidate.get("key", ""))))


class SemanticDedupService:
    def __init__(self, db: Database):
        self.db = db

    def list_candidates(
        self,
        *,
        source_kind: str | None = None,
        source_ref: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if source_kind:
            where.append("source_kind=?")
            params.append(source_kind)
        if source_ref:
            where.append("source_ref=?")
            params.append(source_ref)
        if status:
            where.append("status=?")
            params.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(int(limit), 10000)))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM semantic_candidates {clause} ORDER BY score DESC,id LIMIT ?",
                params,
            ).fetchall()
        return [_decode_candidate(row) for row in rows]

    def score_proposal(
        self,
        proposal_id: str,
        *,
        top_k: int = 10,
        max_candidates: int = 500,
        cross_namespace: bool = False,
    ) -> list[dict[str, Any]]:
        top_k = max(1, min(int(top_k), 1000))
        max_candidates = max(top_k, min(int(max_candidates), 10000))
        with self.db.connect() as conn:
            proposal_row = conn.execute(
                "SELECT * FROM field_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            if proposal_row is None:
                raise KeyError(f"proposal not found: {proposal_id}")
            proposal = dict(proposal_row)
            if cross_namespace:
                field_rows = conn.execute(
                    "SELECT * FROM fields WHERE status NOT IN ('merged','split','deprecated') ORDER BY id"
                ).fetchall()
            else:
                field_rows = conn.execute(
                    """
                    SELECT * FROM fields
                    WHERE namespace=? AND status NOT IN ('merged','split','deprecated')
                    ORDER BY id
                    """,
                    (proposal["namespace"] or "global",),
                ).fetchall()

        if not field_rows:
            return []
        fields = [dict(row) for row in field_rows]
        blocked = sorted(
            fields,
            key=lambda item: _blocking_rank(proposal, item),
            reverse=True,
        )[:max_candidates]
        scored: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for candidate in blocked:
            scored.append((candidate, score_field_pair(proposal, candidate)))
        scored.sort(key=lambda pair: (pair[1]["score"], pair[0]["id"]), reverse=True)
        selected = scored[:top_k]

        now = _now()
        with self.db.connect() as conn:
            # Stale unreviewed proposal candidates are advisory and may be replaced by a fresh ranking.
            conn.execute(
                "DELETE FROM semantic_candidates WHERE source_kind='proposal' AND source_ref=? AND status='pending'",
                (proposal_id,),
            )
            for candidate, result in selected:
                conn.execute(
                    """
                    INSERT INTO semantic_candidates(
                        namespace,source_kind,source_ref,candidate_field_id,score,signals_json,status,created_at
                    ) VALUES(?,?,?,?,?,?,'pending',?)
                    ON CONFLICT(source_kind,source_ref,candidate_field_id) DO UPDATE SET
                        score=excluded.score,
                        signals_json=excluded.signals_json
                    """,
                    (
                        proposal["namespace"] or "global",
                        "proposal",
                        proposal_id,
                        candidate["id"],
                        result["score"],
                        json.dumps(result["signals"], ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
        return self.list_candidates(
            source_kind="proposal", source_ref=proposal_id, limit=top_k
        )

    def get_review(self, candidate_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_candidate_reviews WHERE candidate_id=?",
                (int(candidate_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"semantic candidate review not found: {candidate_id}")
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def review_candidate(
        self,
        candidate_id: int,
        decision: str,
        *,
        reason: str,
        evidence: dict[str, Any] | None = None,
        evaluator: str = "",
    ) -> dict[str, Any]:
        token = str(decision).strip().lower()
        if token not in {"alias", "related", "distinct", "ignore"}:
            raise ValueError("candidate decision must be alias, related, distinct, or ignore")
        reason = str(reason).strip()
        if not reason:
            raise ValueError("reason is required for semantic candidate review")
        evidence = evidence or {}
        now = _now()

        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM semantic_candidates WHERE id=?", (int(candidate_id),)
            ).fetchone()
            if candidate is None:
                raise KeyError(f"semantic candidate not found: {candidate_id}")
            if candidate["status"] == "reviewed" or conn.execute(
                "SELECT 1 FROM semantic_candidate_reviews WHERE candidate_id=?",
                (int(candidate_id),),
            ).fetchone():
                raise ValueError(f"semantic candidate already reviewed: {candidate_id}")

            target = conn.execute(
                "SELECT * FROM fields WHERE id=?", (candidate["candidate_field_id"],)
            ).fetchone()
            if target is None:
                raise KeyError(f"candidate target field not found: {candidate['candidate_field_id']}")

            if token == "alias":
                if candidate["source_kind"] != "proposal":
                    raise ValueError(
                        "canonical field candidates cannot become aliases; use explicit merge governance"
                    )
                proposal = conn.execute(
                    "SELECT * FROM field_proposals WHERE id=?", (candidate["source_ref"],)
                ).fetchone()
                if proposal is None:
                    raise KeyError(f"proposal not found: {candidate['source_ref']}")
                if proposal["status"] != "pending":
                    raise ValueError(f"proposal already decided: {proposal['status']}")
                namespace = proposal["namespace"] or "global"
                normalized_alias = normalize_field_key(proposal["key"])
                canonical_conflict = conn.execute(
                    "SELECT id,key FROM fields WHERE namespace=? AND normalized_key=? ORDER BY id LIMIT 2",
                    (namespace, normalized_alias),
                ).fetchall()
                for conflict in canonical_conflict:
                    if conflict["id"] != target["id"]:
                        raise ValueError(
                            f"semantic alias conflicts with canonical field: {conflict['key']}"
                        )
                existing_alias = conn.execute(
                    "SELECT * FROM field_aliases WHERE namespace=? AND normalized_alias=?",
                    (namespace, normalized_alias),
                ).fetchone()
                if existing_alias is not None and existing_alias["field_id"] != target["id"]:
                    raise ValueError("semantic alias already points to another canonical field")
                if existing_alias is None:
                    conn.execute(
                        """
                        INSERT INTO field_aliases(
                            namespace,alias,normalized_alias,field_id,reason,created_at
                        ) VALUES(?,?,?,?,?,?)
                        """,
                        (
                            namespace,
                            proposal["key"],
                            normalized_alias,
                            target["id"],
                            reason,
                            now,
                        ),
                    )
                conn.execute(
                    "UPDATE field_proposals SET status='accepted' WHERE id=?",
                    (proposal["id"],),
                )
                conn.execute(
                    """
                    INSERT INTO proposal_decisions(
                        proposal_id,decision,outcome,target_field_id,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,'accepted','semantic_alias_existing',?,?,?,?,?)
                    """,
                    (
                        proposal["id"],
                        target["id"],
                        reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        evaluator,
                        now,
                    ),
                )

            elif token == "related" and candidate["source_kind"] == "field":
                source = conn.execute(
                    "SELECT * FROM fields WHERE id=?", (candidate["source_ref"],)
                ).fetchone()
                if source is None:
                    raise KeyError(f"source field not found: {candidate['source_ref']}")
                if source["id"] == target["id"]:
                    raise ValueError("a field cannot be related_to itself")
                left_id, right_id = sorted((source["id"], target["id"]))
                relation_namespace = source["namespace"] or candidate["namespace"] or "global"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO field_relations(
                        namespace,left_field_id,right_field_id,relation,reason,evidence_json,evaluator,created_at
                    ) VALUES(?,?,?,'related_to',?,?,?,?)
                    """,
                    (
                        relation_namespace,
                        left_id,
                        right_id,
                        reason,
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        evaluator,
                        now,
                    ),
                )

            conn.execute(
                """
                INSERT INTO semantic_candidate_reviews(
                    candidate_id,decision,reason,evidence_json,evaluator,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    int(candidate_id),
                    token,
                    reason,
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    evaluator,
                    now,
                ),
            )
            conn.execute(
                "UPDATE semantic_candidates SET status='reviewed' WHERE id=?",
                (int(candidate_id),),
            )
        return self.get_review(int(candidate_id))

    def list_relations(
        self,
        field_ref: str,
        *,
        namespace: str = "global",
    ) -> list[dict[str, Any]]:
        from .governance import resolve_field_row

        with self.db.connect() as conn:
            field = resolve_field_row(conn, field_ref, namespace)
            rows = conn.execute(
                """
                SELECT * FROM field_relations
                WHERE left_field_id=? OR right_field_id=?
                ORDER BY id
                """,
                (field["id"], field["id"]),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result

    def scan_field_similarity(
        self,
        *,
        namespace: str = "global",
        threshold: float = 0.72,
        max_neighbors: int = 12,
        limit_fields: int | None = None,
    ) -> list[dict[str, Any]]:
        namespace = str(namespace).strip() or "global"
        threshold = max(0.0, min(float(threshold), 1.0))
        max_neighbors = max(1, min(int(max_neighbors), 100))
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM fields
                WHERE namespace=? AND status NOT IN ('merged','split','deprecated')
                ORDER BY normalized_key,key,id
                """,
                (namespace,),
            ).fetchall()
        fields = [dict(row) for row in rows]
        if len(fields) < 2:
            return []

        token_to_indices: dict[str, list[int]] = {}
        frequencies: dict[str, int] = {}
        field_tokens: list[set[str]] = []
        for index, field in enumerate(fields):
            tokens = _tokens(f"{field.get('key', '')} {field.get('label', '')}")
            field_tokens.append(tokens)
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
                token_to_indices.setdefault(token, []).append(index)

        rare_cap = max(4, min(64, max(1, int(len(fields) * 0.05))))
        source_count = len(fields) if limit_fields is None else max(0, min(int(limit_fields), len(fields)))
        seen_pairs: set[tuple[str, str]] = set()
        selected: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []

        for index in range(source_count):
            source = fields[index]
            neighbor_indices: set[int] = set()

            # Sorted-neighborhood block. The window is bounded independently of registry size.
            radius = max_neighbors
            start = max(0, index - radius)
            stop = min(len(fields), index + radius + 1)
            neighbor_indices.update(i for i in range(start, stop) if i != index)

            # Rare-token block recovers reordered terms that may be distant in lexical sort.
            for token in field_tokens[index]:
                if frequencies.get(token, 0) <= rare_cap:
                    neighbor_indices.update(i for i in token_to_indices.get(token, []) if i != index)

            ranked_neighbors = sorted(
                (fields[i] for i in neighbor_indices),
                key=lambda item: _blocking_rank(source, item),
                reverse=True,
            )[:max_neighbors]

            for candidate in ranked_neighbors:
                left_id, right_id = sorted((source["id"], candidate["id"]))
                pair = (left_id, right_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                left = source if source["id"] == left_id else candidate
                right = candidate if candidate["id"] == right_id else source
                result = score_field_pair(left, right)
                if result["score"] < threshold:
                    continue
                selected.append((left, right, result))

        now = _now()
        ids: list[int] = []
        with self.db.connect() as conn:
            for left, right, result in selected:
                conn.execute(
                    """
                    INSERT INTO semantic_candidates(
                        namespace,source_kind,source_ref,candidate_field_id,score,signals_json,status,created_at
                    ) VALUES(?,'field',?,?,?,?, 'pending',?)
                    ON CONFLICT(source_kind,source_ref,candidate_field_id) DO UPDATE SET
                        score=excluded.score,
                        signals_json=excluded.signals_json
                    """,
                    (
                        namespace,
                        left["id"],
                        right["id"],
                        result["score"],
                        json.dumps(result["signals"], ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT id FROM semantic_candidates
                    WHERE source_kind='field' AND source_ref=? AND candidate_field_id=?
                    """,
                    (left["id"], right["id"]),
                ).fetchone()
                ids.append(int(row["id"]))
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            result_rows = conn.execute(
                f"SELECT * FROM semantic_candidates WHERE id IN ({placeholders}) ORDER BY score DESC,id",
                ids,
            ).fetchall()
        return [_decode_candidate(row) for row in result_rows]

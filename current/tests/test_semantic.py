from sedb.db import Database
from sedb.fields import FieldService


def test_score_field_pair_ranks_reordered_equivalent_wording_high():
    from sedb.semantic import score_field_pair

    left = {
        "key": "author_country",
        "label": "Author country",
        "description": "Country associated with the author",
        "value_type": "text",
        "namespace": "global",
    }
    right = {
        "key": "country_of_author",
        "label": "Country of author",
        "description": "Author country classification",
        "value_type": "text",
        "namespace": "global",
    }
    result = score_field_pair(left, right)
    assert result["score"] >= 0.80
    assert result["signals"]["key"] >= 0.80
    assert result["signals"]["type_penalty"] == 1.0


def test_score_field_pair_unrelated_wording_is_low():
    from sedb.semantic import score_field_pair

    left = {
        "key": "author_country",
        "label": "Author country",
        "description": "Country associated with the author",
        "value_type": "text",
        "namespace": "global",
    }
    right = {
        "key": "publication_year",
        "label": "Publication year",
        "description": "Year the paper was published",
        "value_type": "integer",
        "namespace": "global",
    }
    result = score_field_pair(left, right)
    assert result["score"] < 0.45


def test_score_field_pair_type_conflict_reduces_score_materially():
    from sedb.semantic import score_field_pair

    base = {
        "key": "citation_count",
        "label": "Citation count",
        "description": "Number of citations",
        "namespace": "global",
    }
    same = score_field_pair({**base, "value_type": "integer"}, {**base, "value_type": "integer"})
    conflict = score_field_pair({**base, "value_type": "integer"}, {**base, "value_type": "text"})
    assert same["score"] > conflict["score"]
    assert conflict["signals"]["type_penalty"] == 0.60
    assert conflict["score"] <= same["score"] * 0.65


def test_score_proposal_ranks_reordered_equivalent_field_first_and_persists_signals(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "score.sqlite")
    fields = FieldService(db)
    target = fields.create_field(key="author_country", label="Author country", value_type="text")
    fields.create_field(key="publication_year", label="Publication year", value_type="integer")
    proposal = fields.create_proposal(
        key="country_of_author",
        label="Country of author",
        value_type="text",
        reason="Imported vocabulary",
    )

    semantic = SemanticDedupService(db)
    ranked = semantic.score_proposal(proposal["id"], top_k=2, max_candidates=10)
    stored = semantic.list_candidates(source_kind="proposal", source_ref=proposal["id"])

    assert ranked[0]["candidate_field_id"] == target["id"]
    assert ranked[0]["score"] >= ranked[1]["score"]
    assert ranked[0]["signals"]["key"] >= 0.80
    assert stored[0]["signals"]["final_score"] == stored[0]["score"]


def test_score_proposal_default_namespace_isolation(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "namespace.sqlite")
    fields = FieldService(db)
    fields.create_field(
        key="author_country", label="Author country", namespace="research"
    )
    proposal = fields.create_proposal(
        key="country_of_author",
        label="Country of author",
        reason="Imported vocabulary",
        namespace="global",
    )

    ranked = SemanticDedupService(db).score_proposal(proposal["id"])
    assert ranked == []


def test_score_proposal_respects_max_candidates_and_top_k(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "bounded.sqlite")
    fields = FieldService(db)
    fields.bulk_create_fields(
        [
            {"key": f"author_metric_{i:03d}", "label": f"Author metric {i:03d}", "value_type": "text"}
            for i in range(40)
        ]
    )
    proposal = fields.create_proposal(
        key="author_metric_candidate",
        label="Author metric candidate",
        reason="Candidate",
    )

    ranked = SemanticDedupService(db).score_proposal(
        proposal["id"], top_k=3, max_candidates=7
    )
    assert len(ranked) == 3
    assert db.scalar(
        "SELECT COUNT(*) FROM semantic_candidates WHERE source_kind='proposal' AND source_ref=?",
        (proposal["id"],),
    ) == 3


def _insert_field_candidate(db, source_id, target_id, score=0.9):
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO semantic_candidates(
                namespace,source_kind,source_ref,candidate_field_id,score,signals_json,status,created_at
            ) VALUES('global','field',?,?,?,?, 'pending','2026-08-20T00:00:00Z')
            """,
            (source_id, target_id, score, '{"final_score": 0.9}'),
        )
        return cur.lastrowid


def test_review_proposal_candidate_as_alias_targets_canonical_without_new_field(tmp_path):
    from sedb.semantic import SemanticDedupService
    from sedb.governance import FieldGovernanceService

    db = Database(tmp_path / "review-alias.sqlite")
    fields = FieldService(db)
    target = fields.create_field(key="author_country", label="Author country")
    proposal = fields.create_proposal(
        key="country_of_author",
        label="Country of author",
        reason="Imported vocabulary",
    )
    semantic = SemanticDedupService(db)
    candidate = semantic.score_proposal(proposal["id"], top_k=1)[0]

    review = semantic.review_candidate(
        candidate["id"],
        "alias",
        reason="Same semantic dimension after review",
        evaluator="test:reviewer",
        evidence={"basis": "manual"},
    )
    resolved = FieldGovernanceService(db).resolve_field("country_of_author")

    assert review["decision"] == "alias"
    assert resolved["id"] == target["id"]
    assert db.scalar("SELECT COUNT(*) FROM fields") == 1
    assert db.scalar("SELECT status FROM field_proposals WHERE id=?", (proposal["id"],)) == "accepted"
    assert db.scalar(
        "SELECT outcome FROM proposal_decisions WHERE proposal_id=?", (proposal["id"],)
    ) == "semantic_alias_existing"


def test_review_canonical_field_candidate_cannot_be_alias(tmp_path):
    import pytest
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "canonical-alias.sqlite")
    fields = FieldService(db)
    left = fields.create_field(key="nation", label="Nation")
    right = fields.create_field(key="country", label="Country")
    candidate_id = _insert_field_candidate(db, left["id"], right["id"])

    with pytest.raises(ValueError, match="canonical.*alias|merge"):
        SemanticDedupService(db).review_candidate(
            candidate_id, "alias", reason="Not permitted"
        )


def test_review_field_candidate_as_related_creates_auditable_relation(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "related.sqlite")
    fields = FieldService(db)
    left = fields.create_field(key="source_quality", label="Source quality")
    right = fields.create_field(key="source_reliability", label="Source reliability")
    candidate_id = _insert_field_candidate(db, left["id"], right["id"])
    semantic = SemanticDedupService(db)

    review = semantic.review_candidate(
        candidate_id,
        "related",
        reason="Related but not identical",
        evaluator="test:reviewer",
    )
    relations = semantic.list_relations(left["id"])

    assert review["decision"] == "related"
    assert len(relations) == 1
    assert relations[0]["relation"] == "related_to"
    assert {relations[0]["left_field_id"], relations[0]["right_field_id"]} == {left["id"], right["id"]}


def test_distinct_and_ignore_reviews_are_auditable_and_single_use(tmp_path):
    import pytest
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "review-audit.sqlite")
    fields = FieldService(db)
    source = fields.create_field(key="publication_year", label="Publication year")
    distinct_target = fields.create_field(key="citation_count", label="Citation count")
    ignore_target = fields.create_field(key="abstract_length", label="Abstract length")
    distinct_id = _insert_field_candidate(db, source["id"], distinct_target["id"], 0.4)
    ignore_id = _insert_field_candidate(db, source["id"], ignore_target["id"], 0.3)
    semantic = SemanticDedupService(db)

    distinct = semantic.review_candidate(distinct_id, "distinct", reason="Different meanings")
    ignored = semantic.review_candidate(ignore_id, "ignore", reason="Noise")

    assert distinct["decision"] == "distinct"
    assert ignored["decision"] == "ignore"
    assert semantic.get_review(distinct_id)["reason"] == "Different meanings"
    with pytest.raises(ValueError, match="already reviewed"):
        semantic.review_candidate(distinct_id, "ignore", reason="Second decision")


def test_scan_field_similarity_finds_reordered_duplicate_without_reverse_pair(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "scan.sqlite")
    fields = FieldService(db)
    left = fields.create_field(key="author_country", label="Author country")
    right = fields.create_field(key="country_author", label="Country author")
    fields.create_field(key="publication_year", label="Publication year", value_type="integer")

    found = SemanticDedupService(db).scan_field_similarity(
        namespace="global", threshold=0.70, max_neighbors=4
    )
    pairs = [{item["source_ref"], item["candidate_field_id"]} for item in found]

    assert {left["id"], right["id"]} in pairs
    raw_pairs = [(item["source_ref"], item["candidate_field_id"]) for item in found]
    assert len(raw_pairs) == len({tuple(sorted(pair)) for pair in raw_pairs})


def test_scan_field_similarity_bounds_candidate_pairs_per_source(tmp_path):
    from sedb.semantic import SemanticDedupService

    db = Database(tmp_path / "bounded-scan.sqlite")
    fields = FieldService(db)
    count = 180
    fields.bulk_create_fields(
        [
            {"key": f"metric_{i:04d}", "label": f"Metric {i:04d}", "value_type": "number"}
            for i in range(count)
        ]
    )

    found = SemanticDedupService(db).scan_field_similarity(
        namespace="global", threshold=0.0, max_neighbors=3
    )
    assert len(found) <= count * 3
    assert db.scalar("SELECT COUNT(*) FROM semantic_candidates WHERE source_kind='field'") <= count * 3

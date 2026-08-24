from sedb.agent import AgentService, DeterministicDiscoveryBackend
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.governance import FieldGovernanceService


def _counts(db):
    return (
        db.scalar("SELECT COUNT(*) FROM fields"),
        db.scalar("SELECT COUNT(*) FROM cells"),
    )


def test_deterministic_run_creates_advisory_artifacts_without_canonical_mutation(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    fields = FieldService(db)
    entities = EntityService(db)
    fields.create_field(key="paper", label="Paper")
    entity = entities.create_entity(label="Existing row")
    entities.set_cell(entity["id"], "paper", "P000")
    before = _counts(db)

    detail = AgentService(db).run_deterministic(
        {
            "records": [
                {
                    "paper": "P001",
                    "publication_type": "preprint",
                    "ai_assistance_disclosed": True,
                }
            ]
        },
        assess_existing=True,
        score_proposals=True,
    )

    assert detail["status"] == "completed"
    assert _counts(db) == before
    proposals = fields.list_proposals(limit=100)
    assert {p["key"] for p in proposals} == {"publication_type", "ai_assistance_disclosed"}
    assert all(p["proposed_by"] == f"agent:{detail['id']}" for p in proposals)
    outcomes = [action["outcome"] for action in detail["actions"]]
    assert "SKIPPED_ALREADY_REPRESENTED" in outcomes
    assert outcomes.count("CREATED_PROPOSAL") == 2
    assert outcomes.count("SCORED_PROPOSAL") == 2
    assert "ASSESSED_FIELD" in outcomes
    assert db.scalar("SELECT COUNT(*) FROM field_utility_assessments") >= 1


def test_alias_is_revalidated_and_skipped_without_proposal(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    field = FieldService(db).create_field(key="country", label="Country")
    FieldGovernanceService(db).add_alias(field["id"], "author_country", reason="fixture")

    detail = AgentService(db).run_deterministic(
        {"author-country": "Taiwan"}, assess_existing=False, score_proposals=False
    )

    assert db.scalar("SELECT COUNT(*) FROM field_proposals") == 0
    assert any(action["outcome"] == "SKIPPED_ALREADY_REPRESENTED" for action in detail["actions"])


def test_same_run_duplicate_suggestions_create_only_one_pending_proposal(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    service = AgentService(db)
    run = service.create_run(backend="external-suggestion-v1")
    service.record_observation(run["id"], {"source": "fixture"})
    suggestions = [
        {"key": "new_signal", "label": "New signal", "value_type": "text", "description": "", "reason": "one", "confidence": 0.8, "evidence_refs": []},
        {"key": "new-signal", "label": "New signal", "value_type": "text", "description": "", "reason": "two", "confidence": 0.7, "evidence_refs": []},
    ]

    receipts = service.execute_suggestions(run["id"], suggestions, score_proposals=False, assess_existing=False)

    assert db.scalar("SELECT COUNT(*) FROM field_proposals") == 1
    assert [receipt["outcome"] for receipt in receipts].count("CREATED_PROPOSAL") == 1
    assert any(receipt["outcome"] == "SKIPPED_DUPLICATE_SUGGESTION" for receipt in receipts)


def test_stale_suggestion_revalidates_after_another_process_creates_field(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    service = AgentService(db)
    run = service.create_run(backend="deterministic-discovery-v1")
    obs = service.record_observation(run["id"], {"new_signal": 1})
    suggestions = DeterministicDiscoveryBackend().suggest(obs["payload"])

    FieldService(db).create_field(key="new_signal", label="New signal")
    receipts = service.execute_suggestions(run["id"], suggestions, score_proposals=False, assess_existing=False)

    assert db.scalar("SELECT COUNT(*) FROM field_proposals") == 0
    assert receipts[0]["outcome"] == "SKIPPED_ALREADY_REPRESENTED"


def test_external_suggestion_run_uses_same_governance_gate(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    before = _counts(db)
    packet = {
        "suggestions": [
            {
                "key": "AI Assistance Disclosed",
                "label": "AI Assistance Disclosed",
                "value_type": "boolean",
                "reason": "External model found disclosure metadata",
                "confidence": 0.9,
                "evidence_refs": ["external:e1"],
            }
        ]
    }

    detail = AgentService(db).run_external(packet, score_proposals=False)

    assert detail["status"] == "completed"
    assert _counts(db) == before
    proposal = FieldService(db).list_proposals(limit=10)[0]
    assert proposal["key"] == "ai_assistance_disclosed"
    assert proposal["proposed_by"] == f"agent:{detail['id']}"


def test_optional_family_proposal_is_advisory_and_preserves_canonical_state(tmp_path):
    db = Database(tmp_path / "agent.sqlite")
    fields = FieldService(db)
    for key, label in [
        ("source_quality", "Source quality"),
        ("quality_source", "Quality source"),
        ("source_quality_score", "Source quality score"),
    ]:
        fields.create_field(key=key, label=label, value_type="number", description="source quality metric")
    before = _counts(db)

    detail = AgentService(db).run_deterministic(
        {"source_quality": 0.9},
        assess_existing=False,
        score_proposals=False,
        propose_families=True,
        family_seed_threshold=0.70,
        family_min_coherence=0.70,
    )

    assert _counts(db) == before
    assert db.scalar("SELECT COUNT(*) FROM field_family_proposals") == 1
    assert any(action["outcome"] == "PROPOSED_FAMILY" for action in detail["actions"])
    assert db.scalar("SELECT COUNT(*) FROM field_families") == 0

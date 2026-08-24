import sqlite3

import pytest

from sedb.agent import AgentService
from sedb.campaign import CampaignService
from sedb.db import Database
from sedb.fields import FieldService


def _link_run(campaigns, campaign_id, payload, run, label):
    item = campaigns.add_work_item(campaign_id, payload)
    campaigns.link_run(campaign_id, item["id"], run["id"], agent_label=label)


def _external(key, label, value_type="text", evidence="e1", description=""):
    return {
        "suggestions": [
            {
                "key": key,
                "label": label,
                "value_type": value_type,
                "reason": f"evidence {evidence}",
                "description": description,
                "confidence": 0.9,
                "evidence_refs": [evidence],
            }
        ]
    }


def test_same_backend_same_observation_is_not_counted_as_independent_support(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    observation = {"new_signal": 1}
    run1 = AgentService(db).run_deterministic(observation, score_proposals=False, assess_existing=False)
    run2 = AgentService(db).run_deterministic(observation, score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], observation, run1, "a")
    _link_run(campaigns, campaign["id"], observation, run2, "b")

    packets = campaigns.aggregate_campaign(campaign["id"])

    assert len(packets) == 1
    packet = packets[0]
    assert packet["status"] == "insufficient_independence"
    assert packet["metrics"]["raw_support"] == 2
    assert packet["metrics"]["independent_support"] == 1


def test_backend_and_evidence_diversity_can_produce_strong_agreement(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    obs = {"new_signal": 1}
    run1 = AgentService(db).run_deterministic(obs, score_proposals=False, assess_existing=False)
    run2 = AgentService(db).run_external(_external("new_signal", "New Signal", "integer", "source-b"), score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], obs, run1, "det")
    _link_run(campaigns, campaign["id"], {"source": "b"}, run2, "ext")

    packet = campaigns.aggregate_campaign(campaign["id"])[0]

    assert packet["status"] == "strong_agreement"
    assert packet["metrics"]["independent_support"] == 2
    assert packet["metrics"]["backend_count"] == 2
    assert packet["metrics"]["evidence_root_count"] == 2


def test_same_identity_with_incompatible_types_produces_incompatible_packet(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    run1 = AgentService(db).run_external(_external("flag", "Flag", "boolean", "a"), score_proposals=False, assess_existing=False)
    run2 = AgentService(db).run_external(_external("flag", "Flag", "text", "b"), score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], {"a": 1}, run1, "a")
    _link_run(campaigns, campaign["id"], {"b": 1}, run2, "b")

    packet = campaigns.aggregate_campaign(campaign["id"])[0]

    assert packet["status"] == "incompatible"
    assert packet["metrics"]["value_types"] == ["boolean", "text"]


def test_semantically_divergent_variants_are_preserved_as_disputed(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    run1 = AgentService(db).run_external(_external("author_country", "Nationality", "text", "a", "person citizenship identity"), score_proposals=False, assess_existing=False)
    run2 = AgentService(db).run_external(_external("author-country", "GPU memory bandwidth", "text", "b", "hardware throughput accelerator memory"), score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], {"a": 1}, run1, "a")
    _link_run(campaigns, campaign["id"], {"b": 1}, run2, "b")

    packet = campaigns.aggregate_campaign(campaign["id"], semantic_floor=0.72)[0]

    assert packet["status"] == "disputed"
    assert packet["metrics"]["min_pair_score"] < 0.72


def test_divergent_run_basis_is_never_hidden_inside_consensus(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    run1 = AgentService(db).run_external(_external("new_signal", "New Signal", evidence="a"), score_proposals=False, assess_existing=False)
    FieldService(db).create_field(key="intervening_field", label="Intervening")
    run2 = AgentService(db).run_external(_external("new_signal", "New Signal", evidence="b"), score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], {"a": 1}, run1, "a")
    _link_run(campaigns, campaign["id"], {"b": 1}, run2, "b")

    packet = campaigns.aggregate_campaign(campaign["id"])[0]

    assert packet["status"] == "basis_incompatible"
    assert packet["metrics"]["basis_count"] == 2


def test_aggregation_is_advisory_and_consensus_packet_is_immutable(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    before = (db.scalar("SELECT COUNT(*) FROM fields"), db.scalar("SELECT COUNT(*) FROM cells"))
    run = AgentService(db).run_external(_external("new_signal", "New Signal"), score_proposals=False, assess_existing=False)
    _link_run(campaigns, campaign["id"], {"x": 1}, run, "a")

    packet = campaigns.aggregate_campaign(campaign["id"])[0]
    after = (db.scalar("SELECT COUNT(*) FROM fields"), db.scalar("SELECT COUNT(*) FROM cells"))

    assert after == before
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as conn:
            conn.execute("UPDATE field_agent_consensus_packets SET summary='changed' WHERE id=?", (packet["id"],))

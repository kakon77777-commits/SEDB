import pytest

from sedb.agent import AgentService
from sedb.campaign import CampaignService
from sedb.db import Database


def test_only_terminal_agent_runs_can_be_linked(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    item = campaigns.add_work_item(campaign["id"], {"x": 1})
    run = AgentService(db).create_run(backend="deterministic-discovery-v1")

    with pytest.raises(ValueError, match="terminal Agent run"):
        campaigns.link_run(campaign["id"], item["id"], run["id"], agent_label="agent-a")


def test_link_run_completes_work_claim_and_aggregates_counters(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    item = campaigns.add_work_item(campaign["id"], {"new_signal": 1})
    claim = campaigns.claim_work_item(campaign["id"], item["id"], agent_label="agent-a")
    run = AgentService(db).run_deterministic(
        {"new_signal": 1}, score_proposals=False, assess_existing=False
    )

    linked = campaigns.link_run(
        campaign["id"], item["id"], run["id"], agent_label="agent-a",
        claim_token=claim["lease_token"], cost_units=3,
    )
    detail = campaigns.get_campaign(campaign["id"])

    assert linked["run_id"] == run["id"]
    assert detail["work_items"][0]["status"] == "completed"
    assert detail["claims"][0]["status"] == "completed"
    assert detail["claims"][0]["run_id"] == run["id"]
    assert detail["counters"]["runs"] == 1
    assert detail["counters"]["agent_steps"] == run["counters"]["steps"]
    assert detail["counters"]["proposals"] == run["counters"]["proposals"]
    assert detail["counters"]["cost_units"] == 3
    assert linked["observation_root_sha256"]


def test_agent_run_cannot_be_linked_to_two_campaign_slots(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C")
    first = campaigns.add_work_item(campaign["id"], {"a": 1})
    second = campaigns.add_work_item(campaign["id"], {"b": 2})
    run = AgentService(db).run_deterministic({"a": 1}, score_proposals=False, assess_existing=False)

    campaigns.link_run(campaign["id"], first["id"], run["id"], agent_label="agent-a")
    with pytest.raises(ValueError, match="already linked"):
        campaigns.link_run(campaign["id"], second["id"], run["id"], agent_label="agent-b")


def test_campaign_run_budget_exhaustion_blocks_second_link(tmp_path):
    db = Database(tmp_path / "campaign.sqlite")
    campaigns = CampaignService(db)
    campaign = campaigns.create_campaign(name="C", budget={"max_runs": 1})
    first = campaigns.add_work_item(campaign["id"], {"a": 1})
    second = campaigns.add_work_item(campaign["id"], {"b": 2})
    run1 = AgentService(db).run_deterministic({"a": 1}, score_proposals=False, assess_existing=False)
    run2 = AgentService(db).run_deterministic({"b": 2}, score_proposals=False, assess_existing=False)

    campaigns.link_run(campaign["id"], first["id"], run1["id"], agent_label="agent-a")
    with pytest.raises(ValueError, match="max_runs"):
        campaigns.link_run(campaign["id"], second["id"], run2["id"], agent_label="agent-b")

    detail = campaigns.get_campaign(campaign["id"])
    assert detail["status"] == "budget_exhausted"
    assert detail["counters"]["runs"] == 1
    assert len(detail["runs"]) == 1

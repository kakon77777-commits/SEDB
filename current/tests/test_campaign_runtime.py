from datetime import datetime, timedelta, timezone

import pytest

from sedb.campaign import CampaignService
from sedb.db import Database


def test_campaign_creation_records_policy_budget_basis_and_counters(tmp_path):
    service = CampaignService(Database(tmp_path / "campaign.sqlite"))
    campaign = service.create_campaign(
        name="Field census",
        task_text="discover missing fields",
        budget={"max_runs": 3, "max_work_items": 4},
        evaluator="test:coordinator",
    )

    assert campaign["status"] == "created"
    assert campaign["budget"]["max_runs"] == 3
    assert campaign["budget"]["max_work_items"] == 4
    assert campaign["counters"] == {
        "work_items": 0,
        "runs": 0,
        "agent_steps": 0,
        "proposals": 0,
        "cost_units": 0,
    }
    assert len(campaign["basis_sha256"]) == 64


def test_work_item_has_only_one_active_claim(tmp_path):
    service = CampaignService(Database(tmp_path / "campaign.sqlite"))
    campaign = service.create_campaign(name="C")
    item = service.add_work_item(campaign["id"], {"records": [{"x": 1}]})

    first = service.claim_work_item(campaign["id"], item["id"], agent_label="agent-a", lease_seconds=60)
    with pytest.raises(ValueError, match="already actively claimed"):
        service.claim_work_item(campaign["id"], item["id"], agent_label="agent-b", lease_seconds=60)

    assert first["status"] == "active"
    assert service.get_campaign(campaign["id"])["work_items"][0]["status"] == "claimed"


def test_expired_claim_can_be_reclaimed(tmp_path):
    service = CampaignService(Database(tmp_path / "campaign.sqlite"))
    campaign = service.create_campaign(name="C")
    item = service.add_work_item(campaign["id"], {"x": 1})
    t0 = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)

    first = service.claim_work_item(
        campaign["id"], item["id"], agent_label="agent-a", lease_seconds=10, now=t0
    )
    second = service.claim_work_item(
        campaign["id"], item["id"], agent_label="agent-b", lease_seconds=10, now=t0 + timedelta(seconds=11)
    )

    assert first["lease_token"] != second["lease_token"]
    detail = service.get_campaign(campaign["id"])
    statuses = [claim["status"] for claim in detail["claims"]]
    assert statuses == ["expired", "active"]


def test_terminal_campaign_rejects_new_work_and_claims(tmp_path):
    service = CampaignService(Database(tmp_path / "campaign.sqlite"))
    campaign = service.create_campaign(name="C")
    item = service.add_work_item(campaign["id"], {"x": 1})
    service.complete_campaign(campaign["id"])

    with pytest.raises(ValueError, match="terminal"):
        service.add_work_item(campaign["id"], {"y": 2})
    with pytest.raises(ValueError, match="terminal"):
        service.claim_work_item(campaign["id"], item["id"], agent_label="agent-a")


def test_work_item_budget_exhaustion_marks_campaign_terminal(tmp_path):
    service = CampaignService(Database(tmp_path / "campaign.sqlite"))
    campaign = service.create_campaign(name="C", budget={"max_work_items": 1})
    service.add_work_item(campaign["id"], {"x": 1})

    with pytest.raises(ValueError, match="max_work_items"):
        service.add_work_item(campaign["id"], {"y": 2})

    assert service.get_campaign(campaign["id"])["status"] == "budget_exhausted"

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sedb.server import create_server


@contextmanager
def running_server(tmp_path):
    server = create_server(tmp_path / "campaign-server.sqlite", host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(base + path, data=data, method=method, headers={"Content-Type":"application/json"} if data else {})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_campaign_api_can_coordinate_existing_agent_runs_and_aggregate(tmp_path):
    with running_server(tmp_path) as base:
        status, campaign = request_json(base, "POST", "/api/agent-campaigns", {"name":"C","task_text":"discover"})
        assert status == 200
        _, work1 = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/work", {"payload":{"new_signal":1}})
        _, work2 = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/work", {"payload":{"new_signal":1}})
        _, run1 = request_json(base, "POST", "/api/agent/run/deterministic", {"observation":{"new_signal":1},"score_proposals":False,"assess_existing":False})
        _, run2 = request_json(base, "POST", "/api/agent/run/deterministic", {"observation":{"new_signal":1},"score_proposals":False,"assess_existing":False})
        request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/link-run", {"work_item_id":work1['id'],"run_id":run1['id'],"agent_label":"a"})
        request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/link-run", {"work_item_id":work2['id'],"run_id":run2['id'],"agent_label":"b"})
        agg_status, packets = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/aggregate", {})
        _, detail = request_json(base, "GET", f"/api/agent-campaigns/{campaign['id']}")
        _, campaigns = request_json(base, "GET", "/api/agent-campaigns")

    assert agg_status == 200
    assert packets[0]["status"] == "insufficient_independence"
    assert detail["counters"]["runs"] == 2
    assert any(row["id"] == campaign["id"] for row in campaigns)


def test_campaign_api_exposes_claim_and_complete_without_canonical_mutation_route(tmp_path):
    with running_server(tmp_path) as base:
        _, campaign = request_json(base, "POST", "/api/agent-campaigns", {"name":"C"})
        _, work = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/work", {"payload":{"x":1}})
        status, claim = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/claim", {"work_item_id":work['id'],"agent_label":"a","lease_seconds":60})
        assert status == 200 and claim["status"] == "active"
        # complete is rejected while an active lease exists; the API remains explicit.
        complete_status, _ = request_json(base, "POST", f"/api/agent-campaigns/{campaign['id']}/complete", {})

    assert complete_status == 400


def test_browser_has_multi_agent_campaign_panel_without_consensus_mutation_controls(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=5) as response:
            js = response.read().decode("utf-8")

    assert "Multi-Agent Campaigns" in html
    assert 'data-campaign-panel="advisory-only"' in html
    assert "data-campaign-mutation" not in html
    assert "loadCampaigns" in js
    assert "aggregateCampaign" in js

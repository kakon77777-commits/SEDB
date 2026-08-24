import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sedb.server import create_server


@contextmanager
def running_server(tmp_path):
    server = create_server(tmp_path / "agent-server.sqlite", host="127.0.0.1", port=0)
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
    req = Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_deterministic_agent_run_api_is_advisory_and_queryable(tmp_path):
    with running_server(tmp_path) as base:
        _, before = request_json(base, "GET", "/api/stats")
        status, run = request_json(
            base,
            "POST",
            "/api/agent/run/deterministic",
            {
                "observation": {"records": [{"paper": "P1", "ai_disclosed": True}]},
                "score_proposals": False,
                "assess_existing": False,
            },
        )
        _, after = request_json(base, "GET", "/api/stats")
        list_status, runs = request_json(base, "GET", "/api/agent/runs")
        detail_status, detail = request_json(base, "GET", f"/api/agent/runs/{run['id']}")

    assert status == 200 and run["status"] == "completed"
    assert before["fields"] == after["fields"]
    assert before["cells"] == after["cells"]
    assert after["proposals"] >= before["proposals"] + 2
    assert list_status == detail_status == 200
    assert any(item["id"] == run["id"] for item in runs)
    assert detail["actions"]


def test_external_agent_run_api_uses_same_governed_runtime(tmp_path):
    packet = {
        "suggestions": [
            {
                "key": "AI Assistance Disclosed",
                "label": "AI Assistance Disclosed",
                "value_type": "boolean",
                "reason": "External model suggestion",
                "confidence": 0.9,
                "evidence_refs": ["external:e1"],
            }
        ]
    }
    with running_server(tmp_path) as base:
        status, run = request_json(
            base,
            "POST",
            "/api/agent/run/external",
            {"packet": packet, "score_proposals": False},
        )
        _, proposals = request_json(base, "GET", "/api/proposals")

    assert status == 200 and run["backend"] == "external-suggestion-v1"
    assert proposals[0]["key"] == "ai_assistance_disclosed"
    assert proposals[0]["proposed_by"] == f"agent:{run['id']}"


def test_agent_api_budget_can_halt_before_proposal_creation(tmp_path):
    with running_server(tmp_path) as base:
        status, run = request_json(
            base,
            "POST",
            "/api/agent/run/deterministic",
            {
                "observation": {"new_field": 1},
                "budget": {"max_steps": 1, "max_observations": 1, "max_proposals": 5},
                "score_proposals": False,
            },
        )
        _, proposals = request_json(base, "GET", "/api/proposals")

    assert status == 200
    assert run["status"] == "budget_exhausted"
    assert proposals == []
    assert run["events"][-1]["event_type"] == "budget_exhausted"


def test_browser_has_advisory_agent_panel_without_agent_mutation_controls(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=5) as response:
            js = response.read().decode("utf-8")

    assert "AI Field Agent" in html
    assert 'data-agent-panel="advisory-only"' in html
    assert "data-agent-mutation" not in html
    assert "agentRunDeterministic" in html and "agentRunExternal" in html
    assert "loadAgentRuns" in js

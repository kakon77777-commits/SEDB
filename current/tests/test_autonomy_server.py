import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from sedb.campaign import CampaignService
from sedb.db import Database
from sedb.fields import FieldService
from sedb.server import create_server


@contextmanager
def running_server(tmp_path):
    db_path = tmp_path / "autonomy-server.sqlite"
    server = create_server(db_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", db_path
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def request_json(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(base + path, data=data, method=method,
                  headers={"Content-Type":"application/json"} if data else {})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def make_packet(db_path, status):
    db = Database(db_path)
    campaign = CampaignService(db).create_campaign(name=f"C-{status}")
    group_id, packet_id = uuid4().hex, uuid4().hex
    now = "2026-08-23T00:00:00Z"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO field_agent_advisory_groups(
                id,campaign_id,namespace,normalized_key,raw_support,independent_support,
                backend_count,evidence_root_count,conflict_count,basis_count,min_pair_score,
                avg_pair_score,metrics_json,evidence_json,created_at
            ) VALUES(?,?, 'global','candidate',3,2,2,2,0,1,1.0,1.0,'{}','{}',?)
            """, (group_id, campaign["id"], now))
        conn.execute(
            """
            INSERT INTO field_agent_consensus_packets(
                id,campaign_id,group_id,policy_version,status,summary,metrics_json,
                evidence_json,basis_sha256,created_at
            ) VALUES(?,?,?,'consensus-v1',?,'fixture','{}','{}','basis',?)
            """, (packet_id, campaign["id"], group_id, status, now))
    return packet_id


def test_autonomy_api_executes_proposal_into_canonical_field(tmp_path):
    with running_server(tmp_path) as (base, db_path):
        db = Database(db_path)
        proposal = FieldService(db).create_proposal(
            key="ai_disclosed", label="AI disclosed", value_type="boolean",
            reason="agent evidence", proposed_by="agent:test")
        status, result = request_json(base, "POST", "/api/autonomy/execute", {
            "action": {"type":"accept_proposal", "proposal_id":proposal["id"], "reason":"autonomous commit"},
            "evaluator":"api:test"
        })
        _, stats = request_json(base, "GET", "/api/autonomy/stats")
        _, fields = request_json(base, "GET", "/api/fields")

    assert status == 200
    assert result["decision"]["decision"] == "EXECUTE"
    assert result["commit"]["mutation"]["outcome"] == "created"
    assert len(fields) == 1
    assert stats["commit_count"] == 1


def test_autonomy_api_conflict_escalates_and_never_commits(tmp_path):
    with running_server(tmp_path) as (base, db_path):
        db = Database(db_path)
        proposal = FieldService(db).create_proposal(
            key="review_status", label="Review status", reason="agent evidence", proposed_by="agent:test")
        packet = make_packet(db_path, "incompatible")
        status, result = request_json(base, "POST", "/api/autonomy/execute", {
            "action": {"type":"accept_proposal", "proposal_id":proposal["id"], "reason":"try"},
            "evidence": {"consensus_packet_id":packet}
        })
        _, decisions = request_json(base, "GET", "/api/autonomy/decisions")

    assert status == 200
    assert result["decision"]["decision"] == "ESCALATE"
    assert result["commit"] is None
    assert decisions[0]["decision"] == "ESCALATE"
    assert Database(db_path).scalar("SELECT COUNT(*) FROM fields") == 0


def test_autonomy_api_exposes_admin_envelopes_but_no_agent_self_grant_route(tmp_path):
    with running_server(tmp_path) as (base, _):
        status, envelopes = request_json(base, "GET", "/api/autonomy/envelopes")
        bad_status, _ = request_json(base, "POST", "/api/agent/autonomy/envelopes", {"name":"self grant"})

    assert status == 200
    assert any(row["id"] == "sedb-local-canonical-v1" for row in envelopes)
    assert bad_status == 404


def test_browser_contains_reflexive_autonomy_panel(tmp_path):
    with running_server(tmp_path) as (base, _):
        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=5) as response:
            js = response.read().decode("utf-8")

    assert "Reflexive Autonomy" in html
    assert "autonomyExecuteForm" in html
    assert "/api/autonomy/execute" in js
    assert "Decision ≠ Commit" in html

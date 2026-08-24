import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sedb.server import create_server


@contextmanager
def running_server(tmp_path):
    server = create_server(tmp_path / "server.sqlite", host="127.0.0.1", port=0)
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
        with urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_health_and_static_index(tmp_path):
    with running_server(tmp_path) as base:
        status, health = request_json(base, "GET", "/api/health")
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")

    assert status == 200
    assert health == {"ok": True, "version": "0.4.0b1"}
    assert "SEDB" in html
    assert "Unbounded Dynamic Field" in html


def test_field_entity_and_sparse_cell_api(tmp_path):
    with running_server(tmp_path) as base:
        field_status, field = request_json(
            base,
            "POST",
            "/api/fields",
            {"key": "year", "label": "Year", "value_type": "integer"},
        )
        entity_status, entity = request_json(
            base, "POST", "/api/entities", {"label": "Paper 1", "kind": "paper"}
        )
        cell_status, cell = request_json(
            base,
            "PUT",
            f"/api/entities/{entity['id']}/cells/year",
            {"value": 2026, "source": "test"},
        )
        loaded_status, loaded = request_json(base, "GET", f"/api/entities/{entity['id']}")
        stats_status, stats = request_json(base, "GET", "/api/stats")

    assert (field_status, entity_status, cell_status, loaded_status, stats_status) == (200, 200, 200, 200, 200)
    assert field["key"] == "year"
    assert cell["value"] == 2026
    assert loaded["values"] == {"year": 2026}
    assert stats["fields"] == 1 and stats["entities"] == 1 and stats["cells"] == 1


def test_converge_api_requires_reason_and_records_evaluation(tmp_path):
    with running_server(tmp_path) as base:
        _, field = request_json(base, "POST", "/api/fields", {"key": "country", "label": "Country"})
        bad_status, bad = request_json(
            base,
            "POST",
            f"/api/fields/{field['id']}/transition",
            {"to_status": "converged", "reason": ""},
        )
        good_status, converged = request_json(
            base,
            "POST",
            f"/api/fields/{field['id']}/transition",
            {
                "to_status": "converged",
                "reason": "Low marginal utility.",
                "metrics": {"utility": 0.05},
                "evaluator": "api:test",
            },
        )
        eval_status, evaluations = request_json(
            base, "GET", f"/api/fields/{field['id']}/evaluations"
        )

    assert bad_status == 400
    assert "reason" in bad["error"]
    assert good_status == 200 and converged["status"] == "converged"
    assert eval_status == 200
    assert evaluations[0]["metrics"] == {"utility": 0.05}


def test_proposal_and_task_view_api(tmp_path):
    with running_server(tmp_path) as base:
        request_json(base, "POST", "/api/fields", {"key": "year", "label": "Year"})
        request_json(base, "POST", "/api/fields", {"key": "verified", "label": "Verified"})
        _, entity = request_json(base, "POST", "/api/entities", {"label": "Paper"})
        request_json(base, "PUT", f"/api/entities/{entity['id']}/cells/year", {"value": 2026})
        proposal_status, proposal = request_json(
            base,
            "POST",
            "/api/proposals",
            {
                "key": "ai_evidence",
                "label": "AI evidence",
                "reason": "Potential discriminator",
                "proposed_by": "agent:test",
            },
        )
        view_status, view = request_json(
            base,
            "POST",
            "/api/views",
            {"name": "Audit", "field_keys": ["year", "verified"]},
        )
        matrix_status, matrix = request_json(base, "GET", f"/api/views/{view['id']}?field_limit=1")

    assert proposal_status == 200 and proposal["status"] == "pending"
    assert view_status == 200
    assert matrix_status == 200
    assert matrix["total_fields"] == 2
    assert [f["key"] for f in matrix["fields"]] == ["year"]
    assert matrix["rows"][0]["values"] == {"year": 2026}


def test_delete_cell_api_restores_blank(tmp_path):
    with running_server(tmp_path) as base:
        request_json(base, "POST", "/api/fields", {"key": "note", "label": "Note"})
        _, entity = request_json(base, "POST", "/api/entities", {"label": "Paper"})
        request_json(base, "PUT", f"/api/entities/{entity['id']}/cells/note", {"value": "x"})
        deleted_status, deleted = request_json(
            base, "DELETE", f"/api/entities/{entity['id']}/cells/note"
        )
        _, loaded = request_json(base, "GET", f"/api/entities/{entity['id']}")

    assert deleted_status == 200 and deleted == {"deleted": True}
    assert loaded["values"] == {}


def test_proposal_decision_api_aliases_normalized_duplicate(tmp_path):
    with running_server(tmp_path) as base:
        _, existing = request_json(
            base, "POST", "/api/fields", {"key": "author_country", "label": "Author country"}
        )
        _, proposal = request_json(
            base,
            "POST",
            "/api/proposals",
            {
                "key": "Author-Country",
                "label": "Duplicate wording",
                "reason": "Imported schema",
                "proposed_by": "agent:test",
            },
        )
        decision_status, decision = request_json(
            base,
            "POST",
            f"/api/proposals/{proposal['id']}/decision",
            {"decision": "accept", "reason": "Same normalized identity", "evaluator": "api:test"},
        )
        read_status, loaded = request_json(base, "GET", f"/api/proposals/{proposal['id']}/decision")
        _, stats = request_json(base, "GET", "/api/stats")

    assert decision_status == 200 and read_status == 200
    assert decision["outcome"] == "alias_existing"
    assert decision["target_field_id"] == existing["id"]
    assert loaded["proposal_id"] == proposal["id"]
    assert stats["fields"] == 1


def test_alias_and_definition_version_api(tmp_path):
    with running_server(tmp_path) as base:
        _, field = request_json(
            base, "POST", "/api/fields", {"key": "source_quality", "label": "Source quality"}
        )
        alias_status, alias = request_json(
            base,
            "POST",
            f"/api/fields/{field['id']}/aliases",
            {"alias": "source-reliability", "reason": "Legacy vocabulary"},
        )
        aliases_status, aliases = request_json(base, "GET", f"/api/fields/{field['id']}/aliases")
        update_status, updated = request_json(
            base,
            "POST",
            f"/api/fields/{field['id']}/definition",
            {
                "label": "Source reliability",
                "description": "Operational reliability definition",
                "reason": "Clarify semantics",
                "evaluator": "api:test",
            },
        )
        versions_status, versions = request_json(base, "GET", f"/api/fields/{field['id']}/versions")

    assert (alias_status, aliases_status, update_status, versions_status) == (200, 200, 200, 200)
    assert alias["field_id"] == field["id"]
    assert aliases[0]["alias"] == "source-reliability"
    assert updated["label"] == "Source reliability"
    assert [item["version"] for item in versions] == [1, 2]


def test_merge_split_and_lineage_api(tmp_path):
    with running_server(tmp_path) as base:
        _, merge_source = request_json(base, "POST", "/api/fields", {"key": "nation", "label": "Nation"})
        _, merge_target = request_json(base, "POST", "/api/fields", {"key": "country", "label": "Country"})
        merge_status, merge_edges = request_json(
            base,
            "POST",
            "/api/governance/merge",
            {
                "sources": [merge_source["id"]],
                "target": merge_target["id"],
                "reason": "Canonicalize geography",
                "evaluator": "api:test",
            },
        )
        merge_lineage_status, merge_lineage = request_json(
            base, "GET", f"/api/fields/{merge_source['id']}/lineage"
        )

        _, split_source = request_json(base, "POST", "/api/fields", {"key": "affiliation", "label": "Affiliation"})
        _, child_a = request_json(base, "POST", "/api/fields", {"key": "institution", "label": "Institution"})
        _, child_b = request_json(base, "POST", "/api/fields", {"key": "department", "label": "Department"})
        split_status, split_edges = request_json(
            base,
            "POST",
            "/api/governance/split",
            {
                "source": split_source["id"],
                "children": [child_a["id"], child_b["id"]],
                "reason": "Separate organization levels",
                "evaluator": "api:test",
            },
        )
        split_lineage_status, split_lineage = request_json(
            base, "GET", f"/api/fields/{split_source['id']}/lineage"
        )

    assert (merge_status, merge_lineage_status, split_status, split_lineage_status) == (200, 200, 200, 200)
    assert [edge["relation"] for edge in merge_edges] == ["merged_into"]
    assert [edge["relation"] for edge in merge_lineage] == ["merged_into"]
    assert len(split_edges) == 2 and {edge["relation"] for edge in split_edges} == {"split_into"}
    assert len(split_lineage) == 2


def test_static_index_exposes_field_governance_panel(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")

    assert 'id="proposalForm"' in html
    assert 'id="proposalList"' in html
    assert "Field Governance" in html


def test_semantic_candidate_score_review_and_list_api(tmp_path):
    with running_server(tmp_path) as base:
        _, target = request_json(
            base, "POST", "/api/fields", {"key": "author_country", "label": "Author country"}
        )
        _, proposal = request_json(
            base,
            "POST",
            "/api/proposals",
            {
                "key": "country_of_author",
                "label": "Country of author",
                "reason": "Imported vocabulary",
            },
        )
        score_status, candidates = request_json(
            base,
            "POST",
            f"/api/proposals/{proposal['id']}/candidates",
            {"top_k": 3, "max_candidates": 20},
        )
        list_status, listed = request_json(
            base, "GET", f"/api/proposals/{proposal['id']}/candidates"
        )
        review_status, review = request_json(
            base,
            "POST",
            f"/api/candidates/{candidates[0]['id']}/review",
            {
                "decision": "alias",
                "reason": "Reviewed as same dimension",
                "evaluator": "api:test",
            },
        )
        read_status, loaded_review = request_json(
            base, "GET", f"/api/candidates/{candidates[0]['id']}/review"
        )
        _, stats = request_json(base, "GET", "/api/stats")

    assert (score_status, list_status, review_status, read_status) == (200, 200, 200, 200)
    assert candidates[0]["candidate_field_id"] == target["id"]
    assert listed[0]["signals"]["final_score"] == listed[0]["score"]
    assert review["decision"] == "alias" and loaded_review["reason"] == "Reviewed as same dimension"
    assert stats["fields"] == 1


def test_registry_similarity_scan_and_related_relation_api(tmp_path):
    with running_server(tmp_path) as base:
        _, left = request_json(
            base, "POST", "/api/fields", {"key": "source_quality", "label": "Source quality"}
        )
        _, right = request_json(
            base, "POST", "/api/fields", {"key": "quality_source", "label": "Quality source"}
        )
        scan_status, found = request_json(
            base,
            "POST",
            "/api/governance/similarity/scan",
            {"namespace": "global", "threshold": 0.70, "max_neighbors": 4},
        )
        field_candidates_status, field_candidates = request_json(
            base, "GET", "/api/candidates?source_kind=field&status=pending"
        )
        chosen = next(
            item for item in field_candidates
            if {item["source_ref"], item["candidate_field_id"]} == {left["id"], right["id"]}
        )
        related_status, _ = request_json(
            base,
            "POST",
            f"/api/candidates/{chosen['id']}/review",
            {"decision": "related", "reason": "Related but not identical", "evaluator": "api:test"},
        )
        relations_status, relations = request_json(
            base, "GET", f"/api/fields/{left['id']}/relations"
        )

    assert (scan_status, field_candidates_status, related_status, relations_status) == (200, 200, 200, 200)
    assert found
    assert relations[0]["relation"] == "related_to"


def test_static_index_exposes_semantic_candidate_review_panel(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=3) as response:
            js = response.read().decode("utf-8")

    assert 'id="semanticCandidateList"' in html
    assert "Semantic Candidates" in html
    assert "/candidates" in js
    assert "Score" in js


def test_field_utility_assessment_guardrail_scan_and_apply_api(tmp_path):
    with running_server(tmp_path) as base:
        request_json(base, "POST", "/api/entities", {"label": "Row 1"})
        _, unused = request_json(
            base, "POST", "/api/fields", {"key": "old_unused_api", "label": "Old unused API"}
        )
        assess_status, assessment = request_json(
            base,
            "POST",
            f"/api/fields/{unused['id']}/utility/assess",
            {"as_of": "2100-01-01T00:00:00Z", "evaluator": "api:test"},
        )
        list_status, history = request_json(
            base, "GET", f"/api/fields/{unused['id']}/utility/assessments"
        )

        _, protected = request_json(
            base, "POST", "/api/fields", {"key": "protected_api", "label": "Protected API"}
        )
        guard_status, guard = request_json(
            base,
            "POST",
            f"/api/fields/{protected['id']}/guardrail",
            {"protected": True, "reason": "Preserve rare field", "evaluator": "api:test"},
        )
        guard_get_status, guard_get = request_json(
            base, "GET", f"/api/fields/{protected['id']}/guardrail"
        )

        scan_status, scan = request_json(
            base,
            "POST",
            "/api/governance/utility/scan",
            {
                "statuses": ["active"],
                "limit_fields": 10,
                "as_of": "2100-01-01T00:00:00Z",
                "evaluator": "api:scan",
            },
        )
        apply_status, applied = request_json(
            base,
            "POST",
            f"/api/utility/assessments/{assessment['id']}/apply",
            {"reason": "Reviewed utility evidence", "evaluator": "api:test"},
        )

    assert (assess_status, list_status, guard_status, guard_get_status, scan_status, apply_status) == (
        200, 200, 200, 200, 200, 200
    )
    assert assessment["recommendation"] == "converge_candidate"
    assert history[-1]["id"] == assessment["id"]
    assert guard["protected"] is True and guard_get["protected"] is True
    assert len(scan) == 2
    assert applied["field"]["status"] == "converged"


def test_field_utility_apply_api_rejects_stale_assessment(tmp_path):
    with running_server(tmp_path) as base:
        _, entity = request_json(base, "POST", "/api/entities", {"label": "Row 1"})
        _, field = request_json(
            base, "POST", "/api/fields", {"key": "stale_api", "label": "Stale API"}
        )
        _, assessment = request_json(
            base,
            "POST",
            f"/api/fields/{field['id']}/utility/assess",
            {"as_of": "2100-01-01T00:00:00Z"},
        )
        request_json(
            base,
            "PUT",
            f"/api/entities/{entity['id']}/cells/{field['key']}",
            {"value": "new evidence"},
        )
        status, payload = request_json(
            base,
            "POST",
            f"/api/utility/assessments/{assessment['id']}/apply",
            {"reason": "Attempt stale apply", "evaluator": "api:test"},
        )

    assert status == 400
    assert "stale" in payload["error"]


def test_static_index_exposes_field_utility_panel_with_explicit_apply(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=3) as response:
            js = response.read().decode("utf-8")

    assert "Field Utility" in html
    assert 'id="utilityFieldRef"' in html
    assert 'id="utilityAssessBtn"' in html
    assert 'id="utilityApplyReason"' in html
    assert 'id="utilityRegistryScan"' in html
    assert "/utility/assess" in js
    assert "/guardrail" in js
    assert "/governance/utility/scan" in js
    assert "data-utility-apply" in js


def test_field_family_api_generate_review_and_read(tmp_path):
    with running_server(tmp_path) as base:
        created = []
        for payload in [
            {"key":"source_quality","label":"Source quality","value_type":"number","description":"quality of source"},
            {"key":"quality_source","label":"Quality source","value_type":"number","description":"source quality metric"},
            {"key":"source_quality_score","label":"Source quality score","value_type":"number","description":"score for source quality"},
        ]:
            status, field = request_json(base, "POST", "/api/fields", payload)
            assert status == 200
            created.append(field)

        generate_status, proposal = request_json(
            base, "POST", "/api/family-proposals/generate",
            {
                "seed_ref": created[0]["id"], "seed_threshold": 0.70,
                "min_coherence": 0.70, "max_neighbors": 8, "max_members": 5,
                "namespace": "global", "evaluator": "api:test",
            },
        )
        list_status, proposals = request_json(base, "GET", "/api/family-proposals")
        get_status, loaded = request_json(base, "GET", f"/api/family-proposals/{proposal['id']}")
        review_status, reviewed = request_json(
            base, "POST", f"/api/family-proposals/{proposal['id']}/review",
            {"decision":"duplicate_family","reason":"API reviewed family","evaluator":"api:test"},
        )
        family_id = reviewed["family"]["id"]
        families_status, families = request_json(base, "GET", "/api/field-families")
        family_status, family = request_json(base, "GET", f"/api/field-families/{family_id}")

    assert (generate_status, list_status, get_status, review_status, families_status, family_status) == (200,200,200,200,200,200)
    assert proposal["member_count"] == 3
    assert proposals and proposals[0]["id"] == proposal["id"]
    assert loaded["id"] == proposal["id"]
    assert reviewed["review"]["decision"] == "duplicate_family"
    assert families[0]["id"] == family_id
    assert family["family_type"] == "duplicate"
    assert len(family["members"]) == 3


def test_field_family_registry_scan_api(tmp_path):
    with running_server(tmp_path) as base:
        for payload in [
            {"key":"model_latency","label":"Model latency","value_type":"number","description":"latency of model"},
            {"key":"latency_model","label":"Latency model","value_type":"number","description":"model latency metric"},
            {"key":"model_latency_score","label":"Model latency score","value_type":"number","description":"score for model latency"},
        ]:
            request_json(base, "POST", "/api/fields", payload)
        status, proposals = request_json(
            base, "POST", "/api/family-proposals/scan",
            {
                "namespace":"global","seed_threshold":0.70,"min_coherence":0.70,
                "max_neighbors":8,"max_members":5,"limit_fields":100,"max_proposals":10,
            },
        )

    assert status == 200
    assert proposals
    assert any(item["member_count"] == 3 for item in proposals)


def test_field_family_browser_panel_markers(tmp_path):
    with running_server(tmp_path) as base:
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        with urlopen(base + "/app.js", timeout=3) as response:
            js = response.read().decode("utf-8")

    assert "Field Families" in html
    assert "familySeedRef" in html
    assert "/api/family-proposals/generate" in js
    assert "duplicate_family" in js

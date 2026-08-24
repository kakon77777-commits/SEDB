from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .db import Database
from .entities import EntityService
from .fields import FieldService
from .family import FieldFamilyService
from .governance import FieldGovernanceService
from .semantic import SemanticDedupService
from .utility import UtilityService
from .views import ViewService
from .agent import AgentService
from .campaign import CampaignService
from .autonomy import AutonomyService


_WEB_DIR = Path(__file__).with_name("web")


def create_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    db = Database(db_path)
    fields = FieldService(db)
    families = FieldFamilyService(db)
    governance = FieldGovernanceService(db)
    semantic = SemanticDedupService(db)
    utility = UtilityService(db)
    entities = EntityService(db)
    views = ViewService(db)
    agent = AgentService(db)
    campaigns = CampaignService(db)
    autonomy = AutonomyService(db)
    autonomy.ensure_default_envelope()

    class Handler(BaseHTTPRequestHandler):
        server_version = "SEDB/0.4B"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON request body must be an object")
            return value

        def _serve_static(self, request_path: str) -> bool:
            mapping = {
                "/": "index.html",
                "/index.html": "index.html",
                "/app.js": "app.js",
                "/style.css": "style.css",
            }
            filename = mapping.get(request_path)
            if filename is None:
                return False
            path = _WEB_DIR / filename
            data = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if filename.endswith((".html", ".js", ".css")):
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

        def _route(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if self.command == "GET" and not path.startswith("/api/"):
                if self._serve_static(path):
                    return
                self._send_json({"error": "not found"}, 404)
                return

            segments = [segment for segment in path.split("/") if segment]
            try:
                if self.command == "GET" and path == "/api/health":
                    self._send_json({"ok": True, "version": __version__})
                    return
                if self.command == "GET" and path == "/api/stats":
                    self._send_json(views.stats())
                    return
                if self.command == "GET" and path == "/api/autonomy/envelopes":
                    self._send_json(autonomy.list_envelopes())
                    return
                if self.command == "POST" and path == "/api/autonomy/envelopes":
                    body = self._read_json()
                    rules = body.get("rules")
                    if not isinstance(rules, dict):
                        raise ValueError("rules must be an object")
                    self._send_json(
                        autonomy.install_envelope(
                            envelope_id=str(body.get("id", "")),
                            name=str(body.get("name", "")),
                            version=int(body.get("version", 1)),
                            rules=rules,
                            contract_ref=str(body.get("contract_ref", "")),
                            authority_ref=str(body.get("authority_ref", "")),
                            created_by=str(body.get("created_by", "api:admin")),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/autonomy/decisions":
                    self._send_json(
                        autonomy.list_decisions(
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/autonomy/stats":
                    self._send_json(autonomy.stats())
                    return
                if self.command == "POST" and path in {"/api/autonomy/decide", "/api/autonomy/execute"}:
                    body = self._read_json()
                    action = body.get("action")
                    if not isinstance(action, dict):
                        raise ValueError("action must be an object")
                    evidence = body.get("evidence")
                    if evidence is not None and not isinstance(evidence, dict):
                        raise ValueError("evidence must be an object")
                    envelope_id = str(body.get("envelope_id", "sedb-local-canonical-v1"))
                    evaluator = str(body.get("evaluator", "api:autonomy"))
                    if path.endswith("/decide"):
                        self._send_json(autonomy.decide(action, envelope_id, evidence=evidence, evaluator=evaluator))
                    else:
                        self._send_json(autonomy.execute_autonomously(action, envelope_id, evidence=evidence, evaluator=evaluator))
                    return
                if (
                    len(segments) == 5
                    and segments[:3] == ["api", "autonomy", "decisions"]
                    and segments[4] == "commit"
                    and self.command == "POST"
                ):
                    self._send_json(autonomy.commit_decision(segments[3]))
                    return
                if (
                    len(segments) == 5
                    and segments[:3] == ["api", "autonomy", "commits"]
                    and segments[4] == "rollback"
                    and self.command == "POST"
                ):
                    body = self._read_json()
                    self._send_json(autonomy.rollback_commit(segments[3], evaluator=str(body.get("evaluator", "api:rollback"))))
                    return
                if self.command == "GET" and path == "/api/agent-campaigns":
                    self._send_json(
                        campaigns.list_campaigns(
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/agent-campaigns":
                    body = self._read_json()
                    budget = body.get("budget")
                    if budget is not None and not isinstance(budget, dict):
                        raise ValueError("budget must be an object")
                    self._send_json(
                        campaigns.create_campaign(
                            name=str(body.get("name", "")),
                            task_text=str(body.get("task_text", "")),
                            namespace=str(body.get("namespace", "global")),
                            budget=budget,
                            evaluator=str(body.get("evaluator", "api:campaign")),
                        )
                    )
                    return
                if len(segments) == 3 and segments[:2] == ["api", "agent-campaigns"] and self.command == "GET":
                    self._send_json(campaigns.get_campaign(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "agent-campaigns"] and self.command == "POST":
                    campaign_id = segments[2]
                    action = segments[3]
                    body = self._read_json()
                    if action == "work":
                        self._send_json(campaigns.add_work_item(campaign_id, body.get("payload", {})))
                        return
                    if action == "claim":
                        self._send_json(
                            campaigns.claim_work_item(
                                campaign_id,
                                str(body.get("work_item_id", "")),
                                agent_label=str(body.get("agent_label", "")),
                                lease_seconds=int(body.get("lease_seconds", 300)),
                            )
                        )
                        return
                    if action == "link-run":
                        self._send_json(
                            campaigns.link_run(
                                campaign_id,
                                str(body.get("work_item_id", "")),
                                str(body.get("run_id", "")),
                                agent_label=str(body.get("agent_label", "")),
                                claim_token=str(body.get("claim_token")) if body.get("claim_token") else None,
                                cost_units=int(body.get("cost_units", 1)),
                            )
                        )
                        return
                    if action == "aggregate":
                        self._send_json(
                            campaigns.aggregate_campaign(
                                campaign_id,
                                semantic_floor=float(body.get("semantic_floor", 0.72)),
                            )
                        )
                        return
                    if action == "complete":
                        self._send_json(campaigns.complete_campaign(campaign_id))
                        return
                if self.command == "GET" and path == "/api/agent/runs":
                    self._send_json(
                        agent.list_runs(
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:3] == ["api", "agent", "runs"] and self.command == "GET":
                    self._send_json(agent.get_run(segments[3]))
                    return
                if self.command == "POST" and path == "/api/agent/run/deterministic":
                    body = self._read_json()
                    budget = body.get("budget")
                    if budget is not None and not isinstance(budget, dict):
                        raise ValueError("budget must be an object")
                    self._send_json(
                        agent.run_deterministic(
                            body.get("observation", {}),
                            namespace=str(body.get("namespace", "global")),
                            budget=budget,
                            evaluator=str(body.get("evaluator", "api:agent")),
                            score_proposals=bool(body.get("score_proposals", True)),
                            assess_existing=bool(body.get("assess_existing", True)),
                            propose_families=bool(body.get("propose_families", False)),
                            score_top_k=int(body.get("score_top_k", 5)),
                            family_seed_threshold=float(body.get("family_seed_threshold", 0.78)),
                            family_min_coherence=float(body.get("family_min_coherence", 0.72)),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/agent/run/external":
                    body = self._read_json()
                    packet = body.get("packet")
                    if not isinstance(packet, dict):
                        raise ValueError("packet must be an object")
                    budget = body.get("budget")
                    if budget is not None and not isinstance(budget, dict):
                        raise ValueError("budget must be an object")
                    self._send_json(
                        agent.run_external(
                            packet,
                            namespace=str(body.get("namespace", "global")),
                            budget=budget,
                            evaluator=str(body.get("evaluator", "api:external-agent")),
                            score_proposals=bool(body.get("score_proposals", True)),
                            assess_existing=bool(body.get("assess_existing", True)),
                            propose_families=bool(body.get("propose_families", False)),
                            score_top_k=int(body.get("score_top_k", 5)),
                            family_seed_threshold=float(body.get("family_seed_threshold", 0.78)),
                            family_min_coherence=float(body.get("family_min_coherence", 0.72)),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/fields":
                    self._send_json(
                        fields.list_fields(
                            search=query.get("search", [""])[0],
                            status=query.get("status", [""])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/fields":
                    body = self._read_json()
                    self._send_json(
                        fields.create_field(
                            key=str(body.get("key", "")),
                            label=str(body.get("label", "")),
                            value_type=str(body.get("value_type", "text")),
                            description=str(body.get("description", "")),
                            status=str(body.get("status", "active")),
                            namespace=str(body.get("namespace", "global")),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "transition" and self.command == "POST":
                    body = self._read_json()
                    self._send_json(
                        fields.transition(
                            segments[2],
                            str(body.get("to_status", "")),
                            reason=str(body.get("reason", "")),
                            evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else {},
                            evaluator=str(body.get("evaluator", "")),
                            reversible=bool(body.get("reversible", True)),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "evaluations" and self.command == "GET":
                    self._send_json(fields.list_evaluations(segments[2]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "fields"] and segments[3:] == ["utility", "assess"] and self.command == "POST":
                    body = self._read_json()
                    self._send_json(
                        utility.assess_field(
                            segments[2],
                            evaluator=str(body.get("evaluator", "system:utility")),
                            as_of=str(body.get("as_of")) if body.get("as_of") else None,
                        )
                    )
                    return
                if len(segments) == 5 and segments[:2] == ["api", "fields"] and segments[3:] == ["utility", "assessments"] and self.command == "GET":
                    self._send_json(
                        utility.list_assessments(
                            segments[2],
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "guardrail":
                    if self.command == "POST":
                        body = self._read_json()
                        if "protected" not in body:
                            raise ValueError("protected is required")
                        self._send_json(
                            utility.set_guardrail(
                                segments[2],
                                bool(body["protected"]),
                                reason=str(body.get("reason", "")),
                                evaluator=str(body.get("evaluator", "")),
                            )
                        )
                        return
                    if self.command == "GET":
                        self._send_json(utility.get_guardrail(segments[2]))
                        return
                if self.command == "POST" and path == "/api/governance/utility/scan":
                    body = self._read_json()
                    statuses = body.get("statuses", ["active", "converged"])
                    if not isinstance(statuses, list):
                        raise ValueError("statuses must be an array")
                    self._send_json(
                        utility.assess_registry(
                            statuses=tuple(str(status) for status in statuses),
                            limit_fields=int(body.get("limit_fields", 1000)),
                            offset=int(body.get("offset", 0)),
                            evaluator=str(body.get("evaluator", "system:utility")),
                            as_of=str(body.get("as_of")) if body.get("as_of") else None,
                        )
                    )
                    return
                if len(segments) == 5 and segments[:3] == ["api", "utility", "assessments"] and segments[4] == "apply" and self.command == "POST":
                    body = self._read_json()
                    self._send_json(
                        utility.apply_assessment(
                            segments[3],
                            reason=str(body.get("reason", "")),
                            evaluator=str(body.get("evaluator", "")),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/family-proposals":
                    reviewed_raw = query.get("reviewed", [None])[0]
                    reviewed = None
                    if reviewed_raw is not None:
                        reviewed = str(reviewed_raw).lower() in {"1", "true", "yes"}
                    self._send_json(
                        families.list_proposals(
                            namespace=query.get("namespace", [None])[0],
                            reviewed=reviewed,
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/family-proposals/generate":
                    body = self._read_json()
                    result = families.propose_from_seed(
                        str(body.get("seed_ref", "")),
                        seed_threshold=float(body.get("seed_threshold", 0.78)),
                        min_coherence=float(body.get("min_coherence", 0.72)),
                        max_neighbors=int(body.get("max_neighbors", 24)),
                        max_members=int(body.get("max_members", 8)),
                        namespace=str(body.get("namespace", "global")),
                        evaluator=str(body.get("evaluator", "system:family")),
                    )
                    self._send_json(result)
                    return
                if self.command == "POST" and path == "/api/family-proposals/scan":
                    body = self._read_json()
                    self._send_json(
                        families.scan_registry(
                            namespace=str(body.get("namespace", "global")),
                            seed_threshold=float(body.get("seed_threshold", 0.78)),
                            min_coherence=float(body.get("min_coherence", 0.72)),
                            max_neighbors=int(body.get("max_neighbors", 12)),
                            max_members=int(body.get("max_members", 8)),
                            limit_fields=int(body.get("limit_fields", 10000)),
                            max_proposals=int(body.get("max_proposals", 100)),
                            evaluator=str(body.get("evaluator", "system:family-scan")),
                        )
                    )
                    return
                if len(segments) == 3 and segments[:2] == ["api", "family-proposals"] and self.command == "GET":
                    self._send_json(families.get_proposal(segments[2]))
                    return
                if len(segments) == 4 and segments[:2] == ["api", "family-proposals"] and segments[3] == "review" and self.command == "POST":
                    body = self._read_json()
                    partitions = body.get("partitions")
                    if partitions is not None and not isinstance(partitions, list):
                        raise ValueError("partitions must be an array")
                    self._send_json(
                        families.review_proposal(
                            segments[2],
                            str(body.get("decision", "")),
                            reason=str(body.get("reason", "")),
                            evaluator=str(body.get("evaluator", "")),
                            evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            label=str(body.get("label", "")),
                            partitions=partitions,
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/field-families":
                    self._send_json(
                        families.list_families(
                            namespace=query.get("namespace", [None])[0],
                            family_type=query.get("family_type", [None])[0],
                            status=query.get("status", ["active"])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                    return
                if len(segments) == 3 and segments[:2] == ["api", "field-families"] and self.command == "GET":
                    self._send_json(families.get_family(segments[2]))
                    return
                if self.command == "GET" and path == "/api/proposals":
                    self._send_json(
                        fields.list_proposals(
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/proposals":
                    body = self._read_json()
                    self._send_json(
                        fields.create_proposal(
                            key=str(body.get("key", "")),
                            label=str(body.get("label", "")),
                            reason=str(body.get("reason", "")),
                            value_type=str(body.get("value_type", "text")),
                            description=str(body.get("description", "")),
                            proposed_by=str(body.get("proposed_by", "")),
                            namespace=str(body.get("namespace", "global")),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "proposals"] and segments[3] == "candidates":
                    proposal_id = segments[2]
                    if self.command == "POST":
                        body = self._read_json()
                        self._send_json(
                            semantic.score_proposal(
                                proposal_id,
                                top_k=int(body.get("top_k", 10)),
                                max_candidates=int(body.get("max_candidates", 500)),
                                cross_namespace=bool(body.get("cross_namespace", False)),
                            )
                        )
                        return
                    if self.command == "GET":
                        self._send_json(
                            semantic.list_candidates(
                                source_kind="proposal",
                                source_ref=proposal_id,
                                status=query.get("status", [None])[0],
                                limit=int(query.get("limit", ["100"])[0]),
                            )
                        )
                        return
                if self.command == "GET" and path == "/api/candidates":
                    self._send_json(
                        semantic.list_candidates(
                            source_kind=query.get("source_kind", [None])[0],
                            source_ref=query.get("source_ref", [None])[0],
                            status=query.get("status", [None])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "candidates"] and segments[3] == "review":
                    candidate_id = int(segments[2])
                    if self.command == "POST":
                        body = self._read_json()
                        self._send_json(
                            semantic.review_candidate(
                                candidate_id,
                                str(body.get("decision", "")),
                                reason=str(body.get("reason", "")),
                                evaluator=str(body.get("evaluator", "")),
                                evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            )
                        )
                        return
                    if self.command == "GET":
                        self._send_json(semantic.get_review(candidate_id))
                        return
                if self.command == "POST" and path == "/api/governance/similarity/scan":
                    body = self._read_json()
                    limit_fields = body.get("limit_fields")
                    self._send_json(
                        semantic.scan_field_similarity(
                            namespace=str(body.get("namespace", "global")),
                            threshold=float(body.get("threshold", 0.72)),
                            max_neighbors=int(body.get("max_neighbors", 12)),
                            limit_fields=None if limit_fields is None else int(limit_fields),
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "relations" and self.command == "GET":
                    self._send_json(
                        semantic.list_relations(
                            segments[2],
                            namespace=query.get("namespace", ["global"])[0],
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "proposals"] and segments[3] == "decision":
                    proposal_id = segments[2]
                    if self.command == "POST":
                        body = self._read_json()
                        self._send_json(
                            governance.decide_proposal(
                                proposal_id,
                                str(body.get("decision", "")),
                                reason=str(body.get("reason", "")),
                                evaluator=str(body.get("evaluator", "")),
                                evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            )
                        )
                        return
                    if self.command == "GET":
                        self._send_json(governance.get_proposal_decision(proposal_id))
                        return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "aliases":
                    field_ref = segments[2]
                    if self.command == "POST":
                        body = self._read_json()
                        self._send_json(
                            governance.add_alias(
                                field_ref,
                                str(body.get("alias", "")),
                                namespace=str(body.get("namespace", "global")),
                                reason=str(body.get("reason", "")),
                            )
                        )
                        return
                    if self.command == "GET":
                        self._send_json(
                            governance.list_aliases(
                                field_ref,
                                namespace=query.get("namespace", ["global"])[0],
                            )
                        )
                        return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "definition":
                    if self.command == "POST":
                        body = self._read_json()
                        self._send_json(
                            governance.update_definition(
                                segments[2],
                                label=body.get("label") if "label" in body else None,
                                value_type=body.get("value_type") if "value_type" in body else None,
                                description=body.get("description") if "description" in body else None,
                                reason=str(body.get("reason", "")),
                                evaluator=str(body.get("evaluator", "")),
                                namespace=str(body.get("namespace", "global")),
                            )
                        )
                        return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "versions" and self.command == "GET":
                    self._send_json(
                        governance.list_versions(
                            segments[2],
                            namespace=query.get("namespace", ["global"])[0],
                        )
                    )
                    return
                if len(segments) == 4 and segments[:2] == ["api", "fields"] and segments[3] == "lineage" and self.command == "GET":
                    self._send_json(
                        governance.list_lineage(
                            segments[2],
                            namespace=query.get("namespace", ["global"])[0],
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/governance/merge":
                    body = self._read_json()
                    sources = body.get("sources")
                    if not isinstance(sources, list):
                        raise ValueError("sources must be an array")
                    self._send_json(
                        governance.merge_fields(
                            [str(ref) for ref in sources],
                            str(body.get("target", "")),
                            reason=str(body.get("reason", "")),
                            evaluator=str(body.get("evaluator", "")),
                            evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            namespace=str(body.get("namespace", "global")),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/governance/split":
                    body = self._read_json()
                    children = body.get("children")
                    if not isinstance(children, list):
                        raise ValueError("children must be an array")
                    self._send_json(
                        governance.split_field(
                            str(body.get("source", "")),
                            [str(ref) for ref in children],
                            reason=str(body.get("reason", "")),
                            evaluator=str(body.get("evaluator", "")),
                            evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
                            namespace=str(body.get("namespace", "global")),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/entities":
                    self._send_json(
                        entities.list_entities(
                            limit=int(query.get("limit", ["1000"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                    return
                if self.command == "POST" and path == "/api/entities":
                    body = self._read_json()
                    self._send_json(
                        entities.create_entity(
                            label=str(body.get("label", "")),
                            kind=str(body.get("kind", "record")),
                            entity_id=str(body.get("id", "")).strip() or None,
                        )
                    )
                    return
                if len(segments) == 3 and segments[:2] == ["api", "entities"] and self.command == "GET":
                    self._send_json(entities.get_entity(segments[2]))
                    return
                if len(segments) == 5 and segments[:2] == ["api", "entities"] and segments[3] == "cells":
                    entity_id, field_key = segments[2], segments[4]
                    if self.command == "PUT":
                        body = self._read_json()
                        if "value" not in body:
                            raise ValueError("cell value is required; use DELETE to make a cell blank")
                        self._send_json(
                            entities.set_cell(
                                entity_id,
                                field_key,
                                body["value"],
                                source=str(body.get("source", "")),
                                confidence=body.get("confidence"),
                            )
                        )
                        return
                    if self.command == "DELETE":
                        self._send_json({"deleted": entities.delete_cell(entity_id, field_key)})
                        return
                if self.command == "GET" and path == "/api/search":
                    self._send_json(
                        views.search(
                            query.get("q", [""])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                    return
                if self.command == "GET" and path == "/api/views":
                    self._send_json(views.list_views())
                    return
                if self.command == "POST" and path == "/api/views":
                    body = self._read_json()
                    field_keys = body.get("field_keys")
                    if not isinstance(field_keys, list):
                        raise ValueError("field_keys must be an array")
                    self._send_json(
                        views.create_view(
                            str(body.get("name", "")),
                            [str(key) for key in field_keys],
                            query_text=str(body.get("query_text", "")),
                        )
                    )
                    return
                if len(segments) == 3 and segments[:2] == ["api", "views"] and self.command == "GET":
                    self._send_json(
                        views.get_view_matrix(
                            segments[2],
                            field_offset=int(query.get("field_offset", ["0"])[0]),
                            field_limit=int(query.get("field_limit", ["25"])[0]),
                            entity_offset=int(query.get("entity_offset", ["0"])[0]),
                            entity_limit=int(query.get("entity_limit", ["1000"])[0]),
                        )
                    )
                    return
                self._send_json({"error": "not found"}, 404)
            except KeyError as exc:
                self._send_json({"error": str(exc).strip("'")}, 404)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, 409)
            except Exception as exc:
                self._send_json({"error": f"internal error: {exc}"}, 500)

        def do_GET(self) -> None:
            self._route()

        def do_POST(self) -> None:
            self._route()

        def do_PUT(self) -> None:
            self._route()

        def do_DELETE(self) -> None:
            self._route()

    return ThreadingHTTPServer((host, port), Handler)

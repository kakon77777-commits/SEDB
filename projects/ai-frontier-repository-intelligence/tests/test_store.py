from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from config import FIELD_SPECS, VIEW_SPECS, ProjectConfig  # noqa: E402
from store import ImmutableConflict, RepoIntelStore, StorageError  # noqa: E402
from cli import category_records  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = RepoIntelStore.open(ProjectConfig(database_path=tmp_path / "t.sqlite"))
    s.ensure_schema()
    return s


def test_schema_bootstrap_is_idempotent(store):
    first = store.stats()
    again = store.ensure_schema()
    assert again.fields_created == 0 and again.fields_reused == len(FIELD_SPECS)
    assert again.views_created == 0 and again.views_reused == len(VIEW_SPECS)
    assert store.stats()["fields"] == first["fields"] == len(FIELD_SPECS)
    assert again.integrity == "ok"


def test_taxonomy_seed_replay_is_noop(store):
    r1 = store.write(category_records(), source="seed")
    r2 = store.write(category_records(), source="seed")
    assert r1.created_entities == 38 and r2.created_entities == 0 and r2.unchanged_entities == 38
    ai = store.find("af_category", af_category_slug="artificial-intelligence")
    assert len(ai) == 1 and ai[0]["values"]["af_parent_category_id"] is None
    sub = store.find("af_category", af_parent_category_id="cat_artificial_intelligence")
    assert len(sub) == 9


def test_immutable_kind_rejects_different_values_atomically(store):
    rev = {"entity_id": "rev_x", "kind": "af_repository_revision", "label": "x@abc",
           "values": {"af_repository_id": "repo_x", "af_commit_sha": "abc"}}
    store.write([rev], source="t")
    changed = dict(rev, values={"af_repository_id": "repo_x", "af_commit_sha": "def"})
    other = {"entity_id": "rev_y", "kind": "af_repository_revision", "label": "y", "values": {"af_commit_sha": "y"}}
    with pytest.raises(ImmutableConflict) as exc:
        store.write([other, changed], source="t")
    assert exc.value.differences[0]["field"] == "af_commit_sha"
    assert store.get("rev_y") is None, "batch must roll back atomically"
    assert store.get("rev_x")["values"]["af_commit_sha"] == "abc"


def test_current_kind_updates_in_place_with_provenance(store):
    repo = {"entity_id": "repo_x", "kind": "af_repository", "label": "o/n",
            "values": {"af_full_name": "o/n", "af_repository_status": "active"}}
    store.write([repo], source="github_api")
    r = store.write([dict(repo, values={"af_full_name": "o/n", "af_repository_status": "archived"})], source="github_api", confidence=0.9)
    assert r.updated_entities == 1 and r.written_cells == 1
    ent = store.entities.get_entity("repo_x")
    assert ent["values"]["af_repository_status"] == "archived"
    assert ent["cells"]["af_repository_status"]["source"] == "ai-frontier:github_api"


def test_unknown_field_or_kind_is_rejected(store):
    with pytest.raises(StorageError):
        store.write([{"entity_id": "a", "kind": "af_repository", "label": "a", "values": {"nope": 1}}], source="t")
    with pytest.raises(StorageError):
        store.write([{"entity_id": "a", "kind": "af_nope", "label": "a", "values": {}}], source="t")


def test_provenance_chain_answers_handoff_questions(store):
    store.write([
        {"entity_id": "repo_1", "kind": "af_repository", "label": "o/n", "values": {"af_full_name": "o/n", "af_platform": "github", "af_platform_repository_id": "1", "af_canonical_source_url": "https://github.com/o/n"}},
        {"entity_id": "rev_1", "kind": "af_repository_revision", "label": "o/n@1", "values": {"af_repository_id": "repo_1", "af_commit_sha": "1" * 40, "af_branch": "main"}},
        {"entity_id": "lic_1", "kind": "af_license_record", "label": "lic", "values": {"af_repository_id": "repo_1", "af_revision_id": "rev_1", "af_license_status": "open-source", "af_detected_spdx": "MIT"}},
        {"entity_id": "analysis_1", "kind": "af_analysis_run", "label": "run", "values": {"af_repository_id": "repo_1", "af_revision_id": "rev_1", "af_engine": "RepoLumen", "af_engine_version": "0.10", "af_artifact_sha256": "m" * 64, "af_grounding_bundle_sha256": "g" * 64}},
        {"entity_id": "asset_1", "kind": "af_knowledge_asset", "label": "overview", "values": {"af_repository_id": "repo_1", "af_asset_type": "overview", "af_current_revision_id": "assetrev_1"}},
        {"entity_id": "worker_1", "kind": "af_worker_run", "label": "w", "values": {"af_worker_role": "writer", "af_model_name": "glm-5.3-flash", "af_run_status": "passed"}},
        {"entity_id": "assetrev_1", "kind": "af_asset_revision", "label": "v1", "values": {"af_asset_id": "asset_1", "af_repository_id": "repo_1", "af_repository_revision_id": "rev_1", "af_analysis_run_id": "analysis_1", "af_worker_run_ids": ["worker_1"], "af_canonical_source_sha256": "c" * 64, "af_publication_status": "unpublished"}},
        {"entity_id": "val_1", "kind": "af_validation_run", "label": "v", "values": {"af_target_type": "asset_revision", "af_target_id": "assetrev_1", "af_validator_type": "grounding", "af_validation_status": "passed"}},
    ], source="t")
    chain = store.provenance_chain("assetrev_1")
    assert chain["1_which_repository"]["af_full_name"] == "o/n"
    assert chain["2_which_commit"]["af_commit_sha"] == "1" * 40
    assert chain["3_which_license_state"][0]["af_license_status"] == "open-source"
    assert chain["4_which_analysis"]["af_engine_version"] == "0.10"
    assert chain["5_which_grounding_bundle"]["af_grounding_bundle_sha256"] == "g" * 64
    assert chain["6_which_worker_runs"][0]["af_worker_role"] == "writer"
    assert chain["7_which_validation_runs"][0]["af_validator_type"] == "grounding"
    assert chain["8_canonical_markdown_hash"] == "c" * 64
    assert chain["9_public_url"] is None and chain["10_rollback"].startswith("unpublished")


def test_cli_init_stats_roundtrip(tmp_path):
    env = {"PYTHONPATH": str(PROJECT.parents[1] / "current" / "src") + ";" + str(PROJECT), "PYTHONIOENCODING": "utf-8"}
    import os
    env = {**os.environ, **env}
    db = tmp_path / "c.sqlite"
    out = subprocess.run([sys.executable, str(PROJECT / "cli.py"), "--db", str(db), "init"], capture_output=True, env=env, check=True)
    assert json.loads(out.stdout)["status"] == "ready"
    out = subprocess.run([sys.executable, str(PROJECT / "cli.py"), "--db", str(db), "taxonomy"], capture_output=True, env=env, check=True)
    assert json.loads(out.stdout)["created_entities"] == 38
    out = subprocess.run([sys.executable, str(PROJECT / "cli.py"), "--db", str(db), "stats"], capture_output=True, env=env, check=True)
    assert json.loads(out.stdout)["entities_by_kind"]["af_category"] == 38

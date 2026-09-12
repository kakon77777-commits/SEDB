"""AI Frontier Repository Intelligence — SEDB project contract.

Logical schema `repository-intelligence/v1` from the AI Frontier RKE series
(Paper 03 §134 MVP tables, Paper 04 adapter records, Paper 05 worker provenance,
FINAL_HANDOFF Phase 1). Every table of the logical model becomes one SEDB
entity *kind*; its columns become sparse SEDB fields in one namespace.

The catalog is canonical memory for repository knowledge state. It stores
references and hashes of large artifacts (manifests, grounding bundles,
canonical Markdown), never the artifact bytes themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_NAME = "ai-frontier-repository-intelligence.sqlite"
NAMESPACE = "ai_frontier_repository_intelligence"
SCHEMA_VERSION = "repository-intelligence/v1"
TAXONOMY_VERSION = "v1"
CELL_SOURCE_PREFIX = "ai-frontier"

# Entity kinds (one per logical table). Immutable kinds are append-only:
# a second write with different values is a conflict, an identical write is a
# no-op. Current-state kinds may be updated in place.
IMMUTABLE_KINDS = (
    "af_repository_revision",
    "af_metadata_snapshot",
    "af_license_record",
    "af_analysis_run",
    "af_grounding",
    "af_asset_revision",
    "af_worker_run",
    "af_validation_run",
    "af_publication_event",
)
CURRENT_KINDS = (
    "af_repository",
    "af_repository_alias",
    "af_topic",
    "af_category",
    "af_repository_topic",
    "af_repository_category",
    "af_knowledge_asset",
    "af_freshness_state",
    "af_search_document",
    "af_worker_task",
)
KINDS = IMMUTABLE_KINDS + CURRENT_KINDS

EPISTEMIC_STATES = ("observed", "inferred", "author_claimed", "unresolved")
LICENSE_STATES = ("open-source", "custom", "multiple", "none", "unknown", "unresolved")
ASSET_TYPES = (
    "overview", "getting_started", "architecture", "source_walkthrough",
    "extensions", "faq", "comparison", "weekly_analysis", "release_analysis",
)
ASSET_STATUSES = (
    "draft", "generated", "under_review", "validated", "published",
    "stale", "revalidating", "archived", "rejected",
)
WORKER_ROLES = (
    "writer", "verifier", "critic", "beginner_reviewer", "formatter",
    "taxonomy_classifier", "trend_analyst", "metadata_normalizer",
)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    value_type: str
    description: str

    def as_sedb_spec(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "value_type": self.value_type,
            "description": self.description,
            "namespace": NAMESPACE,
            "status": "active",
        }


@dataclass(frozen=True)
class ViewSpec:
    name: str
    field_keys: tuple[str, ...]
    description: str


def _fields(defs):
    return tuple(FieldSpec(*d) for d in defs)


FIELD_SPECS = _fields((
    # --- shared identity / provenance
    ("af_schema_version", "Schema version", "text", "Logical contract version of the record."),
    ("af_repository_id", "Repository ID", "text", "Stable internal repository identity."),
    ("af_revision_id", "Revision ID", "text", "Repository revision record the row binds to."),
    ("af_analysis_run_id", "Analysis run ID", "text", "Immutable analysis run the row derives from."),
    ("af_provenance_source", "Provenance source", "text", "github_api, repository_file, repolumen, worker, human, system."),
    ("af_observed_at", "Observed at", "text", "UTC timestamp when the source state was observed."),
    ("af_created_at", "Created at", "text", "UTC timestamp when the record was created."),
    ("af_confidence", "Confidence", "number", "0..1 confidence of the assignment or observation; not a probability of truth."),
    # --- repository
    ("af_platform", "Platform", "text", "Source hosting platform, e.g. github."),
    ("af_platform_repository_id", "Platform repository ID", "text", "Stable native platform identifier."),
    ("af_platform_node_id", "Platform node ID", "text", "Platform GraphQL node identifier when available."),
    ("af_owner", "Owner", "text", "Current owner login or organization."),
    ("af_name", "Name", "text", "Current repository name."),
    ("af_full_name", "Full name", "text", "Current owner/name."),
    ("af_canonical_source_url", "Canonical source URL", "text", "Original repository URL; first-level action on every page."),
    ("af_default_branch", "Default branch", "text", "Default branch at observation."),
    ("af_repository_status", "Repository status", "text", "active, archived, renamed, transferred, deleted, unavailable, blocked, unknown."),
    ("af_source_description", "Source description", "text", "Description as published by the repository owner (author-claimed)."),
    ("af_homepage_url", "Homepage URL", "text", "Homepage declared by the repository owner."),
    ("af_is_fork", "Is fork", "boolean", "Whether the platform marks the repository as a fork."),
    ("af_source_created_at", "Source created at", "text", "Repository creation time on the platform."),
    # --- alias
    ("af_alias_owner", "Alias owner", "text", "Historical owner login."),
    ("af_alias_name", "Alias name", "text", "Historical repository name."),
    ("af_alias_url", "Alias URL", "text", "Historical source URL."),
    ("af_valid_from", "Valid from", "text", "Alias validity start."),
    ("af_valid_to", "Valid to", "text", "Alias validity end."),
    # --- revision
    ("af_branch", "Branch", "text", "Branch observed for the commit."),
    ("af_commit_sha", "Commit SHA", "text", "Exact commit identifier."),
    ("af_tag", "Tag", "text", "Tag or release name bound to the commit, if any."),
    ("af_committed_at", "Committed at", "text", "Commit timestamp from the source."),
    # --- metadata snapshot
    ("af_stars", "Stars", "integer", "Stargazer count at observation."),
    ("af_forks", "Forks", "integer", "Fork count at observation."),
    ("af_watchers", "Watchers", "integer", "Subscriber count at observation."),
    ("af_open_issues", "Open issues", "integer", "Open issue and pull request count at observation."),
    ("af_primary_language", "Primary language", "text", "Primary language reported by the platform."),
    ("af_language_bytes", "Language bytes", "json", "Language to byte-count map from the platform."),
    ("af_size_kb", "Size (KB)", "integer", "Repository size reported by the platform."),
    ("af_archived", "Archived", "boolean", "Whether the repository is archived."),
    ("af_pushed_at", "Pushed at", "text", "Last push timestamp reported by the platform."),
    ("af_latest_release_tag", "Latest release tag", "text", "Most recent release tag at observation."),
    ("af_latest_release_at", "Latest release at", "text", "Most recent release publication time."),
    ("af_raw_topics", "Raw topics", "json", "Platform topics exactly as observed."),
    # --- topic / category
    ("af_topic_slug", "Topic slug", "text", "Raw platform topic slug."),
    ("af_topic_source", "Topic source", "text", "Where the topic was observed (github)."),
    ("af_display_name", "Display name", "text", "Human-readable name."),
    ("af_category_slug", "Category slug", "text", "Stable AI Frontier category slug."),
    ("af_parent_category_id", "Parent category", "text", "Parent category entity ID, if any."),
    ("af_taxonomy_version", "Taxonomy version", "text", "Taxonomy version the assignment or category belongs to."),
    ("af_category_status", "Category status", "text", "active, merged, split, retired."),
    ("af_topic_id", "Topic ID", "text", "Topic entity ID."),
    ("af_category_id", "Category ID", "text", "Category entity ID."),
    ("af_assignment_role", "Assignment role", "text", "primary or secondary."),
    ("af_assignment_source", "Assignment source", "text", "rule, model, human, imported, hybrid."),
    ("af_validated", "Validated", "boolean", "Whether a human or policy gate validated the assignment."),
    ("af_evidence_refs", "Evidence refs", "json", "Grounding or metadata references supporting the row."),
    ("af_candidate_categories", "Candidate categories", "json", "Rule-based candidate category slugs offered to the classifier."),
    ("af_uncertainty_note", "Uncertainty note", "text", "Worker-reported uncertainty about the assignment."),
    # --- license
    ("af_detected_spdx", "Detected SPDX", "text", "SPDX identifier detected, if any."),
    ("af_license_status", "License status", "text", "open-source, custom, multiple, none, unknown, unresolved."),
    ("af_license_file_path", "License file path", "text", "Path of the license file inside the repository."),
    ("af_license_file_sha256", "License file SHA-256", "text", "SHA-256 of the license file bytes at the revision."),
    ("af_license_source", "License source", "text", "Observation sources, e.g. github_api+repository_file."),
    ("af_license_policy", "License policy", "text", "Content policy derived from the state (FINAL_HANDOFF license gate)."),
    # --- analysis run
    ("af_engine", "Engine", "text", "Analysis engine name."),
    ("af_engine_version", "Engine version", "text", "Analyzer version."),
    ("af_manifest_schema_version", "Manifest schema version", "text", "Schema version of the produced manifest."),
    ("af_analysis_mode", "Analysis mode", "text", "full, incremental, cache_hit."),
    ("af_external_provider", "External provider", "text", "disabled for production deterministic runs."),
    ("af_analysis_status", "Analysis status", "text", "queued, running, passed, partial, failed, cancelled, superseded."),
    ("af_analysis_config_hash", "Analysis config hash", "text", "SHA-256 over result-affecting analyzer configuration."),
    ("af_artifact_ref", "Artifact ref", "text", "Storage reference of the immutable artifact (relative to the artifact root)."),
    ("af_artifact_sha256", "Artifact SHA-256", "text", "SHA-256 of the canonical artifact bytes."),
    ("af_artifact_bytes", "Artifact bytes", "integer", "Size of the artifact in bytes."),
    ("af_started_at", "Started at", "text", "UTC start time."),
    ("af_completed_at", "Completed at", "text", "UTC completion time."),
    ("af_elapsed_seconds", "Elapsed seconds", "number", "Wall-clock duration."),
    ("af_grounding_bundle_ref", "Grounding bundle ref", "text", "Storage reference of the grounding bundle projection."),
    ("af_grounding_bundle_sha256", "Grounding bundle SHA-256", "text", "SHA-256 of the canonical grounding bundle bytes."),
    ("af_capability_profile", "Capability profile", "json", "Per-language analysis strength bound to the analyzer version."),
    ("af_counts", "Counts", "json", "Object counts produced by the run."),
    ("af_limitations", "Limitations", "json", "Analyzer limitations that apply to this run."),
    # --- grounding
    ("af_grounding_type", "Grounding type", "text", "source_span, symbol, file, import_edge, call_edge, execution_path, repository_metadata, documentation_claim, test_case, architecture_reconstruction, summary_repository, semantic_block, annotation."),
    ("af_origin_engine", "Origin engine", "text", "Engine that produced the local grounding ID."),
    ("af_origin_local_id", "Origin local ID", "text", "Engine-local grounding identifier (not globally unique)."),
    ("af_source_path", "Source path", "text", "Repository-relative path of the evidence."),
    ("af_start_line", "Start line", "integer", "First line of the evidence span."),
    ("af_end_line", "End line", "integer", "Last line of the evidence span."),
    ("af_symbol", "Symbol", "text", "Symbol name the evidence refers to."),
    ("af_content_hash", "Content hash", "text", "SHA-256 of the evidence text, for drift detection."),
    ("af_epistemic_status", "Epistemic status", "text", "observed, inferred, author_claimed, unresolved."),
    ("af_source_provenance", "Source provenance", "text", "Original engine provenance (verified, strongly_inferred, weakly_inferred, author_claim, unresolved)."),
    ("af_summary_text", "Summary text", "text", "Short human-readable text carried by the grounding object."),
    # --- knowledge asset / asset revision
    ("af_asset_type", "Asset type", "text", "overview, getting_started, architecture, source_walkthrough, extensions, faq, comparison, weekly_analysis, release_analysis."),
    ("af_asset_slug", "Asset slug", "text", "Registry-controlled slug."),
    ("af_canonical_path", "Canonical path", "text", "Public canonical path of the asset."),
    ("af_asset_status", "Asset status", "text", "draft, generated, under_review, validated, published, stale, revalidating, archived, rejected."),
    ("af_current_revision_id", "Current revision ID", "text", "Pointer to the current validated asset revision."),
    ("af_asset_id", "Asset ID", "text", "Knowledge asset entity ID."),
    ("af_content_version", "Content version", "integer", "Monotonic content version of the asset."),
    ("af_canonical_source_ref", "Canonical source ref", "text", "Storage reference of the canonical UTF-8 Markdown."),
    ("af_canonical_source_sha256", "Canonical source SHA-256", "text", "SHA-256 of the canonical Markdown bytes."),
    ("af_content_format", "Content format", "text", "markdown."),
    ("af_encoding", "Encoding", "text", "utf-8."),
    ("af_locale", "Locale", "text", "Locale of the canonical source."),
    ("af_selected_grounding_ids", "Selected grounding IDs", "json", "Namespaced grounding IDs the content depends on."),
    ("af_worker_run_ids", "Worker run IDs", "json", "Worker runs that produced or checked the content."),
    ("af_validation_status", "Validation status", "text", "pending, passed, failed."),
    ("af_publication_status", "Publication status", "text", "unpublished, published, unpublished_after_publish."),
    ("af_claim_count", "Claim count", "integer", "Substantive claims in the content."),
    ("af_supported_claim_count", "Supported claim count", "integer", "Claims with valid grounding."),
    ("af_quality_scores", "Quality scores", "json", "Derived quality scores; never a substitute for hard gates."),
    # --- freshness
    ("af_entity_type", "Entity type", "text", "repository or asset."),
    ("af_entity_id", "Entity ID", "text", "Entity the state describes."),
    ("af_last_verified_revision_id", "Last verified revision", "text", "Revision the content was last verified against."),
    ("af_latest_observed_revision_id", "Latest observed revision", "text", "Most recent revision observed for the repository."),
    ("af_freshness", "Freshness", "text", "fresh, changed_unassessed, unaffected, stale_candidate, stale_confirmed, revalidating, fresh_again, unknown."),
    ("af_reason", "Reason", "text", "Why the state holds."),
    ("af_updated_at", "Updated at", "text", "UTC timestamp of the last state change."),
    # --- search document
    ("af_title", "Title", "text", "Search title."),
    ("af_summary", "Summary", "text", "Editorial summary (normalized, not the source description)."),
    ("af_topics", "Topics", "json", "Topic slugs."),
    ("af_categories", "Categories", "json", "Category slugs."),
    ("af_language", "Language", "text", "Primary language."),
    ("af_asset_titles", "Asset titles", "json", "Titles of validated assets."),
    ("af_search_visible", "Search visible", "boolean", "Whether the document is visible in search."),
    ("af_search_schema_version", "Search schema version", "text", "Version of the search projection."),
    ("af_indexed_at", "Indexed at", "text", "When the projection was built."),
    # --- worker task / run
    ("af_worker_role", "Worker role", "text", "writer, verifier, critic, beginner_reviewer, formatter, taxonomy_classifier, trend_analyst, metadata_normalizer."),
    ("af_task_status", "Task status", "text", "queued, leased, running, blocked, retryable, failed, completed, cancelled."),
    ("af_max_attempts", "Max attempts", "integer", "Hard retry ceiling."),
    ("af_attempt_count", "Attempt count", "integer", "Attempts consumed."),
    ("af_prompt_contract_version", "Prompt contract version", "text", "Versioned prompt contract identifier."),
    ("af_prompt_contract_sha256", "Prompt contract SHA-256", "text", "Hash of the prompt contract text."),
    ("af_input_sha256", "Input SHA-256", "text", "Hash of the exact worker input packet."),
    ("af_budget", "Budget", "json", "Cost, latency, token and attempt budget."),
    ("af_macr_task_id", "MACR task ID", "text", "Task identifier inside the MACR runtime."),
    ("af_macr_provider_id", "MACR provider ID", "text", "Provider profile used through MACR."),
    ("af_macr_candidate_id", "MACR candidate ID", "text", "Candidate identifier persisted by MACR."),
    ("af_task_id", "Worker task ID", "text", "Worker task entity ID."),
    ("af_attempt", "Attempt", "integer", "1-based attempt number."),
    ("af_model_provider", "Model provider", "text", "Provider organisation, e.g. zhipu."),
    ("af_model_name", "Model name", "text", "Exact model identifier."),
    ("af_output_ref", "Output ref", "text", "Storage reference of the raw worker output."),
    ("af_output_sha256", "Output SHA-256", "text", "SHA-256 of the raw worker output bytes."),
    ("af_run_status", "Run status", "text", "passed, failed, schema_invalid, needs_more_evidence, provider_failed."),
    ("af_input_tokens", "Input tokens", "integer", "Prompt tokens reported by the provider."),
    ("af_output_tokens", "Output tokens", "integer", "Completion tokens reported by the provider."),
    ("af_reasoning_tokens", "Reasoning tokens", "integer", "Reasoning tokens reported by the provider, if any."),
    ("af_cost_usd", "Cost (USD)", "number", "Known cost in USD; null when unknown."),
    ("af_cost_status", "Cost status", "text", "known, unknown_after_dispatch, estimated."),
    ("af_latency_seconds", "Latency seconds", "number", "Provider round-trip wall-clock seconds."),
    ("af_generation_config", "Generation config", "json", "Temperature, reasoning effort, max tokens, etc."),
    ("af_structured_result", "Structured result", "json", "Bounded structured summary of the worker output."),
    # --- validation / publication
    ("af_target_type", "Target type", "text", "asset_revision, worker_run, grounding_bundle."),
    ("af_target_id", "Target id", "text", "Validated entity ID."),
    ("af_validator_type", "Validator type", "text", "schema, grounding, link, license, markdown, security, revision, policy."),
    ("af_validator_version", "Validator version", "text", "Version of the validator implementation."),
    ("af_details_ref", "Details ref", "text", "Storage reference of the full validator report."),
    ("af_details", "Details", "json", "Bounded validator summary."),
    ("af_event", "Event", "text", "published, updated, unpublished, redirected, archived."),
    ("af_url", "URL", "text", "Public URL affected by the event."),
    ("af_occurred_at", "Occurred at", "text", "UTC event time."),
    ("af_asset_revision_id", "Asset revision ID", "text", "Asset revision entity ID."),
))

VIEW_SPECS = (
    ViewSpec("AI Frontier Repository Registry", ("af_platform", "af_platform_repository_id", "af_full_name", "af_canonical_source_url", "af_default_branch", "af_repository_status", "af_source_description", "af_is_fork"), "Stable repository identity."),
    ViewSpec("AI Frontier Revision Ledger", ("af_repository_id", "af_branch", "af_commit_sha", "af_tag", "af_committed_at", "af_observed_at"), "Immutable repository revisions."),
    ViewSpec("AI Frontier Metadata Snapshots", ("af_repository_id", "af_observed_at", "af_stars", "af_forks", "af_watchers", "af_open_issues", "af_primary_language", "af_pushed_at", "af_latest_release_tag", "af_raw_topics"), "Temporal platform metadata."),
    ViewSpec("AI Frontier Taxonomy", ("af_category_slug", "af_display_name", "af_parent_category_id", "af_taxonomy_version", "af_category_status"), "Versioned category taxonomy."),
    ViewSpec("AI Frontier Category Assignments", ("af_repository_id", "af_category_id", "af_assignment_role", "af_confidence", "af_assignment_source", "af_validated", "af_taxonomy_version", "af_evidence_refs"), "Repository to category assignments with provenance."),
    ViewSpec("AI Frontier License Records", ("af_repository_id", "af_revision_id", "af_detected_spdx", "af_license_status", "af_license_file_path", "af_license_file_sha256", "af_license_source", "af_license_policy", "af_confidence"), "Revision-aware license state."),
    ViewSpec("AI Frontier Analysis Runs", ("af_repository_id", "af_revision_id", "af_engine", "af_engine_version", "af_manifest_schema_version", "af_analysis_mode", "af_external_provider", "af_analysis_status", "af_artifact_sha256", "af_grounding_bundle_sha256", "af_elapsed_seconds"), "Immutable deterministic analysis runs."),
    ViewSpec("AI Frontier Groundings", ("af_analysis_run_id", "af_grounding_type", "af_origin_local_id", "af_source_path", "af_start_line", "af_end_line", "af_symbol", "af_epistemic_status", "af_source_provenance"), "Namespaced grounding catalog."),
    ViewSpec("AI Frontier Knowledge Assets", ("af_repository_id", "af_asset_type", "af_asset_slug", "af_canonical_path", "af_asset_status", "af_current_revision_id"), "Knowledge assets per repository."),
    ViewSpec("AI Frontier Asset Revisions", ("af_asset_id", "af_repository_revision_id", "af_analysis_run_id", "af_grounding_bundle_sha256", "af_content_version", "af_canonical_source_sha256", "af_validation_status", "af_publication_status", "af_claim_count", "af_supported_claim_count"), "Versioned canonical content with dependencies."),
    ViewSpec("AI Frontier Worker Runs", ("af_task_id", "af_worker_role", "af_attempt", "af_model_provider", "af_model_name", "af_macr_candidate_id", "af_input_sha256", "af_output_sha256", "af_run_status", "af_input_tokens", "af_output_tokens", "af_cost_usd", "af_cost_status", "af_latency_seconds"), "Cheap-model worker provenance."),
    ViewSpec("AI Frontier Validation Runs", ("af_target_type", "af_target_id", "af_validator_type", "af_validator_version", "af_validation_status", "af_details", "af_completed_at"), "Validate-before-commit evidence."),
    ViewSpec("AI Frontier Publication Events", ("af_asset_revision_id", "af_event", "af_url", "af_occurred_at"), "Append-only publication history."),
    ViewSpec("AI Frontier Freshness", ("af_entity_type", "af_entity_id", "af_last_verified_revision_id", "af_latest_observed_revision_id", "af_freshness", "af_reason", "af_updated_at"), "Revision-aware freshness state."),
    ViewSpec("AI Frontier Search Documents", ("af_entity_type", "af_entity_id", "af_title", "af_owner", "af_summary", "af_topics", "af_categories", "af_language", "af_asset_titles", "af_search_visible", "af_search_schema_version"), "Rebuildable search projection."),
)

# Field key of the repository revision on an asset revision differs from the
# generic revision field so that referential checks can be explicit.
FIELD_SPECS = FIELD_SPECS + _fields((
    ("af_repository_revision_id", "Repository revision ID", "text", "Repository revision the asset revision is bound to (must belong to the same repository)."),
))

# Taxonomy v1 (Paper 06 §8-11). Slugs are stable; names may be localized later.
TAXONOMY_V1: tuple[tuple[str, str, str | None], ...] = (
    ("artificial-intelligence", "Artificial Intelligence", None),
    ("developer-tools", "Developer Tools", None),
    ("data-and-databases", "Data and Databases", None),
    ("web-and-applications", "Web and Applications", None),
    ("infrastructure-and-cloud", "Infrastructure and Cloud", None),
    ("security", "Security", None),
    ("robotics-and-edge", "Robotics and Edge", None),
    ("multimedia", "Multimedia", None),
    ("scientific-computing", "Scientific Computing", None),
    ("programming-languages", "Programming Languages", None),
    ("operating-systems", "Operating Systems", None),
    ("automation", "Automation", None),
    ("education", "Education", None),
    ("other", "Other", None),
    ("ai-agents", "AI Agents", "artificial-intelligence"),
    ("rag-and-knowledge-systems", "RAG and Knowledge Systems", "artificial-intelligence"),
    ("llm-serving", "LLM Serving", "artificial-intelligence"),
    ("model-training", "Model Training", "artificial-intelligence"),
    ("evaluation", "Evaluation", "artificial-intelligence"),
    ("multimodal-ai", "Multimodal AI", "artificial-intelligence"),
    ("local-ai", "Local AI", "artificial-intelligence"),
    ("ai-infrastructure", "AI Infrastructure", "artificial-intelligence"),
    ("ai-safety", "AI Safety", "artificial-intelligence"),
    ("ide-and-editors", "IDE and Editors", "developer-tools"),
    ("cli-tools", "CLI Tools", "developer-tools"),
    ("testing", "Testing", "developer-tools"),
    ("build-systems", "Build Systems", "developer-tools"),
    ("code-search", "Code Search", "developer-tools"),
    ("code-intelligence", "Code Intelligence", "developer-tools"),
    ("devops-tools", "DevOps Tools", "developer-tools"),
    ("observability", "Observability", "developer-tools"),
    ("relational-databases", "Relational Databases", "data-and-databases"),
    ("vector-databases", "Vector Databases", "data-and-databases"),
    ("search-engines", "Search Engines", "data-and-databases"),
    ("data-pipelines", "Data Pipelines", "data-and-databases"),
    ("data-processing", "Data Processing", "data-and-databases"),
    ("knowledge-graphs", "Knowledge Graphs", "data-and-databases"),
    ("storage-systems", "Storage Systems", "data-and-databases"),
)

# FINAL_HANDOFF license gate.
LICENSE_POLICY = {
    "open-source": "license_specific_policy",
    "custom": "review_required",
    "multiple": "review_required",
    "none": "analysis_only_conservative_source_reuse",
    "unknown": "block_source_reproduction",
    "unresolved": "block_source_reproduction",
}


@dataclass(frozen=True)
class ProjectConfig:
    database_path: Path = PROJECT_ROOT / DATABASE_NAME
    namespace: str = NAMESPACE
    schema_version: str = SCHEMA_VERSION


def default_config() -> ProjectConfig:
    return ProjectConfig()

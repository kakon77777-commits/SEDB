from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from isql_core.semantic_addressing import semantic_address_from_analysis
from isql_core.semantics import SemanticAnalysis, SemanticCoordinateSet
from isql_dsr.branch import NativeBranch
from isql_dsr.branch_history import BranchHistoryLedger
from isql_dsr.canonical import state_hash
from isql_dsr.events import TransitionEvent
from isql_dsr.machine import compile_registered_state, registered_state_hash
from isql_dsr.model import PointValue, SemanticState, SpectrumAxis
from isql_dsr.registry import NativeSymbolRegistry, SymbolNamespace, extend_registry_for_events, extend_registry_for_state
from isql_dsr.runtime import apply_event
from isql_dsr.stream import build_event_stream
from isql_sedb_readonly import SEDBReadOnlyAdapter
from isql_sedb_readonly.active_domain import ActiveDomainBudget, plan_active_domain
from isql_sedb_readonly.history import CheckpointHistoryLedger
from isql_sedb_readonly.sidecar import build_proof_sidecar
from isql_sedb_readonly.world_head import build_world_head_manifest, verify_world_head_manifest
from isql_world_materializer import (
    ExactContentIdentity,
    LocalDirectoryProvider,
    MaterializationRangeReader,
    PhysicalPlacementResolver,
    PlacementCatalog,
    PlacementRecord,
    RangeProofIndex,
    VerifiedRangeFetcher,
    build_materialization_manifest,
    build_range_proof_sidecar,
    verify_materialization_manifest,
)
from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.views import ViewService
from sedb_ral.materialization_anchor import append_materialization_anchor, verify_materialization_anchor
from sedb_ral.world_head_anchor import append_world_head_anchor, verify_world_head_anchor


@dataclass(frozen=True, slots=True)
class SyntheticUniverseConfig:
    object_count: int = 256
    topic_count: int = 16
    active_entities: int = 4
    artifact_size: int = 4096
    chunk_size: int = 256
    range_offset: int = 64
    range_length: int = 64
    seed: str = "d15-universe-v1"

    def __post_init__(self) -> None:
        for name in ("object_count", "topic_count", "active_entities", "artifact_size", "chunk_size", "range_length"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.range_offset) is not int or self.range_offset < 0:
            raise ValueError("range_offset must be nonnegative")
        if self.topic_count > self.object_count:
            raise ValueError("topic_count cannot exceed object_count")
        target_population = (self.object_count + self.topic_count - 1) // self.topic_count
        if self.active_entities > target_population:
            raise ValueError("active_entities exceeds synthetic target-topic population")
        if self.range_offset + self.range_length > self.artifact_size:
            raise ValueError("requested range exceeds artifact size")
        if not self.seed or "\x00" in self.seed:
            raise ValueError("seed must be non-empty")


@dataclass(frozen=True, slots=True)
class SyntheticUniverseReport:
    schema: str
    config: dict[str, object]
    universe_objects: int
    total_universe_bytes: int
    semantic_profile_entries: int
    semantic_probe_count: int
    semantic_probe_ratio: float
    active_entities: int
    active_domain_ratio: float
    selected_cells: int
    materialization_artifacts: int
    requested_payload_bytes: int
    physical_range_bytes: int
    physical_fetch_ratio: float
    range_sidecar_bytes: int
    reservoir_sidecar_bytes: int
    replica_failover_count: int
    world_head_sha256: str
    materialization_manifest_sha256: str
    world_head_ral_anchor_verified: bool
    materialization_ral_anchor_verified: bool
    ral_final_chain_digest: str
    historical_world_head_valid_after_dsr_advance: bool
    historical_world_head_current_after_dsr_advance: bool
    new_world_head_current: bool
    stale_materialization_rejected_for_new_world_head: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

    @property
    def report_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class CountingRangeProvider:
    def __init__(self, provider: LocalDirectoryProvider):
        self.provider = provider
        self.bytes_requested = 0
        self.calls: list[tuple[str, int, int]] = []

    def read_range(self, object_key: str, *, offset: int, length: int, max_bytes: int | None = None) -> bytes:
        self.calls.append((object_key, offset, length))
        self.bytes_requested += length
        return self.provider.read_range(object_key, offset=offset, length=length, max_bytes=max_bytes)


def _artifact_bytes(seed: str, index: int, size: int) -> bytes:
    block = hashlib.sha256(f"{seed}:artifact:{index}".encode("utf-8")).digest()
    return (block * ((size + len(block) - 1) // len(block)))[:size]


def _semantic(topic: str) -> SemanticAnalysis:
    return SemanticAnalysis(
        analyzer_id="d15-synthetic-analyzer",
        analyzer_contract="d15-synthetic-analyzer-contract-v1",
        coordinates=SemanticCoordinateSet(
            summary="synthetic universe entity",
            concepts=(topic,),
            entities=(),
            relations=(),
            claims=(),
            intent=None,
            uncertainty=(),
            tags=(),
            language="en",
        ),
    )


def _ctcl_receipt(suffix: int, recorded_time: str) -> dict[str, object]:
    parsed = datetime.fromisoformat(recorded_time.removesuffix("Z") + "+00:00").astimezone(timezone.utc)
    seconds = calendar.timegm(parsed.utctimetuple())
    ns = seconds * 1_000_000_000 + parsed.microsecond * 1_000
    rfc3339 = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return {
        "schema_version": "0.1",
        "ctcl_instant_id": f"ctcl:instant:00000000-0000-4000-8000-{suffix:012x}",
        "ctcl_call_kind": "registered_anchor",
        "reference": {"timescale": "utc", "value": rfc3339},
        "encodings": {
            "unix_s": f"{ns / 1_000_000_000:.6f}",
            "unix_ms": str(ns // 1_000_000),
            "unix_us": str(ns // 1_000),
            "unix_ns": str(ns),
            "rfc3339": rfc3339,
        },
        "source": {"class": "fixture", "protocol": "https", "provider": "d15-ctcl", "sync_status": "synchronized"},
        "quality": {"precision": "microsecond", "estimated_uncertainty_ns": 0, "synchronized": True, "note": "D15 synthetic anchor"},
        "signature": {
            "alg": "Ed25519",
            "key_id": "d15-fixture-key",
            "signed_fields": "instant_id|unix_ns|timescale",
            "value": "d15-fixture-signature-not-cryptographically-verified",
            "verify_endpoint": "https://example.invalid/verify",
            "verification_status": "not_performed",
        },
        "retrievability": {"expected": True, "status": "unverified", "checked_at_ref": None, "retrieval_evidence_ref": None},
        "service_returned_share_url": f"https://example.invalid/instant/{suffix}",
    }


def _build_dsr_history(root: Path):
    base = SemanticState(identity="world:d15")
    event1 = TransitionEvent(
        event_id="d15-tick-1",
        operation="upsert_axis",
        payload={"axis": SpectrumAxis("tick", "ordinal", PointValue(1)).to_dict()},
        base_revision=0,
        previous_hash=state_hash(base),
    )
    state1 = apply_event(base, event1).state
    event2 = TransitionEvent(
        event_id="d15-tick-2",
        operation="set_context",
        payload={"context": {"phase": "advanced"}},
        base_revision=1,
        previous_hash=state_hash(state1),
    )
    registry = extend_registry_for_state(NativeSymbolRegistry(), base)
    registry = extend_registry_for_events(registry, (event1, event2))
    registry, branch_ref = registry.intern_text(SymbolNamespace.BRANCH_ID, "d15-main")
    native_base = compile_registered_state(base, registry)
    base_hash = registered_state_hash(native_base)
    branch_v1 = NativeBranch(branch_ref, native_base.revision, base_hash, build_event_stream(base, (event1,), registry))
    branch_v2 = NativeBranch(branch_ref, native_base.revision, base_hash, build_event_stream(base, (event1, event2), registry))
    ledger = BranchHistoryLedger(root / "dsr-branch-history.sqlite3")
    first = ledger.publish_branch(native_base, branch_v1, registry, expected_head_sha256=None)
    return ledger, native_base, registry, branch_v2, first


def _prepare_sedb(root: Path, config: SyntheticUniverseConfig):
    db_path = root / "sedb.sqlite3"
    db = Database(db_path)
    fields = FieldService(db)
    entities = EntityService(db)
    views = ViewService(db)
    for key in ("topic", "ordinal", "artifact_ref"):
        fields.create_field(key=key, label=key.title(), value_type="json")
    analyses: dict[str, SemanticAnalysis] = {}
    good_root = root / "provider-good"
    bad_root = root / "provider-bad"
    (good_root / "objects").mkdir(parents=True)
    (bad_root / "objects").mkdir(parents=True)
    total_bytes = 0
    for index in range(config.object_count):
        entity_id = f"Entity-{index:06d}"
        topic = f"topic-{index % config.topic_count:03d}"
        artifact_ref = f"artifact:{entity_id}"
        object_key = f"objects/{entity_id}.bin"
        entities.create_entity(label=entity_id, kind="synthetic", entity_id=entity_id)
        entities.set_cell(entity_id, "topic", topic, source="d15")
        entities.set_cell(entity_id, "ordinal", index, source="d15")
        entities.set_cell(entity_id, "artifact_ref", artifact_ref, source="d15")
        analyses[entity_id] = _semantic(topic)
        content = _artifact_bytes(config.seed, index, config.artifact_size)
        (good_root / object_key).write_bytes(content)
        total_bytes += len(content)
    view = views.create_view("d15-active-view", ["topic", "ordinal", "artifact_ref"], query_text="synthetic distributed universe active domain")
    return db_path, view, analyses, good_root, bad_root, total_bytes


def run_synthetic_acceptance(root: str | Path, config: SyntheticUniverseConfig = SyntheticUniverseConfig()) -> SyntheticUniverseReport:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    db_path, view, analyses, good_root, bad_root, total_bytes = _prepare_sedb(root, config)
    adapter = SEDBReadOnlyAdapter(db_path)
    semantic_index = adapter.build_semantic_index(analyses)
    query = semantic_address_from_analysis(_semantic("topic-000"))
    target_population = sum(1 for index in range(config.object_count) if index % config.topic_count == 0)
    plan = plan_active_domain(
        adapter,
        query,
        semantic_index,
        view_id=view["id"],
        budget=ActiveDomainBudget(
            max_candidate_scan=max(config.active_entities, target_population),
            max_entities=config.active_entities,
            max_fields=3,
            max_cells=config.active_entities * 3,
        ),
    )
    if len(plan.selected_entities) != config.active_entities:
        raise RuntimeError("D15_ACTIVE_DOMAIN_SIZE_UNEXPECTED")

    reservoir_sidecar = root / "sedb-proof-sidecar.sqlite3"
    reservoir_build = build_proof_sidecar(adapter, reservoir_sidecar)
    reservoir_history = CheckpointHistoryLedger(root / "sedb-history.sqlite3", create=True)
    reservoir_record = reservoir_history.append(
        reservoir_build.checkpoint,
        stream_id="world:d15",
        observed_at="2026-09-15T10:00:00Z",
        authority_ref="authority:d15-synthetic",
        expected_head_sha256=None,
        note="D15 synthetic reservoir checkpoint",
    )

    dsr_ledger, native_base, registry, branch_v2, branch_first = _build_dsr_history(root)
    world_head = build_world_head_manifest(world_id="world:d15", reservoir_record=reservoir_record, dsr_record=branch_first.record)
    initial_world_verification = verify_world_head_manifest(
        world_head,
        expected_manifest_sha256=world_head.manifest_sha256(),
        reservoir_ledger=reservoir_history,
        dsr_ledger=dsr_ledger,
    )
    if not initial_world_verification.current:
        raise RuntimeError("D15_WORLD_HEAD_NOT_CURRENT")

    catalog = PlacementCatalog(root / "placement.sqlite3")
    proof_indexes: dict[str, RangeProofIndex] = {}
    commitments = {}
    selected_ids = [entity.exact.entity_id for entity in plan.selected_entities]
    selected_index_by_id = {f"Entity-{index:06d}": index for index in range(config.object_count)}
    for ordinal, entity_id in enumerate(selected_ids):
        index = selected_index_by_id[entity_id]
        content = _artifact_bytes(config.seed, index, config.artifact_size)
        identity = ExactContentIdentity("sha256", hashlib.sha256(content).hexdigest())
        artifact_ref = f"artifact:{entity_id}"
        object_key = f"objects/{entity_id}.bin"
        sidecar_path = root / "range-proofs" / f"{entity_id}.sqlite3"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        commitment = build_range_proof_sidecar(good_root / object_key, sidecar_path, identity, chunk_size=config.chunk_size)
        commitments[artifact_ref] = commitment
        proof_indexes[artifact_ref] = RangeProofIndex(sidecar_path)
        catalog.register(PlacementRecord(identity=identity, placement_id=f"good:{entity_id}", provider_id="good", object_key=object_key, size_bytes=config.artifact_size, region="region-good", tier="hot", priority=10))
        if ordinal == 0:
            corrupted = bytearray(content)
            corrupted[min(config.range_offset, len(corrupted) - 1)] ^= 0xFF
            (bad_root / object_key).write_bytes(bytes(corrupted))
            catalog.register(PlacementRecord(identity=identity, placement_id=f"bad:{entity_id}", provider_id="bad", object_key=object_key, size_bytes=config.artifact_size, region="region-bad", tier="hot", priority=0))

    materialization = build_materialization_manifest(
        world_id=world_head.world_id,
        world_head_manifest_sha256=world_head.manifest_sha256(),
        profile_id="d15-synthetic-materialization-v1",
        commitments=commitments,
    )

    ral_root = root / "ral-history"
    world_anchor = append_world_head_anchor(
        ral_root,
        world_head.to_dict(),
        _ctcl_receipt(1, "2026-09-15T10:01:00Z"),
        event_id="evt_d15_world_head_001",
        ledger_id="ledger:d15/world",
        expected_previous_chain_digest=None,
        expected_manifest_sha256=world_head.manifest_sha256(),
    )
    materialization_anchor = append_materialization_anchor(
        ral_root,
        materialization.to_dict(),
        _ctcl_receipt(2, "2026-09-15T10:02:00Z"),
        event_id="evt_d15_materialization_001",
        ledger_id="ledger:d15/world",
        causal_parent_ids=(world_anchor.event_id,),
        expected_previous_chain_digest=world_anchor.chain_digest,
        expected_manifest_sha256=materialization.manifest_sha256,
    )
    world_anchor_verification = verify_world_head_anchor(
        ral_root,
        expected_ral_head=materialization_anchor.chain_digest,
        manifest=world_head.to_dict(),
        expected_manifest_sha256=world_head.manifest_sha256(),
    )
    materialization_anchor_verification = verify_materialization_anchor(
        ral_root,
        expected_ral_head=materialization_anchor.chain_digest,
        manifest=materialization.to_dict(),
        expected_manifest_sha256=materialization.manifest_sha256,
    )
    if not world_anchor_verification.valid or not materialization_anchor_verification.valid:
        raise RuntimeError("D15_EXTERNAL_ANCHOR_VERIFICATION_FAILED")

    good_counter = CountingRangeProvider(LocalDirectoryProvider(good_root))
    bad_counter = CountingRangeProvider(LocalDirectoryProvider(bad_root))
    reader = MaterializationRangeReader(
        materialization,
        expected_manifest_sha256=materialization.manifest_sha256,
        expected_world_head_manifest_sha256=world_head.manifest_sha256(),
        proof_indexes=proof_indexes,
        range_fetcher=VerifiedRangeFetcher(PhysicalPlacementResolver(catalog), {"good": good_counter, "bad": bad_counter}),
    )
    requested_payload_bytes = 0
    failovers = 0
    for entity_id in selected_ids:
        result = reader.fetch_range(f"artifact:{entity_id}", offset=config.range_offset, length=config.range_length)
        index = selected_index_by_id[entity_id]
        expected_content = _artifact_bytes(config.seed, index, config.artifact_size)
        if result.content != expected_content[config.range_offset : config.range_offset + config.range_length]:
            raise RuntimeError("D15_FETCHED_BYTES_MISMATCH")
        requested_payload_bytes += len(result.content)
        if len(result.attempted_placement_ids) > 1:
            failovers += 1

    physical_range_bytes = good_counter.bytes_requested + bad_counter.bytes_requested
    range_sidecar_bytes = sum(index.path.stat().st_size for index in proof_indexes.values())

    second = dsr_ledger.publish_branch(native_base, branch_v2, registry, expected_head_sha256=branch_first.record.record_sha256)
    historical = verify_world_head_manifest(
        world_head,
        expected_manifest_sha256=world_head.manifest_sha256(),
        reservoir_ledger=reservoir_history,
        dsr_ledger=dsr_ledger,
    )
    new_world_head = build_world_head_manifest(world_id="world:d15", reservoir_record=reservoir_record, dsr_record=second.record)
    new_verification = verify_world_head_manifest(
        new_world_head,
        expected_manifest_sha256=new_world_head.manifest_sha256(),
        reservoir_ledger=reservoir_history,
        dsr_ledger=dsr_ledger,
    )
    stale_materialization = verify_materialization_manifest(
        materialization,
        expected_manifest_sha256=materialization.manifest_sha256,
        expected_world_head_manifest_sha256=new_world_head.manifest_sha256(),
        proof_indexes=proof_indexes,
    )

    return SyntheticUniverseReport(
        schema="isql-distributed-universe-acceptance/v0.1",
        config=asdict(config),
        universe_objects=config.object_count,
        total_universe_bytes=total_bytes,
        semantic_profile_entries=plan.profile_entry_count,
        semantic_probe_count=plan.probe_count,
        semantic_probe_ratio=(plan.probe_count / plan.profile_entry_count if plan.profile_entry_count else 0.0),
        active_entities=len(plan.selected_entities),
        active_domain_ratio=len(plan.selected_entities) / config.object_count,
        selected_cells=plan.selected_cell_count,
        materialization_artifacts=len(materialization.artifacts),
        requested_payload_bytes=requested_payload_bytes,
        physical_range_bytes=physical_range_bytes,
        physical_fetch_ratio=physical_range_bytes / total_bytes if total_bytes else 0.0,
        range_sidecar_bytes=range_sidecar_bytes,
        reservoir_sidecar_bytes=reservoir_sidecar.stat().st_size,
        replica_failover_count=failovers,
        world_head_sha256=world_head.manifest_sha256(),
        materialization_manifest_sha256=materialization.manifest_sha256,
        world_head_ral_anchor_verified=world_anchor_verification.valid,
        materialization_ral_anchor_verified=materialization_anchor_verification.valid,
        ral_final_chain_digest=materialization_anchor.chain_digest,
        historical_world_head_valid_after_dsr_advance=historical.valid,
        historical_world_head_current_after_dsr_advance=historical.current,
        new_world_head_current=new_verification.current,
        stale_materialization_rejected_for_new_world_head=not stale_materialization.world_head_binding_valid,
    )


def acceptance_passes(report: SyntheticUniverseReport) -> bool:
    return (
        report.universe_objects > report.active_entities > 0
        and 0.0 < report.semantic_probe_ratio < 1.0
        and 0.0 < report.active_domain_ratio < 0.25
        and report.physical_range_bytes < report.total_universe_bytes
        and report.requested_payload_bytes <= report.physical_range_bytes
        and report.replica_failover_count >= 1
        and report.world_head_ral_anchor_verified
        and report.materialization_ral_anchor_verified
        and report.ral_final_chain_digest.startswith("sha256:sedb-ral-chain-v1:")
        and report.historical_world_head_valid_after_dsr_advance
        and not report.historical_world_head_current_after_dsr_advance
        and report.new_world_head_current
        and report.stale_materialization_rejected_for_new_world_head
    )

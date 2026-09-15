from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .adapter import SEDBReadOnlyAdapterError
from .history import CheckpointHistoryLedger, CheckpointHistoryRecord

WORLD_HEAD_MANIFEST_SCHEMA = "isql-world-head-manifest/v0.1"


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_NOT_CANONICAL_JSON") from exc


def _identity_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or value != value.strip():
        raise SEDBReadOnlyAdapterError(code)
    return value


def _hex64(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise SEDBReadOnlyAdapterError(code)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise SEDBReadOnlyAdapterError(code) from exc
    if len(raw) != 32 or value.lower() != value:
        raise SEDBReadOnlyAdapterError(code)
    return value


def _load_dsr_history_types():
    try:
        from isql_dsr.branch_history import (
            BRANCH_HISTORY_KIND_HEAD,
            BRANCH_HISTORY_KIND_MERGE,
            BranchHistoryLedger,
            BranchHistoryRecord,
        )
    except ImportError as exc:
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_RUNTIME_REQUIRED") from exc
    return BRANCH_HISTORY_KIND_HEAD, BRANCH_HISTORY_KIND_MERGE, BranchHistoryLedger, BranchHistoryRecord


@dataclass(frozen=True, slots=True)
class WorldHeadManifest:
    world_id: str
    reservoir_stream_id: str
    reservoir_sequence: int
    reservoir_record_sha256: str
    reservoir_checkpoint_sha256: str
    dsr_record_sha256: str
    dsr_record_kind: str
    dsr_base_revision: int
    dsr_base_hash: str
    dsr_result_state_hash: str
    dsr_branch_ref: int | None
    dsr_source_branch_refs: tuple[int, ...]
    dsr_source_head_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", _identity_text(self.world_id, "WORLD_HEAD_WORLD_ID_INVALID"))
        object.__setattr__(
            self,
            "reservoir_stream_id",
            _identity_text(self.reservoir_stream_id, "WORLD_HEAD_RESERVOIR_STREAM_INVALID"),
        )
        if not isinstance(self.reservoir_sequence, int) or isinstance(self.reservoir_sequence, bool) or self.reservoir_sequence < 0:
            raise SEDBReadOnlyAdapterError("WORLD_HEAD_RESERVOIR_SEQUENCE_INVALID")
        for name in (
            "reservoir_record_sha256",
            "reservoir_checkpoint_sha256",
            "dsr_record_sha256",
            "dsr_base_hash",
            "dsr_result_state_hash",
        ):
            object.__setattr__(self, name, _hex64(getattr(self, name), f"WORLD_HEAD_{name.upper()}_INVALID"))
        if self.dsr_record_kind not in {"branch_head", "merge_commit"}:
            raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_RECORD_KIND_INVALID")
        if not isinstance(self.dsr_base_revision, int) or isinstance(self.dsr_base_revision, bool) or self.dsr_base_revision < 0:
            raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_BASE_REVISION_INVALID")

        refs = tuple(self.dsr_source_branch_refs)
        heads = tuple(self.dsr_source_head_sha256s)
        if self.dsr_record_kind == "branch_head":
            if not isinstance(self.dsr_branch_ref, int) or isinstance(self.dsr_branch_ref, bool) or self.dsr_branch_ref <= 0:
                raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_BRANCH_REF_INVALID")
            if refs or heads:
                raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_BRANCH_SOURCES_INVALID")
        else:
            if self.dsr_branch_ref is not None:
                raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_MERGE_BRANCH_REF_INVALID")
            if len(refs) < 2 or len(refs) != len(heads) or tuple(sorted(refs)) != refs or len(set(refs)) != len(refs):
                raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_MERGE_SOURCES_INVALID")
            object.__setattr__(
                self,
                "dsr_source_head_sha256s",
                tuple(_hex64(value, "WORLD_HEAD_DSR_SOURCE_HEAD_INVALID") for value in heads),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WORLD_HEAD_MANIFEST_SCHEMA,
            "world_id": self.world_id,
            "reservoir": {
                "stream_id": self.reservoir_stream_id,
                "sequence": self.reservoir_sequence,
                "record_sha256": self.reservoir_record_sha256,
                "checkpoint_sha256": self.reservoir_checkpoint_sha256,
            },
            "dsr": {
                "record_sha256": self.dsr_record_sha256,
                "record_kind": self.dsr_record_kind,
                "base_revision": self.dsr_base_revision,
                "base_hash": self.dsr_base_hash,
                "result_state_hash": self.dsr_result_state_hash,
                "branch_ref": self.dsr_branch_ref,
                "source_branch_refs": list(self.dsr_source_branch_refs),
                "source_head_sha256s": list(self.dsr_source_head_sha256s),
            },
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class WorldHeadVerification:
    world_id: str
    manifest_sha256: str
    manifest_hash_valid: bool
    reservoir_record_valid: bool
    reservoir_is_head: bool
    dsr_record_valid: bool
    dsr_is_current: bool

    @property
    def valid(self) -> bool:
        return self.manifest_hash_valid and self.reservoir_record_valid and self.dsr_record_valid

    @property
    def current(self) -> bool:
        return self.valid and self.reservoir_is_head and self.dsr_is_current


def build_world_head_manifest(
    *,
    world_id: str,
    reservoir_record: CheckpointHistoryRecord,
    dsr_record: Any,
) -> WorldHeadManifest:
    if not isinstance(reservoir_record, CheckpointHistoryRecord):
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_RESERVOIR_RECORD_REQUIRED")
    head_kind, merge_kind, _, record_type = _load_dsr_history_types()
    if not isinstance(dsr_record, record_type):
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_RECORD_REQUIRED")

    if dsr_record.record_kind == head_kind:
        branch_ref = dsr_record.branch_ref
        source_refs: tuple[int, ...] = ()
        source_heads: tuple[str, ...] = ()
    elif dsr_record.record_kind == merge_kind:
        branch_ref = None
        source_refs = tuple(dsr_record.source_branch_refs)
        source_heads = tuple(dsr_record.source_head_sha256s)
    else:
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_RECORD_KIND_INVALID")

    return WorldHeadManifest(
        world_id=world_id,
        reservoir_stream_id=reservoir_record.stream_id,
        reservoir_sequence=reservoir_record.sequence,
        reservoir_record_sha256=reservoir_record.record_sha256(),
        reservoir_checkpoint_sha256=reservoir_record.checkpoint_sha256,
        dsr_record_sha256=dsr_record.record_sha256,
        dsr_record_kind=dsr_record.record_kind,
        dsr_base_revision=dsr_record.base_revision,
        dsr_base_hash=dsr_record.base_hash,
        dsr_result_state_hash=dsr_record.result_state_hash,
        dsr_branch_ref=branch_ref,
        dsr_source_branch_refs=source_refs,
        dsr_source_head_sha256s=source_heads,
    )


def verify_world_head_manifest(
    manifest: WorldHeadManifest,
    *,
    expected_manifest_sha256: str,
    reservoir_ledger: CheckpointHistoryLedger,
    dsr_ledger: Any,
) -> WorldHeadVerification:
    if not isinstance(manifest, WorldHeadManifest):
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_MANIFEST_REQUIRED")
    expected = _hex64(expected_manifest_sha256, "WORLD_HEAD_EXPECTED_HASH_INVALID")
    actual_manifest_hash = manifest.manifest_sha256()
    manifest_hash_valid = actual_manifest_hash == expected

    reservoir_record_valid = False
    reservoir_is_head = False
    try:
        records = reservoir_ledger.records(manifest.reservoir_stream_id)
        for record in records:
            if record.record_sha256() != manifest.reservoir_record_sha256:
                continue
            reservoir_record_valid = (
                record.sequence == manifest.reservoir_sequence
                and record.checkpoint_sha256 == manifest.reservoir_checkpoint_sha256
            )
            break
        head = reservoir_ledger.head(manifest.reservoir_stream_id)
        reservoir_is_head = (
            reservoir_record_valid
            and head is not None
            and head.record_sha256() == manifest.reservoir_record_sha256
        )
    except Exception:
        reservoir_record_valid = False
        reservoir_is_head = False

    head_kind, merge_kind, ledger_type, _ = _load_dsr_history_types()
    if not isinstance(dsr_ledger, ledger_type):
        raise SEDBReadOnlyAdapterError("WORLD_HEAD_DSR_LEDGER_REQUIRED")

    dsr_record_valid = False
    dsr_is_current = False
    try:
        record = dsr_ledger.read_record(manifest.dsr_record_sha256)
        dsr_record_valid = (
            record.record_kind == manifest.dsr_record_kind
            and record.base_revision == manifest.dsr_base_revision
            and record.base_hash == manifest.dsr_base_hash
            and record.result_state_hash == manifest.dsr_result_state_hash
            and record.branch_ref == manifest.dsr_branch_ref
            and tuple(record.source_branch_refs) == manifest.dsr_source_branch_refs
            and tuple(record.source_head_sha256s) == manifest.dsr_source_head_sha256s
        )
        if dsr_record_valid and record.record_kind == head_kind:
            dsr_is_current = dsr_ledger.current_head_sha256(record.branch_ref) == manifest.dsr_record_sha256
        elif dsr_record_valid and record.record_kind == merge_kind:
            dsr_is_current = all(
                dsr_ledger.current_head_sha256(ref) == head_sha
                for ref, head_sha in zip(record.source_branch_refs, record.source_head_sha256s)
            )
    except Exception:
        dsr_record_valid = False
        dsr_is_current = False

    return WorldHeadVerification(
        world_id=manifest.world_id,
        manifest_sha256=actual_manifest_hash,
        manifest_hash_valid=manifest_hash_valid,
        reservoir_record_valid=reservoir_record_valid,
        reservoir_is_head=reservoir_is_head,
        dsr_record_valid=dsr_record_valid,
        dsr_is_current=dsr_is_current,
    )

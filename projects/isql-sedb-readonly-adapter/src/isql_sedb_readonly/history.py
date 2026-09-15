from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .adapter import SEDBReadOnlyAdapterError
from .sidecar import (
    ProofSidecarCheckpoint,
    SidecarProofEnvelope,
    verify_sidecar_proof_envelope,
)


CHECKPOINT_HISTORY_SCHEMA = "isql-sedb.checkpoint-history/v0.1"
CHECKPOINT_RECORD_SCHEMA = "isql-sedb.checkpoint-record/v0.1"


_HISTORY_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE checkpoint_records (
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    record_sha256 TEXT NOT NULL UNIQUE,
    parent_record_sha256 TEXT,
    checkpoint_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY(stream_id, sequence)
);

CREATE INDEX idx_checkpoint_records_stream_head
ON checkpoint_records(stream_id, sequence DESC);
CREATE INDEX idx_checkpoint_records_checkpoint
ON checkpoint_records(stream_id, checkpoint_sha256, sequence);

CREATE TRIGGER checkpoint_records_no_update
BEFORE UPDATE ON checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'checkpoint history records are append-only');
END;

CREATE TRIGGER checkpoint_records_no_delete
BEFORE DELETE ON checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'checkpoint history records are append-only');
END;
"""


class CheckpointHistoryConflict(SEDBReadOnlyAdapterError):
    pass


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
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_NOT_CANONICAL_JSON") from exc


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
    if len(raw) != 32:
        raise SEDBReadOnlyAdapterError(code)
    return value.lower()


def _utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_TIMESTAMP_INVALID")
    token = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError as exc:
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_TIMESTAMP_TZ_REQUIRED")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return canonical.replace("+00:00", "Z")


def _checkpoint_from_dict(value: object) -> ProofSidecarCheckpoint:
    if not isinstance(value, dict) or value.get("schema") != "isql-sedb.proof-sidecar-checkpoint/v0.1":
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_CHECKPOINT_SCHEMA_INVALID")
    return ProofSidecarCheckpoint(
        field_registry_commitment_sha256=str(value["field_registry_commitment_sha256"]),
        entity_root_sha256=str(value["entity_root_sha256"]),
        entity_count=int(value["entity_count"]),
    )


@dataclass(frozen=True, slots=True)
class CheckpointHistoryRecord:
    stream_id: str
    sequence: int
    parent_record_sha256: str | None
    checkpoint: ProofSidecarCheckpoint
    checkpoint_sha256: str
    observed_at: str
    authority_ref: str
    note: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stream_id",
            _identity_text(self.stream_id, "CHECKPOINT_HISTORY_STREAM_ID_INVALID"),
        )
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_SEQUENCE_INVALID")
        if self.parent_record_sha256 is not None:
            object.__setattr__(
                self,
                "parent_record_sha256",
                _hex64(
                    self.parent_record_sha256,
                    "CHECKPOINT_HISTORY_PARENT_HASH_INVALID",
                ),
            )
        if not isinstance(self.checkpoint, ProofSidecarCheckpoint):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_CHECKPOINT_REQUIRED")
        object.__setattr__(
            self,
            "checkpoint_sha256",
            _hex64(self.checkpoint_sha256, "CHECKPOINT_HISTORY_CHECKPOINT_HASH_INVALID"),
        )
        if self.checkpoint.checkpoint_sha256() != self.checkpoint_sha256:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_CHECKPOINT_HASH_MISMATCH")
        object.__setattr__(self, "observed_at", _utc_timestamp(self.observed_at))
        object.__setattr__(
            self,
            "authority_ref",
            _identity_text(self.authority_ref, "CHECKPOINT_HISTORY_AUTHORITY_REF_INVALID"),
        )
        if not isinstance(self.note, str) or "\x00" in self.note:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_NOTE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": CHECKPOINT_RECORD_SCHEMA,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "parent_record_sha256": self.parent_record_sha256,
            "checkpoint": self.checkpoint.to_dict(),
            "checkpoint_sha256": self.checkpoint_sha256,
            "observed_at": self.observed_at,
            "authority_ref": self.authority_ref,
            "note": self.note,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def record_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> "CheckpointHistoryRecord":
        if not isinstance(value, dict) or value.get("schema") != CHECKPOINT_RECORD_SCHEMA:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_RECORD_SCHEMA_INVALID")
        return cls(
            stream_id=str(value["stream_id"]),
            sequence=int(value["sequence"]),
            parent_record_sha256=(
                None
                if value.get("parent_record_sha256") is None
                else str(value["parent_record_sha256"])
            ),
            checkpoint=_checkpoint_from_dict(value["checkpoint"]),
            checkpoint_sha256=str(value["checkpoint_sha256"]),
            observed_at=str(value["observed_at"]),
            authority_ref=str(value["authority_ref"]),
            note=str(value.get("note") or ""),
        )


@dataclass(frozen=True, slots=True)
class CheckpointStreamVerification:
    stream_id: str
    valid: bool
    record_count: int
    head_record_sha256: str | None
    head_checkpoint_sha256: str | None
    authority_ref: str | None


@dataclass(frozen=True, slots=True)
class CheckpointHeadVerification:
    stream_id: str
    chain_valid: bool
    checkpoint_is_head: bool
    proof_valid: bool
    head_record_sha256: str | None
    head_checkpoint_sha256: str | None
    authority_ref: str | None

    @property
    def valid(self) -> bool:
        return self.chain_valid and self.checkpoint_is_head and self.proof_valid


class CheckpointHistoryLedger:
    def __init__(self, path: str | Path, *, create: bool = False, overwrite: bool = False):
        target = Path(path).expanduser().resolve()
        if create:
            if target.exists():
                if not overwrite:
                    raise FileExistsError(target)
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(target) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_HISTORY_DDL)
                conn.execute(
                    "INSERT INTO metadata(key,value_json) VALUES('schema',?)",
                    (_canonical_json_bytes({"schema": CHECKPOINT_HISTORY_SCHEMA}).decode("utf-8"),),
                )
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_SQLITE_INTEGRITY_FAILED")
        elif not target.is_file():
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_FILE_REQUIRED")
        self.path = target
        with self._connect() as conn:
            self._require_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not {"metadata", "checkpoint_records"}.issubset(tables):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_REQUIRED_SCHEMA_MISSING")
        row = conn.execute("SELECT value_json FROM metadata WHERE key='schema'").fetchone()
        if row is None:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_SCHEMA_METADATA_MISSING")
        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError as exc:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_SCHEMA_METADATA_INVALID") from exc
        if value != {"schema": CHECKPOINT_HISTORY_SCHEMA}:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_SCHEMA_VERSION_INVALID")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> CheckpointHistoryRecord:
        try:
            value = json.loads(row["record_json"])
        except json.JSONDecodeError as exc:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_RECORD_JSON_INVALID") from exc
        record = CheckpointHistoryRecord.from_dict(value)
        if record.record_sha256() != str(row["record_sha256"]):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_RECORD_HASH_MISMATCH")
        if record.checkpoint_sha256 != str(row["checkpoint_sha256"]):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_ROW_CHECKPOINT_MISMATCH")
        if record.stream_id != str(row["stream_id"]) or record.sequence != int(row["sequence"]):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_ROW_IDENTITY_MISMATCH")
        row_parent = None if row["parent_record_sha256"] is None else str(row["parent_record_sha256"])
        if record.parent_record_sha256 != row_parent:
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_ROW_PARENT_MISMATCH")
        return record

    def head(self, stream_id: str) -> CheckpointHistoryRecord | None:
        stream_id = _identity_text(stream_id, "CHECKPOINT_HISTORY_STREAM_ID_INVALID")
        with self._connect() as conn:
            self._require_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM checkpoint_records
                WHERE stream_id=? ORDER BY sequence DESC LIMIT 1
                """,
                (stream_id,),
            ).fetchone()
        return None if row is None else self._record_from_row(row)

    def append(
        self,
        checkpoint: ProofSidecarCheckpoint,
        *,
        stream_id: str,
        observed_at: str,
        authority_ref: str,
        expected_head_sha256: str | None,
        note: str = "",
    ) -> CheckpointHistoryRecord:
        if not isinstance(checkpoint, ProofSidecarCheckpoint):
            raise SEDBReadOnlyAdapterError("CHECKPOINT_HISTORY_CHECKPOINT_REQUIRED")
        stream_id = _identity_text(stream_id, "CHECKPOINT_HISTORY_STREAM_ID_INVALID")
        authority_ref = _identity_text(
            authority_ref,
            "CHECKPOINT_HISTORY_AUTHORITY_REF_INVALID",
        )
        observed_at = _utc_timestamp(observed_at)
        if expected_head_sha256 is not None:
            expected_head_sha256 = _hex64(
                expected_head_sha256,
                "CHECKPOINT_HISTORY_EXPECTED_HEAD_INVALID",
            )

        conn = self._connect()
        try:
            self._require_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM checkpoint_records
                WHERE stream_id=? ORDER BY sequence DESC LIMIT 1
                """,
                (stream_id,),
            ).fetchone()
            head = None if row is None else self._record_from_row(row)
            actual_head = None if head is None else head.record_sha256()
            if actual_head != expected_head_sha256:
                raise CheckpointHistoryConflict(
                    f"expected head {expected_head_sha256!r}, actual head {actual_head!r}"
                )
            sequence = 0 if head is None else head.sequence + 1
            record = CheckpointHistoryRecord(
                stream_id=stream_id,
                sequence=sequence,
                parent_record_sha256=actual_head,
                checkpoint=checkpoint,
                checkpoint_sha256=checkpoint.checkpoint_sha256(),
                observed_at=observed_at,
                authority_ref=authority_ref,
                note=note,
            )
            record_hash = record.record_sha256()
            conn.execute(
                """
                INSERT INTO checkpoint_records(
                    stream_id,sequence,record_sha256,parent_record_sha256,
                    checkpoint_sha256,record_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    record.stream_id,
                    record.sequence,
                    record_hash,
                    record.parent_record_sha256,
                    record.checkpoint_sha256,
                    record.canonical_bytes().decode("utf-8"),
                ),
            )
            conn.commit()
            return record
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def records(self, stream_id: str) -> tuple[CheckpointHistoryRecord, ...]:
        stream_id = _identity_text(stream_id, "CHECKPOINT_HISTORY_STREAM_ID_INVALID")
        with self._connect() as conn:
            self._require_schema(conn)
            rows = conn.execute(
                "SELECT * FROM checkpoint_records WHERE stream_id=? ORDER BY sequence",
                (stream_id,),
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def verify_stream(self, stream_id: str) -> CheckpointStreamVerification:
        stream_id = _identity_text(stream_id, "CHECKPOINT_HISTORY_STREAM_ID_INVALID")
        try:
            records = self.records(stream_id)
        except SEDBReadOnlyAdapterError:
            return CheckpointStreamVerification(
                stream_id=stream_id,
                valid=False,
                record_count=0,
                head_record_sha256=None,
                head_checkpoint_sha256=None,
                authority_ref=None,
            )
        parent = None
        for expected_sequence, record in enumerate(records):
            if record.sequence != expected_sequence or record.parent_record_sha256 != parent:
                return CheckpointStreamVerification(
                    stream_id=stream_id,
                    valid=False,
                    record_count=len(records),
                    head_record_sha256=None,
                    head_checkpoint_sha256=None,
                    authority_ref=None,
                )
            parent = record.record_sha256()
        head = records[-1] if records else None
        return CheckpointStreamVerification(
            stream_id=stream_id,
            valid=True,
            record_count=len(records),
            head_record_sha256=None if head is None else head.record_sha256(),
            head_checkpoint_sha256=None if head is None else head.checkpoint_sha256,
            authority_ref=None if head is None else head.authority_ref,
        )


def verify_sidecar_envelope_at_head(
    envelope: SidecarProofEnvelope,
    ledger: CheckpointHistoryLedger,
    *,
    stream_id: str,
) -> CheckpointHeadVerification:
    if not isinstance(envelope, SidecarProofEnvelope):
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HEAD_ENVELOPE_REQUIRED")
    if not isinstance(ledger, CheckpointHistoryLedger):
        raise SEDBReadOnlyAdapterError("CHECKPOINT_HEAD_LEDGER_REQUIRED")
    stream = ledger.verify_stream(stream_id)
    checkpoint_sha = envelope.checkpoint.checkpoint_sha256()
    return CheckpointHeadVerification(
        stream_id=stream_id,
        chain_valid=stream.valid,
        checkpoint_is_head=(
            stream.head_checkpoint_sha256 is not None
            and stream.head_checkpoint_sha256 == checkpoint_sha
        ),
        proof_valid=verify_sidecar_proof_envelope(envelope),
        head_record_sha256=stream.head_record_sha256,
        head_checkpoint_sha256=stream.head_checkpoint_sha256,
        authority_ref=stream.authority_ref,
    )

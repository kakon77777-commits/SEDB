from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

from .adapter import (
    SEDBCellSnapshot,
    SEDBEntitySnapshot,
    SEDBFieldBindingSnapshot,
    SEDBReadOnlyAdapter,
    SEDBReadOnlyAdapterError,
    _confidence,
    _json_value,
    _require_text,
)
from .commitment import (
    SPARSE_MERKLE_DEPTH,
    CommittedEntityMetadata,
    EntityStateCommitment,
    FieldClaimProof,
    FieldRegistryCommitment,
    MerkleMembershipProof,
    MerkleNonMembershipProof,
    ProofCarryingPartialEntity,
    _EMPTY_HASHES,
    _build_sparse_tree,
    _cell_payload,
    _canonical_json_bytes,
    _key_position,
    _slot_cell_payload,
    verify_membership_proof,
    verify_proof_carrying_projection,
)
from .materializer import FieldProjectionState, PartialEntityProjection


PROOF_SIDECAR_SCHEMA = "isql-sedb.proof-sidecar/v0.1"
PROOF_SIDECAR_CHECKPOINT_SCHEMA = "isql-sedb.proof-sidecar-checkpoint/v0.1"
PROOF_SIDECAR_ENVELOPE_SCHEMA = "isql-sedb.sidecar-proof-envelope/v0.1"


_SIDECAR_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE field_registry (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    commitment_json TEXT NOT NULL,
    commitment_sha256 TEXT NOT NULL
);

CREATE TABLE field_leaves (
    field_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);

CREATE TABLE field_nodes (
    depth INTEGER NOT NULL,
    position_hex TEXT NOT NULL,
    hash_hex TEXT NOT NULL,
    PRIMARY KEY(depth, position_hex)
);

CREATE TABLE entity_commitments (
    entity_id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    commitment_json TEXT NOT NULL,
    commitment_sha256 TEXT NOT NULL
);

CREATE TABLE cell_leaves (
    entity_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(entity_id, field_id)
);

CREATE TABLE cell_nodes (
    entity_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    position_hex TEXT NOT NULL,
    hash_hex TEXT NOT NULL,
    PRIMARY KEY(entity_id, depth, position_hex)
);

CREATE TABLE entity_index_nodes (
    depth INTEGER NOT NULL,
    position_hex TEXT NOT NULL,
    hash_hex TEXT NOT NULL,
    PRIMARY KEY(depth, position_hex)
);

CREATE TABLE entity_index_leaves (
    entity_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_cell_nodes_lookup
ON cell_nodes(entity_id, depth, position_hex);
"""


def _json_text(value: object) -> str:
    return _canonical_json_bytes(value).decode("utf-8")


def _json_object(raw: str, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SEDBReadOnlyAdapterError(code) from exc
    if not isinstance(value, dict):
        raise SEDBReadOnlyAdapterError(code)
    _canonical_json_bytes(value)
    return value


def _position_hex(position: int) -> str:
    if not isinstance(position, int) or position < 0 or position >= (1 << 256):
        raise SEDBReadOnlyAdapterError("SIDECAR_NODE_POSITION_INVALID")
    return f"{position:064x}"


def _write_tree_nodes(
    conn: sqlite3.Connection,
    table: str,
    tree,
    *,
    entity_id: str | None = None,
) -> None:
    if table not in {"field_nodes", "cell_nodes", "entity_index_nodes"}:
        raise SEDBReadOnlyAdapterError("SIDECAR_NODE_TABLE_INVALID")
    rows = []
    for depth, nodes in tree.levels.items():
        for position, value in nodes.items():
            if entity_id is None:
                rows.append((depth, _position_hex(position), value.hex()))
            else:
                rows.append((entity_id, depth, _position_hex(position), value.hex()))
    if entity_id is None:
        conn.executemany(
            f"INSERT INTO {table}(depth,position_hex,hash_hex) VALUES(?,?,?)",
            rows,
        )
    else:
        conn.executemany(
            f"INSERT INTO {table}(entity_id,depth,position_hex,hash_hex) VALUES(?,?,?,?)",
            rows,
        )


def _field_from_row(row: sqlite3.Row) -> SEDBFieldBindingSnapshot:
    return SEDBFieldBindingSnapshot(
        field_id=_require_text(row["id"], "SIDECAR_FIELD_ID_INVALID"),
        key=_require_text(row["key"], "SIDECAR_FIELD_KEY_INVALID"),
        namespace=_require_text(row["namespace"], "SIDECAR_FIELD_NAMESPACE_INVALID"),
        normalized_key=None if row["normalized_key"] is None else str(row["normalized_key"]),
        label=_require_text(row["label"], "SIDECAR_FIELD_LABEL_INVALID"),
        value_type=_require_text(row["value_type"], "SIDECAR_FIELD_TYPE_INVALID"),
        description=str(row["description"] or ""),
        status=_require_text(row["status"], "SIDECAR_FIELD_STATUS_INVALID"),
        created_at=_require_text(row["created_at"], "SIDECAR_FIELD_CREATED_AT_INVALID"),
        updated_at=_require_text(row["updated_at"], "SIDECAR_FIELD_UPDATED_AT_INVALID"),
    )


def _read_field_registry_from_conn(
    conn: sqlite3.Connection,
) -> tuple[SEDBFieldBindingSnapshot, ...]:
    rows = conn.execute(
        """
        SELECT id,key,namespace,normalized_key,label,value_type,description,
               status,created_at,updated_at
        FROM fields
        ORDER BY id
        LIMIT 100001
        """
    ).fetchall()
    if len(rows) > 100000:
        raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_REGISTRY_TOO_LARGE")
    return tuple(_field_from_row(row) for row in rows)


def _read_entity_snapshot_from_conn(
    conn: sqlite3.Connection,
    entity_id: str,
) -> SEDBEntitySnapshot:
    entity = conn.execute(
        "SELECT id,kind,label,created_at,updated_at FROM entities WHERE id=?",
        (entity_id,),
    ).fetchone()
    if entity is None:
        raise KeyError(f"SEDB entity not found: {entity_id}")
    rows = conn.execute(
        """
        SELECT
            f.id AS field_id,
            f.key AS field_key,
            f.namespace AS field_namespace,
            f.normalized_key AS field_normalized_key,
            f.label AS field_label,
            f.value_type AS field_value_type,
            f.description AS field_description,
            f.status AS field_status,
            f.created_at AS field_created_at,
            f.updated_at AS field_updated_at,
            c.value_json AS cell_value_json,
            c.source AS cell_source,
            c.confidence AS cell_confidence,
            c.updated_at AS cell_updated_at
        FROM cells c
        JOIN fields f ON f.id=c.field_id
        WHERE c.entity_id=?
        ORDER BY f.id
        """,
        (entity_id,),
    ).fetchall()
    cells = []
    for row in rows:
        field = SEDBFieldBindingSnapshot(
            field_id=_require_text(row["field_id"], "SIDECAR_FIELD_ID_INVALID"),
            key=_require_text(row["field_key"], "SIDECAR_FIELD_KEY_INVALID"),
            namespace=_require_text(row["field_namespace"], "SIDECAR_FIELD_NAMESPACE_INVALID"),
            normalized_key=(
                None if row["field_normalized_key"] is None else str(row["field_normalized_key"])
            ),
            label=_require_text(row["field_label"], "SIDECAR_FIELD_LABEL_INVALID"),
            value_type=_require_text(row["field_value_type"], "SIDECAR_FIELD_TYPE_INVALID"),
            description=str(row["field_description"] or ""),
            status=_require_text(row["field_status"], "SIDECAR_FIELD_STATUS_INVALID"),
            created_at=_require_text(row["field_created_at"], "SIDECAR_FIELD_CREATED_AT_INVALID"),
            updated_at=_require_text(row["field_updated_at"], "SIDECAR_FIELD_UPDATED_AT_INVALID"),
        )
        cells.append(SEDBCellSnapshot(
            field=field,
            value=_json_value(row["cell_value_json"]),
            source=str(row["cell_source"] or ""),
            confidence=_confidence(row["cell_confidence"]),
            updated_at=_require_text(row["cell_updated_at"], "SIDECAR_CELL_UPDATED_AT_INVALID"),
        ))
    snapshot = SEDBEntitySnapshot(
        entity_id=_require_text(entity["id"], "SIDECAR_ENTITY_ID_INVALID"),
        kind=_require_text(entity["kind"], "SIDECAR_ENTITY_KIND_INVALID"),
        label=_require_text(entity["label"], "SIDECAR_ENTITY_LABEL_INVALID"),
        created_at=_require_text(entity["created_at"], "SIDECAR_ENTITY_CREATED_AT_INVALID"),
        updated_at=_require_text(entity["updated_at"], "SIDECAR_ENTITY_UPDATED_AT_INVALID"),
        cells=tuple(cells),
    )
    snapshot.canonical_bytes()
    return snapshot


def _entity_commitment_from_snapshot(snapshot: SEDBEntitySnapshot):
    metadata = CommittedEntityMetadata.from_snapshot(snapshot)
    tree = _build_sparse_tree(
        (cell.field.field_id, _cell_payload(cell)) for cell in snapshot.cells
    )
    commitment = EntityStateCommitment(
        entity_id=snapshot.entity_id,
        legacy_snapshot_sha256=snapshot.sha256(),
        entity_metadata_sha256=metadata.sha256(),
        cell_root_sha256=tree.root.hex(),
        cell_count=len(tree.leaves),
    )
    return metadata, tree, commitment


@dataclass(frozen=True, slots=True)
class ProofSidecarCheckpoint:
    field_registry_commitment_sha256: str
    entity_root_sha256: str
    entity_count: int

    def __post_init__(self) -> None:
        for value, code in (
            (self.field_registry_commitment_sha256, "SIDECAR_FIELD_COMMITMENT_HASH_INVALID"),
            (self.entity_root_sha256, "SIDECAR_ENTITY_ROOT_HASH_INVALID"),
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise SEDBReadOnlyAdapterError(code)
            try:
                bytes.fromhex(value)
            except ValueError as exc:
                raise SEDBReadOnlyAdapterError(code) from exc
        if not isinstance(self.entity_count, int) or isinstance(self.entity_count, bool) or self.entity_count < 0:
            raise SEDBReadOnlyAdapterError("SIDECAR_ENTITY_COUNT_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROOF_SIDECAR_CHECKPOINT_SCHEMA,
            "field_registry_commitment_sha256": self.field_registry_commitment_sha256,
            "entity_root_sha256": self.entity_root_sha256,
            "entity_count": self.entity_count,
        }

    def checkpoint_sha256(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class SidecarBuildResult:
    sidecar_path: str
    checkpoint: ProofSidecarCheckpoint
    checkpoint_sha256: str
    entity_count: int
    field_count: int


@dataclass(frozen=True, slots=True)
class SidecarReadStats:
    field_leaf_reads: int
    cell_leaf_reads: int
    node_hash_lookups: int
    commitment_reads: int

    def to_dict(self) -> dict[str, int]:
        return {
            "field_leaf_reads": self.field_leaf_reads,
            "cell_leaf_reads": self.cell_leaf_reads,
            "node_hash_lookups": self.node_hash_lookups,
            "commitment_reads": self.commitment_reads,
        }


@dataclass(frozen=True, slots=True)
class SidecarProofEnvelope:
    checkpoint: ProofSidecarCheckpoint
    entity_commitment_membership: MerkleMembershipProof
    proof_bundle: ProofCarryingPartialEntity
    read_stats: SidecarReadStats

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROOF_SIDECAR_ENVELOPE_SCHEMA,
            "checkpoint": self.checkpoint.to_dict(),
            "entity_commitment_membership": self.entity_commitment_membership.to_dict(),
            "proof_bundle": self.proof_bundle.to_dict(),
            "read_stats": self.read_stats.to_dict(),
        }

    def envelope_sha256(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


def build_proof_sidecar(
    adapter: SEDBReadOnlyAdapter,
    sidecar_path: str | Path,
    *,
    overwrite: bool = False,
) -> SidecarBuildResult:
    if not isinstance(adapter, SEDBReadOnlyAdapter):
        raise SEDBReadOnlyAdapterError("SIDECAR_ADAPTER_REQUIRED")
    target = Path(sidecar_path).expanduser().resolve()
    if target == adapter.database_path:
        raise SEDBReadOnlyAdapterError("SIDECAR_PATH_MUST_DIFFER_FROM_SEDB")
    if target.exists():
        if not overwrite:
            raise FileExistsError(target)
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)

    # One explicit source read transaction gives one consistent SEDB checkpoint even
    # if another writer commits while the sidecar is being built.
    with adapter._connect() as source:
        adapter._require_schema(source)
        source.execute("BEGIN")
        fields = _read_field_registry_from_conn(source)
        field_tree = _build_sparse_tree((field.field_id, field.to_dict()) for field in fields)
        field_commitment = FieldRegistryCommitment(
            field_root_sha256=field_tree.root.hex(),
            field_count=len(field_tree.leaves),
        )
        entity_ids = tuple(
            str(row["id"])
            for row in source.execute("SELECT id FROM entities ORDER BY id").fetchall()
        )
        entity_rows = []
        entity_index_leaves = []
        entity_payloads = []
        for entity_id in entity_ids:
            snapshot = _read_entity_snapshot_from_conn(source, entity_id)
            metadata, cell_tree, commitment = _entity_commitment_from_snapshot(snapshot)
            commitment_sha = commitment.commitment_sha256()
            entity_index_payload = {"entity_commitment_sha256": commitment_sha}
            entity_index_leaves.append((entity_id, entity_index_payload))
            entity_rows.append((entity_id, snapshot, metadata, cell_tree, commitment, commitment_sha))
            entity_payloads.append((entity_id, entity_index_payload))

        entity_index_tree = _build_sparse_tree(entity_index_leaves)
        checkpoint = ProofSidecarCheckpoint(
            field_registry_commitment_sha256=field_commitment.commitment_sha256(),
            entity_root_sha256=entity_index_tree.root.hex(),
            entity_count=len(entity_rows),
        )

        with sqlite3.connect(target) as out:
            out.execute("PRAGMA foreign_keys=ON")
            out.executescript(_SIDECAR_DDL)
            out.execute(
                "INSERT INTO metadata(key,value_json) VALUES('schema',?)",
                (_json_text({"schema": PROOF_SIDECAR_SCHEMA}),),
            )
            out.execute(
                "INSERT INTO metadata(key,value_json) VALUES('checkpoint',?)",
                (_json_text(checkpoint.to_dict()),),
            )
            out.execute(
                "INSERT INTO field_registry(singleton,commitment_json,commitment_sha256) VALUES(1,?,?)",
                (_json_text(field_commitment.to_dict()), field_commitment.commitment_sha256()),
            )
            out.executemany(
                "INSERT INTO field_leaves(field_id,payload_json) VALUES(?,?)",
                [(field.field_id, _json_text(field.to_dict())) for field in fields],
            )
            _write_tree_nodes(out, "field_nodes", field_tree)

            for entity_id, snapshot, metadata, cell_tree, commitment, commitment_sha in entity_rows:
                out.execute(
                    """
                    INSERT INTO entity_commitments(
                        entity_id,metadata_json,commitment_json,commitment_sha256
                    ) VALUES(?,?,?,?)
                    """,
                    (
                        entity_id,
                        _json_text(metadata.to_dict()),
                        _json_text(commitment.to_dict()),
                        commitment_sha,
                    ),
                )
                out.executemany(
                    "INSERT INTO cell_leaves(entity_id,field_id,payload_json) VALUES(?,?,?)",
                    [
                        (entity_id, cell.field.field_id, _json_text(_cell_payload(cell)))
                        for cell in snapshot.cells
                    ],
                )
                _write_tree_nodes(out, "cell_nodes", cell_tree, entity_id=entity_id)

            out.executemany(
                "INSERT INTO entity_index_leaves(entity_id,payload_json) VALUES(?,?)",
                [(entity_id, _json_text(payload)) for entity_id, payload in entity_payloads],
            )
            _write_tree_nodes(out, "entity_index_nodes", entity_index_tree)
            if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SEDBReadOnlyAdapterError("SIDECAR_SQLITE_INTEGRITY_FAILED")

    return SidecarBuildResult(
        sidecar_path=str(target),
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint.checkpoint_sha256(),
        entity_count=len(entity_rows),
        field_count=len(fields),
    )


def _field_from_payload(payload: dict[str, Any]) -> SEDBFieldBindingSnapshot:
    return SEDBFieldBindingSnapshot(
        field_id=str(payload["field_id"]),
        key=str(payload["key"]),
        namespace=str(payload["namespace"]),
        normalized_key=None if payload.get("normalized_key") is None else str(payload["normalized_key"]),
        label=str(payload["label"]),
        value_type=str(payload["value_type"]),
        description=str(payload.get("description") or ""),
        status=str(payload["status"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )


def _metadata_from_payload(payload: dict[str, Any]) -> CommittedEntityMetadata:
    return CommittedEntityMetadata(
        entity_id=str(payload["id"]),
        kind=str(payload["kind"]),
        label=str(payload["label"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )


def _entity_commitment_from_payload(payload: dict[str, Any]) -> EntityStateCommitment:
    if payload.get("schema") != "isql-sedb.entity-state-commitment/v0.1":
        raise SEDBReadOnlyAdapterError("SIDECAR_ENTITY_COMMITMENT_SCHEMA_INVALID")
    return EntityStateCommitment(
        entity_id=str(payload["entity_id"]),
        legacy_snapshot_sha256=str(payload["legacy_snapshot_sha256"]),
        entity_metadata_sha256=str(payload["entity_metadata_sha256"]),
        cell_root_sha256=str(payload["cell_root_sha256"]),
        cell_count=int(payload["cell_count"]),
    )


def _field_commitment_from_payload(payload: dict[str, Any]) -> FieldRegistryCommitment:
    if payload.get("schema") != "isql-sedb.field-registry-commitment/v0.1":
        raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_COMMITMENT_SCHEMA_INVALID")
    return FieldRegistryCommitment(
        field_root_sha256=str(payload["field_root_sha256"]),
        field_count=int(payload["field_count"]),
    )


class ProofSidecar:
    def __init__(self, path: str | Path):
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise SEDBReadOnlyAdapterError("SIDECAR_FILE_REQUIRED")
        self.path = target

    def _connect(self) -> sqlite3.Connection:
        encoded = quote(self.path.as_posix(), safe="/:")
        conn = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        required = {
            "metadata", "field_registry", "field_leaves", "field_nodes",
            "entity_commitments", "cell_leaves", "cell_nodes",
            "entity_index_nodes", "entity_index_leaves",
        }
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {str(row["name"]) for row in rows}
        if not required.issubset(names):
            raise SEDBReadOnlyAdapterError("SIDECAR_REQUIRED_SCHEMA_MISSING")
        row = conn.execute("SELECT value_json FROM metadata WHERE key='schema'").fetchone()
        if row is None or _json_object(row["value_json"], "SIDECAR_SCHEMA_METADATA_INVALID").get("schema") != PROOF_SIDECAR_SCHEMA:
            raise SEDBReadOnlyAdapterError("SIDECAR_SCHEMA_VERSION_INVALID")

    def checkpoint(self) -> ProofSidecarCheckpoint:
        with self._connect() as conn:
            self._require_schema(conn)
            row = conn.execute("SELECT value_json FROM metadata WHERE key='checkpoint'").fetchone()
        if row is None:
            raise SEDBReadOnlyAdapterError("SIDECAR_CHECKPOINT_MISSING")
        payload = _json_object(row["value_json"], "SIDECAR_CHECKPOINT_INVALID")
        if payload.get("schema") != PROOF_SIDECAR_CHECKPOINT_SCHEMA:
            raise SEDBReadOnlyAdapterError("SIDECAR_CHECKPOINT_SCHEMA_INVALID")
        return ProofSidecarCheckpoint(
            field_registry_commitment_sha256=str(payload["field_registry_commitment_sha256"]),
            entity_root_sha256=str(payload["entity_root_sha256"]),
            entity_count=int(payload["entity_count"]),
        )

    @staticmethod
    def _node_siblings(
        conn: sqlite3.Connection,
        table: str,
        key: str,
        *,
        entity_id: str | None = None,
    ) -> tuple[tuple[str, ...], int]:
        if table not in {"field_nodes", "cell_nodes", "entity_index_nodes"}:
            raise SEDBReadOnlyAdapterError("SIDECAR_NODE_TABLE_INVALID")
        index = _key_position(key)
        siblings = []
        lookups = 0
        for depth in range(SPARSE_MERKLE_DEPTH, 0, -1):
            sibling_position = _position_hex(index ^ 1)
            if entity_id is None:
                row = conn.execute(
                    f"SELECT hash_hex FROM {table} WHERE depth=? AND position_hex=?",
                    (depth, sibling_position),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT hash_hex FROM {table} WHERE entity_id=? AND depth=? AND position_hex=?",
                    (entity_id, depth, sibling_position),
                ).fetchone()
            lookups += 1
            siblings.append(
                _EMPTY_HASHES[depth].hex() if row is None else str(row["hash_hex"])
            )
            index >>= 1
        return tuple(siblings), lookups

    def issue_projection(self, projection: PartialEntityProjection) -> SidecarProofEnvelope:
        if not isinstance(projection, PartialEntityProjection):
            raise SEDBReadOnlyAdapterError("SIDECAR_PARTIAL_PROJECTION_REQUIRED")

        field_leaf_reads = 0
        cell_leaf_reads = 0
        node_hash_lookups = 0
        commitment_reads = 0

        with self._connect() as conn:
            self._require_schema(conn)
            checkpoint_row = conn.execute(
                "SELECT value_json FROM metadata WHERE key='checkpoint'"
            ).fetchone()
            if checkpoint_row is None:
                raise SEDBReadOnlyAdapterError("SIDECAR_CHECKPOINT_MISSING")
            checkpoint_payload = _json_object(
                checkpoint_row["value_json"],
                "SIDECAR_CHECKPOINT_INVALID",
            )
            checkpoint = ProofSidecarCheckpoint(
                field_registry_commitment_sha256=str(checkpoint_payload["field_registry_commitment_sha256"]),
                entity_root_sha256=str(checkpoint_payload["entity_root_sha256"]),
                entity_count=int(checkpoint_payload["entity_count"]),
            )
            commitment_reads += 1

            field_row = conn.execute(
                "SELECT commitment_json,commitment_sha256 FROM field_registry WHERE singleton=1"
            ).fetchone()
            if field_row is None:
                raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_COMMITMENT_MISSING")
            field_commitment = _field_commitment_from_payload(_json_object(
                field_row["commitment_json"],
                "SIDECAR_FIELD_COMMITMENT_INVALID",
            ))
            if field_commitment.commitment_sha256() != str(field_row["commitment_sha256"]):
                raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_COMMITMENT_HASH_MISMATCH")
            if checkpoint.field_registry_commitment_sha256 != field_commitment.commitment_sha256():
                raise SEDBReadOnlyAdapterError("SIDECAR_CHECKPOINT_FIELD_BINDING_MISMATCH")
            commitment_reads += 1

            entity_row = conn.execute(
                """
                SELECT metadata_json,commitment_json,commitment_sha256
                FROM entity_commitments WHERE entity_id=?
                """,
                (projection.source_exact.entity_id,),
            ).fetchone()
            if entity_row is None:
                raise KeyError(f"sidecar entity not found: {projection.source_exact.entity_id}")
            metadata = _metadata_from_payload(_json_object(
                entity_row["metadata_json"],
                "SIDECAR_ENTITY_METADATA_INVALID",
            ))
            entity_commitment = _entity_commitment_from_payload(_json_object(
                entity_row["commitment_json"],
                "SIDECAR_ENTITY_COMMITMENT_INVALID",
            ))
            entity_commitment_sha = entity_commitment.commitment_sha256()
            if entity_commitment_sha != str(entity_row["commitment_sha256"]):
                raise SEDBReadOnlyAdapterError("SIDECAR_ENTITY_COMMITMENT_HASH_MISMATCH")
            if projection.source_exact.state_sha256 != entity_commitment.legacy_snapshot_sha256:
                raise SEDBReadOnlyAdapterError("SIDECAR_PROJECTION_LEGACY_HASH_MISMATCH")
            commitment_reads += 1

            entity_index_leaf = conn.execute(
                "SELECT payload_json FROM entity_index_leaves WHERE entity_id=?",
                (entity_commitment.entity_id,),
            ).fetchone()
            if entity_index_leaf is None:
                raise SEDBReadOnlyAdapterError("SIDECAR_ENTITY_INDEX_LEAF_MISSING")
            entity_index_payload = _json_object(
                entity_index_leaf["payload_json"],
                "SIDECAR_ENTITY_INDEX_LEAF_INVALID",
            )
            if entity_index_payload != {"entity_commitment_sha256": entity_commitment_sha}:
                raise SEDBReadOnlyAdapterError("SIDECAR_ENTITY_INDEX_BINDING_MISMATCH")
            entity_siblings, lookups = self._node_siblings(
                conn,
                "entity_index_nodes",
                entity_commitment.entity_id,
            )
            node_hash_lookups += lookups
            entity_membership = MerkleMembershipProof(
                key=entity_commitment.entity_id,
                payload=entity_index_payload,
                siblings=entity_siblings,
            )

            claims = []
            for slot in projection.fields:
                leaf = conn.execute(
                    "SELECT payload_json FROM field_leaves WHERE field_id=?",
                    (slot.field.field_id,),
                ).fetchone()
                field_leaf_reads += 1
                if leaf is None:
                    raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_LEAF_MISSING")
                field_payload = _json_object(
                    leaf["payload_json"],
                    "SIDECAR_FIELD_LEAF_INVALID",
                )
                field = _field_from_payload(field_payload)
                if field.key != slot.field.key:
                    raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_KEY_BINDING_MISMATCH")
                field_siblings, lookups = self._node_siblings(
                    conn,
                    "field_nodes",
                    field.field_id,
                )
                node_hash_lookups += lookups
                field_membership = MerkleMembershipProof(
                    key=field.field_id,
                    payload=field_payload,
                    siblings=field_siblings,
                )

                cell_membership = None
                cell_nonmembership = None
                if slot.state in (
                    FieldProjectionState.PRESENT,
                    FieldProjectionState.BLANK,
                    FieldProjectionState.ABSENT,
                    FieldProjectionState.UNKNOWN,
                ):
                    cell_row = conn.execute(
                        "SELECT payload_json FROM cell_leaves WHERE entity_id=? AND field_id=?",
                        (entity_commitment.entity_id, field.field_id),
                    ).fetchone()
                    cell_leaf_reads += 1
                    cell_siblings, lookups = self._node_siblings(
                        conn,
                        "cell_nodes",
                        field.field_id,
                        entity_id=entity_commitment.entity_id,
                    )
                    node_hash_lookups += lookups
                    if slot.state in (FieldProjectionState.PRESENT, FieldProjectionState.BLANK):
                        if cell_row is None:
                            raise SEDBReadOnlyAdapterError("SIDECAR_CELL_LEAF_MISSING")
                        cell_payload = _json_object(
                            cell_row["payload_json"],
                            "SIDECAR_CELL_LEAF_INVALID",
                        )
                        if cell_payload != _slot_cell_payload(slot):
                            raise SEDBReadOnlyAdapterError("SIDECAR_CELL_PAYLOAD_BINDING_MISMATCH")
                        cell_membership = MerkleMembershipProof(
                            key=field.field_id,
                            payload=cell_payload,
                            siblings=cell_siblings,
                        )
                    else:
                        if cell_row is not None:
                            raise SEDBReadOnlyAdapterError("SIDECAR_NONMEMBERSHIP_CONFLICTS_WITH_CELL")
                        cell_nonmembership = MerkleNonMembershipProof(
                            key=field.field_id,
                            siblings=cell_siblings,
                        )
                elif slot.state is FieldProjectionState.UNLOADED:
                    # Deliberately do not query cell_leaves/cell_nodes for unloaded state.
                    pass
                else:
                    raise SEDBReadOnlyAdapterError("SIDECAR_FIELD_STATE_UNSUPPORTED")

                claims.append(FieldClaimProof(
                    field=field,
                    field_membership=field_membership,
                    cell_membership=cell_membership,
                    cell_nonmembership=cell_nonmembership,
                ))

        bundle = ProofCarryingPartialEntity(
            projection=projection,
            entity_metadata=metadata,
            entity_commitment=entity_commitment,
            field_registry_commitment=field_commitment,
            claims=tuple(claims),
        )
        stats = SidecarReadStats(
            field_leaf_reads=field_leaf_reads,
            cell_leaf_reads=cell_leaf_reads,
            node_hash_lookups=node_hash_lookups,
            commitment_reads=commitment_reads,
        )
        envelope = SidecarProofEnvelope(
            checkpoint=checkpoint,
            entity_commitment_membership=entity_membership,
            proof_bundle=bundle,
            read_stats=stats,
        )
        if not verify_sidecar_proof_envelope(envelope):
            raise SEDBReadOnlyAdapterError("SIDECAR_ISSUED_PROOF_FAILED_SELF_VERIFY")
        return envelope


def verify_sidecar_proof_envelope(envelope: SidecarProofEnvelope) -> bool:
    if not isinstance(envelope, SidecarProofEnvelope):
        raise SEDBReadOnlyAdapterError("SIDECAR_PROOF_ENVELOPE_REQUIRED")
    bundle = envelope.proof_bundle
    entity_commitment_sha = bundle.entity_commitment.commitment_sha256()
    expected_payload = {"entity_commitment_sha256": entity_commitment_sha}
    membership = envelope.entity_commitment_membership
    if membership.key != bundle.entity_commitment.entity_id:
        return False
    if membership.payload != expected_payload:
        return False
    if not verify_membership_proof(membership, envelope.checkpoint.entity_root_sha256):
        return False
    if (
        envelope.checkpoint.field_registry_commitment_sha256
        != bundle.field_registry_commitment.commitment_sha256()
    ):
        return False
    return verify_proof_carrying_projection(bundle)

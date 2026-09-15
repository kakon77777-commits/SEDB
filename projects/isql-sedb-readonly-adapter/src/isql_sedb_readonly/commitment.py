from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from .adapter import (
    SEDBCellSnapshot,
    SEDBEntitySnapshot,
    SEDBFieldBindingSnapshot,
    SEDBReadOnlyAdapter,
    SEDBReadOnlyAdapterError,
)
from .materializer import (
    FieldProjectionState,
    PartialEntityProjection,
    PartialFieldSlot,
)


ENTITY_STATE_COMMITMENT_SCHEMA = "isql-sedb.entity-state-commitment/v0.1"
FIELD_REGISTRY_COMMITMENT_SCHEMA = "isql-sedb.field-registry-commitment/v0.1"
PROOF_CARRYING_PROJECTION_SCHEMA = "isql-sedb.proof-carrying-partial-entity/v0.1"
SPARSE_MERKLE_DEPTH = 256


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
        raise SEDBReadOnlyAdapterError("COMMITMENT_NOT_CANONICAL_JSON") from exc


def _require_hex64(value: str, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise SEDBReadOnlyAdapterError(code)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise SEDBReadOnlyAdapterError(code) from exc
    if len(raw) != 32:
        raise SEDBReadOnlyAdapterError(code)
    return value.lower()


def _require_key(key: str) -> str:
    if not isinstance(key, str) or not key or "\x00" in key:
        raise SEDBReadOnlyAdapterError("COMMITMENT_LEAF_KEY_INVALID")
    return key


def _key_digest(key: str) -> bytes:
    return hashlib.sha256(b"\x02" + _require_key(key).encode("utf-8")).digest()


def _key_position(key: str) -> int:
    return int.from_bytes(_key_digest(key), "big")


def _present_leaf_hash(key: str, payload: object) -> bytes:
    _canonical_json_bytes(payload)
    return hashlib.sha256(
        b"\x00present" + _key_digest(key) + _canonical_json_bytes(payload)
    ).digest()


def _internal_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _empty_hashes() -> tuple[bytes, ...]:
    values: list[bytes] = [b""] * (SPARSE_MERKLE_DEPTH + 1)
    values[SPARSE_MERKLE_DEPTH] = hashlib.sha256(b"\x00empty").digest()
    for depth in range(SPARSE_MERKLE_DEPTH - 1, -1, -1):
        values[depth] = _internal_hash(values[depth + 1], values[depth + 1])
    return tuple(values)


_EMPTY_HASHES = _empty_hashes()


def _canonical_leaves(leaves: Iterable[tuple[str, object]]) -> tuple[tuple[str, object], ...]:
    rows = tuple(sorted(leaves, key=lambda row: row[0]))
    keys = [key for key, _ in rows]
    if len(keys) != len(set(keys)):
        raise SEDBReadOnlyAdapterError("COMMITMENT_DUPLICATE_LEAF_KEY")
    for key, payload in rows:
        _require_key(key)
        _canonical_json_bytes(payload)
    return rows


@dataclass(slots=True)
class _SparseMerkleTree:
    leaves: tuple[tuple[str, object], ...]
    positions: dict[str, int]
    payloads: dict[str, object]
    levels: dict[int, dict[int, bytes]]
    root: bytes


def _build_sparse_tree(leaves: Iterable[tuple[str, object]]) -> _SparseMerkleTree:
    rows = _canonical_leaves(leaves)
    positions: dict[str, int] = {}
    payloads: dict[str, object] = {}
    leaf_nodes: dict[int, bytes] = {}
    occupied: dict[int, str] = {}

    for key, payload in rows:
        position = _key_position(key)
        other = occupied.get(position)
        if other is not None and other != key:
            raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_KEY_DIGEST_COLLISION")
        occupied[position] = key
        positions[key] = position
        payloads[key] = payload
        leaf_nodes[position] = _present_leaf_hash(key, payload)

    levels: dict[int, dict[int, bytes]] = {SPARSE_MERKLE_DEPTH: leaf_nodes}
    current = leaf_nodes
    for depth in range(SPARSE_MERKLE_DEPTH, 0, -1):
        parent_indices = {position >> 1 for position in current}
        parents: dict[int, bytes] = {}
        default_child = _EMPTY_HASHES[depth]
        default_parent = _EMPTY_HASHES[depth - 1]
        for parent in parent_indices:
            left = current.get(parent << 1, default_child)
            right = current.get((parent << 1) | 1, default_child)
            value = _internal_hash(left, right)
            if value != default_parent:
                parents[parent] = value
        levels[depth - 1] = parents
        current = parents

    root = levels[0].get(0, _EMPTY_HASHES[0])
    return _SparseMerkleTree(
        leaves=rows,
        positions=positions,
        payloads=payloads,
        levels=levels,
        root=root,
    )


@dataclass(frozen=True, slots=True)
class MerkleMembershipProof:
    key: str
    payload: object
    siblings: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_key(self.key)
        _canonical_json_bytes(self.payload)
        if len(self.siblings) != SPARSE_MERKLE_DEPTH:
            raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_PROOF_DEPTH_INVALID")
        for sibling in self.siblings:
            _require_hex64(sibling, "SPARSE_MERKLE_SIBLING_HASH_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "payload": self.payload,
            "siblings": list(self.siblings),
        }


@dataclass(frozen=True, slots=True)
class MerkleNonMembershipProof:
    key: str
    siblings: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_key(self.key)
        if len(self.siblings) != SPARSE_MERKLE_DEPTH:
            raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_PROOF_DEPTH_INVALID")
        for sibling in self.siblings:
            _require_hex64(sibling, "SPARSE_MERKLE_SIBLING_HASH_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "siblings": list(self.siblings)}


def _proof_siblings(tree: _SparseMerkleTree, key: str) -> tuple[str, ...]:
    position = _key_position(key)
    siblings: list[str] = []
    index = position
    for depth in range(SPARSE_MERKLE_DEPTH, 0, -1):
        sibling_index = index ^ 1
        sibling = tree.levels[depth].get(sibling_index, _EMPTY_HASHES[depth])
        siblings.append(sibling.hex())
        index >>= 1
    return tuple(siblings)


def _membership_proof(tree: _SparseMerkleTree, key: str) -> MerkleMembershipProof:
    if key not in tree.positions:
        raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_MEMBERSHIP_KEY_MISSING")
    return MerkleMembershipProof(
        key=key,
        payload=tree.payloads[key],
        siblings=_proof_siblings(tree, key),
    )


def _nonmembership_proof(tree: _SparseMerkleTree, key: str) -> MerkleNonMembershipProof:
    if key in tree.positions:
        raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_NONMEMBERSHIP_KEY_EXISTS")
    return MerkleNonMembershipProof(
        key=key,
        siblings=_proof_siblings(tree, key),
    )


def _fold_sparse_path(key: str, start_hash: bytes, siblings: tuple[str, ...]) -> bytes:
    if len(siblings) != SPARSE_MERKLE_DEPTH:
        raise SEDBReadOnlyAdapterError("SPARSE_MERKLE_PROOF_DEPTH_INVALID")
    position = _key_position(key)
    current = start_hash
    for sibling_hex in siblings:
        sibling = bytes.fromhex(_require_hex64(
            sibling_hex,
            "SPARSE_MERKLE_SIBLING_HASH_INVALID",
        ))
        if position & 1:
            current = _internal_hash(sibling, current)
        else:
            current = _internal_hash(current, sibling)
        position >>= 1
    return current


def verify_membership_proof(proof: MerkleMembershipProof, root_sha256: str) -> bool:
    if not isinstance(proof, MerkleMembershipProof):
        raise SEDBReadOnlyAdapterError("MERKLE_MEMBERSHIP_PROOF_REQUIRED")
    root = _require_hex64(root_sha256, "MERKLE_ROOT_HASH_INVALID")
    computed = _fold_sparse_path(
        proof.key,
        _present_leaf_hash(proof.key, proof.payload),
        proof.siblings,
    )
    return computed.hex() == root


def verify_nonmembership_proof(proof: MerkleNonMembershipProof, root_sha256: str) -> bool:
    if not isinstance(proof, MerkleNonMembershipProof):
        raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_PROOF_REQUIRED")
    root = _require_hex64(root_sha256, "MERKLE_ROOT_HASH_INVALID")
    computed = _fold_sparse_path(
        proof.key,
        _EMPTY_HASHES[SPARSE_MERKLE_DEPTH],
        proof.siblings,
    )
    return computed.hex() == root


@dataclass(frozen=True, slots=True)
class EntityStateCommitment:
    entity_id: str
    legacy_snapshot_sha256: str
    entity_metadata_sha256: str
    cell_root_sha256: str
    cell_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, str) or not self.entity_id or "\x00" in self.entity_id:
            raise SEDBReadOnlyAdapterError("ENTITY_COMMITMENT_ID_INVALID")
        object.__setattr__(
            self,
            "legacy_snapshot_sha256",
            _require_hex64(self.legacy_snapshot_sha256, "ENTITY_COMMITMENT_LEGACY_HASH_INVALID"),
        )
        object.__setattr__(
            self,
            "entity_metadata_sha256",
            _require_hex64(self.entity_metadata_sha256, "ENTITY_COMMITMENT_METADATA_HASH_INVALID"),
        )
        object.__setattr__(
            self,
            "cell_root_sha256",
            _require_hex64(self.cell_root_sha256, "ENTITY_COMMITMENT_CELL_ROOT_INVALID"),
        )
        if not isinstance(self.cell_count, int) or isinstance(self.cell_count, bool) or self.cell_count < 0:
            raise SEDBReadOnlyAdapterError("ENTITY_COMMITMENT_CELL_COUNT_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ENTITY_STATE_COMMITMENT_SCHEMA,
            "entity_id": self.entity_id,
            "legacy_snapshot_sha256": self.legacy_snapshot_sha256,
            "entity_metadata_sha256": self.entity_metadata_sha256,
            "cell_root_sha256": self.cell_root_sha256,
            "cell_count": self.cell_count,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def commitment_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class FieldRegistryCommitment:
    field_root_sha256: str
    field_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field_root_sha256",
            _require_hex64(self.field_root_sha256, "FIELD_REGISTRY_COMMITMENT_ROOT_INVALID"),
        )
        if not isinstance(self.field_count, int) or isinstance(self.field_count, bool) or self.field_count < 0:
            raise SEDBReadOnlyAdapterError("FIELD_REGISTRY_COMMITMENT_COUNT_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": FIELD_REGISTRY_COMMITMENT_SCHEMA,
            "field_root_sha256": self.field_root_sha256,
            "field_count": self.field_count,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def commitment_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class CommittedEntityMetadata:
    entity_id: str
    kind: str
    label: str
    created_at: str
    updated_at: str

    @classmethod
    def from_snapshot(cls, snapshot: SEDBEntitySnapshot) -> "CommittedEntityMetadata":
        return cls(
            entity_id=snapshot.entity_id,
            kind=snapshot.kind,
            label=snapshot.label,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


def _cell_payload(cell: SEDBCellSnapshot) -> dict[str, object]:
    return {
        "field_id": cell.field.field_id,
        "value": cell.value,
        "source": cell.source,
        "confidence": cell.confidence,
        "updated_at": cell.updated_at,
    }


def _slot_cell_payload(slot: PartialFieldSlot) -> dict[str, object]:
    return {
        "field_id": slot.field.field_id,
        "value": slot.value,
        "source": slot.source,
        "confidence": slot.confidence,
        "updated_at": slot.updated_at,
    }


def _entity_cell_tree(snapshot: SEDBEntitySnapshot) -> _SparseMerkleTree:
    return _build_sparse_tree(
        (cell.field.field_id, _cell_payload(cell)) for cell in snapshot.cells
    )


def _read_field_registry(
    adapter: SEDBReadOnlyAdapter,
) -> tuple[tuple[SEDBFieldBindingSnapshot, ...], _SparseMerkleTree]:
    with adapter._connect() as conn:
        adapter._require_schema(conn)
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
        raise SEDBReadOnlyAdapterError("COMMITMENT_FIELD_REGISTRY_TOO_LARGE")
    fields = tuple(
        SEDBFieldBindingSnapshot(
            field_id=str(row["id"]),
            key=str(row["key"]),
            namespace=str(row["namespace"]),
            normalized_key=None if row["normalized_key"] is None else str(row["normalized_key"]),
            label=str(row["label"]),
            value_type=str(row["value_type"]),
            description=str(row["description"] or ""),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    )
    return fields, _build_sparse_tree((field.field_id, field.to_dict()) for field in fields)


@dataclass(frozen=True, slots=True)
class FieldClaimProof:
    field: SEDBFieldBindingSnapshot
    field_membership: MerkleMembershipProof
    cell_membership: MerkleMembershipProof | None
    cell_nonmembership: MerkleNonMembershipProof | None

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field.to_dict(),
            "field_membership": self.field_membership.to_dict(),
            "cell_membership": None if self.cell_membership is None else self.cell_membership.to_dict(),
            "cell_nonmembership": None if self.cell_nonmembership is None else self.cell_nonmembership.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProofCarryingPartialEntity:
    projection: PartialEntityProjection
    entity_metadata: CommittedEntityMetadata
    entity_commitment: EntityStateCommitment
    field_registry_commitment: FieldRegistryCommitment
    claims: tuple[FieldClaimProof, ...]

    def __post_init__(self) -> None:
        if self.projection.source_exact.entity_id != self.entity_commitment.entity_id:
            raise SEDBReadOnlyAdapterError("PROOF_ENTITY_ID_BINDING_MISMATCH")
        if self.entity_metadata.entity_id != self.entity_commitment.entity_id:
            raise SEDBReadOnlyAdapterError("PROOF_ENTITY_METADATA_BINDING_MISMATCH")
        if len(self.claims) != len(self.projection.fields):
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_CLAIM_COUNT_MISMATCH")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROOF_CARRYING_PROJECTION_SCHEMA,
            "projection": self.projection.to_dict(),
            "entity_metadata": self.entity_metadata.to_dict(),
            "entity_commitment": self.entity_commitment.to_dict(),
            "field_registry_commitment": self.field_registry_commitment.to_dict(),
            "claims": [claim.to_dict() for claim in self.claims],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def proof_bundle_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def issue_proof_carrying_projection(
    adapter: SEDBReadOnlyAdapter,
    projection: PartialEntityProjection,
) -> ProofCarryingPartialEntity:
    if not isinstance(adapter, SEDBReadOnlyAdapter):
        raise SEDBReadOnlyAdapterError("PROOF_ADAPTER_REQUIRED")
    if not isinstance(projection, PartialEntityProjection):
        raise SEDBReadOnlyAdapterError("PROOF_PARTIAL_PROJECTION_REQUIRED")

    # Issuance is correctness-first: D1 verifies the complete current snapshot.
    # D4 then derives compact commitments and proofs from that verified state.
    snapshot = adapter.read_current_exact(projection.source_exact)
    entity_metadata = CommittedEntityMetadata.from_snapshot(snapshot)
    cell_tree = _entity_cell_tree(snapshot)
    cell_by_id = {cell.field.field_id: cell for cell in snapshot.cells}

    fields, field_tree = _read_field_registry(adapter)
    field_by_id = {field.field_id: field for field in fields}

    entity_commitment = EntityStateCommitment(
        entity_id=snapshot.entity_id,
        legacy_snapshot_sha256=snapshot.sha256(),
        entity_metadata_sha256=entity_metadata.sha256(),
        cell_root_sha256=cell_tree.root.hex(),
        cell_count=len(cell_tree.leaves),
    )
    field_commitment = FieldRegistryCommitment(
        field_root_sha256=field_tree.root.hex(),
        field_count=len(field_tree.leaves),
    )

    claims: list[FieldClaimProof] = []
    for slot in projection.fields:
        field = field_by_id.get(slot.field.field_id)
        if field is None:
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_NOT_IN_REGISTRY")
        if field.key != slot.field.key:
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_KEY_BINDING_MISMATCH")
        field_membership = _membership_proof(field_tree, field.field_id)

        cell_membership: MerkleMembershipProof | None = None
        cell_nonmembership: MerkleNonMembershipProof | None = None
        cell = cell_by_id.get(field.field_id)

        if slot.state in (FieldProjectionState.PRESENT, FieldProjectionState.BLANK):
            if cell is None or _cell_payload(cell) != _slot_cell_payload(slot):
                raise SEDBReadOnlyAdapterError("PROOF_CELL_PAYLOAD_BINDING_MISMATCH")
            cell_membership = _membership_proof(cell_tree, field.field_id)
        elif slot.state in (FieldProjectionState.ABSENT, FieldProjectionState.UNKNOWN):
            if cell is not None:
                raise SEDBReadOnlyAdapterError("PROOF_NONMEMBERSHIP_CONFLICTS_WITH_CELL")
            cell_nonmembership = _nonmembership_proof(cell_tree, field.field_id)
        elif slot.state is FieldProjectionState.UNLOADED:
            # Unloaded makes no source-cell presence/absence claim.
            pass
        else:
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_STATE_UNSUPPORTED")

        claims.append(FieldClaimProof(
            field=field,
            field_membership=field_membership,
            cell_membership=cell_membership,
            cell_nonmembership=cell_nonmembership,
        ))

    return ProofCarryingPartialEntity(
        projection=projection,
        entity_metadata=entity_metadata,
        entity_commitment=entity_commitment,
        field_registry_commitment=field_commitment,
        claims=tuple(claims),
    )


def verify_proof_carrying_projection(bundle: ProofCarryingPartialEntity) -> bool:
    if not isinstance(bundle, ProofCarryingPartialEntity):
        raise SEDBReadOnlyAdapterError("PROOF_CARRYING_PROJECTION_REQUIRED")

    projection = bundle.projection
    entity_commitment = bundle.entity_commitment
    field_commitment = bundle.field_registry_commitment

    if projection.source_exact.entity_id != entity_commitment.entity_id:
        return False
    # Bridge consistency only: this does not recreate the legacy flat D1 hash.
    if projection.source_exact.state_sha256 != entity_commitment.legacy_snapshot_sha256:
        return False
    if bundle.entity_metadata.entity_id != entity_commitment.entity_id:
        return False
    if bundle.entity_metadata.sha256() != entity_commitment.entity_metadata_sha256:
        return False
    if len(bundle.claims) != len(projection.fields):
        return False

    for slot, claim in zip(projection.fields, bundle.claims, strict=True):
        if claim.field.field_id != slot.field.field_id or claim.field.key != slot.field.key:
            return False
        if claim.field_membership.key != claim.field.field_id:
            return False
        if claim.field_membership.payload != claim.field.to_dict():
            return False
        if not verify_membership_proof(
            claim.field_membership,
            field_commitment.field_root_sha256,
        ):
            return False

        if slot.state in (FieldProjectionState.PRESENT, FieldProjectionState.BLANK):
            if claim.cell_membership is None or claim.cell_nonmembership is not None:
                return False
            if claim.cell_membership.key != slot.field.field_id:
                return False
            if claim.cell_membership.payload != _slot_cell_payload(slot):
                return False
            if not verify_membership_proof(
                claim.cell_membership,
                entity_commitment.cell_root_sha256,
            ):
                return False
        elif slot.state in (FieldProjectionState.ABSENT, FieldProjectionState.UNKNOWN):
            if claim.cell_membership is not None or claim.cell_nonmembership is None:
                return False
            if claim.cell_nonmembership.key != slot.field.field_id:
                return False
            if not verify_nonmembership_proof(
                claim.cell_nonmembership,
                entity_commitment.cell_root_sha256,
            ):
                return False
            if slot.state is FieldProjectionState.UNKNOWN and (
                not isinstance(slot.unknown_reason, str) or not slot.unknown_reason.strip()
            ):
                return False
        elif slot.state is FieldProjectionState.UNLOADED:
            if claim.cell_membership is not None or claim.cell_nonmembership is not None:
                return False
        else:
            return False

    return True

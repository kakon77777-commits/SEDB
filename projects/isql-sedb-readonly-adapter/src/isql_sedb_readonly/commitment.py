from __future__ import annotations

from bisect import bisect_left
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

_EMPTY_ROOT = hashlib.sha256(b"\x02empty").digest()


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


def _leaf_hash(key: str, payload: object) -> bytes:
    if not isinstance(key, str) or not key:
        raise SEDBReadOnlyAdapterError("COMMITMENT_LEAF_KEY_INVALID")
    return hashlib.sha256(
        b"\x00" + _canonical_json_bytes({"key": key, "payload": payload})
    ).digest()


def _internal_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _canonical_leaves(leaves: Iterable[tuple[str, object]]) -> tuple[tuple[str, object], ...]:
    rows = tuple(sorted(leaves, key=lambda row: row[0]))
    keys = [key for key, _ in rows]
    if len(keys) != len(set(keys)):
        raise SEDBReadOnlyAdapterError("COMMITMENT_DUPLICATE_LEAF_KEY")
    for key in keys:
        if not isinstance(key, str) or not key or "\x00" in key:
            raise SEDBReadOnlyAdapterError("COMMITMENT_LEAF_KEY_INVALID")
    return rows


def _merkle_root(leaves: tuple[tuple[str, object], ...]) -> bytes:
    if not leaves:
        return _EMPTY_ROOT
    level = [_leaf_hash(key, payload) for key, payload in leaves]
    while len(level) > 1:
        next_level: list[bytes] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(_internal_hash(left, right))
        level = next_level
    return level[0]


def _expected_sibling_count(count: int) -> int:
    levels = 0
    size = count
    while size > 1:
        levels += 1
        size = (size + 1) // 2
    return levels


@dataclass(frozen=True, slots=True)
class MerkleMembershipProof:
    key: str
    payload: object
    index: int
    count: int
    siblings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key or "\x00" in self.key:
            raise SEDBReadOnlyAdapterError("MERKLE_PROOF_KEY_INVALID")
        _canonical_json_bytes(self.payload)
        if not isinstance(self.index, int) or isinstance(self.index, bool) or self.index < 0:
            raise SEDBReadOnlyAdapterError("MERKLE_PROOF_INDEX_INVALID")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count <= 0:
            raise SEDBReadOnlyAdapterError("MERKLE_PROOF_COUNT_INVALID")
        if self.index >= self.count:
            raise SEDBReadOnlyAdapterError("MERKLE_PROOF_INDEX_OUT_OF_RANGE")
        if len(self.siblings) != _expected_sibling_count(self.count):
            raise SEDBReadOnlyAdapterError("MERKLE_PROOF_SIBLING_COUNT_INVALID")
        for sibling in self.siblings:
            _require_hex64(sibling, "MERKLE_PROOF_SIBLING_HASH_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "payload": self.payload,
            "index": self.index,
            "count": self.count,
            "siblings": list(self.siblings),
        }


def _membership_proof(
    leaves: tuple[tuple[str, object], ...],
    index: int,
) -> MerkleMembershipProof:
    if not leaves or not 0 <= index < len(leaves):
        raise SEDBReadOnlyAdapterError("MERKLE_PROOF_INDEX_OUT_OF_RANGE")
    level = [_leaf_hash(key, payload) for key, payload in leaves]
    current_index = index
    siblings: list[str] = []
    while len(level) > 1:
        if current_index % 2 == 0:
            sibling_index = current_index + 1
            sibling = level[sibling_index] if sibling_index < len(level) else level[current_index]
        else:
            sibling = level[current_index - 1]
        siblings.append(sibling.hex())

        next_level: list[bytes] = []
        for pos in range(0, len(level), 2):
            left = level[pos]
            right = level[pos + 1] if pos + 1 < len(level) else left
            next_level.append(_internal_hash(left, right))
        current_index //= 2
        level = next_level

    key, payload = leaves[index]
    return MerkleMembershipProof(
        key=key,
        payload=payload,
        index=index,
        count=len(leaves),
        siblings=tuple(siblings),
    )


def verify_membership_proof(proof: MerkleMembershipProof, root_sha256: str) -> bool:
    if not isinstance(proof, MerkleMembershipProof):
        raise SEDBReadOnlyAdapterError("MERKLE_MEMBERSHIP_PROOF_REQUIRED")
    root = bytes.fromhex(_require_hex64(root_sha256, "MERKLE_ROOT_HASH_INVALID"))
    current = _leaf_hash(proof.key, proof.payload)
    index = proof.index
    count = proof.count
    for sibling_hex in proof.siblings:
        sibling = bytes.fromhex(sibling_hex)
        if index % 2 == 0:
            if index + 1 >= count and sibling != current:
                return False
            current = _internal_hash(current, sibling)
        else:
            current = _internal_hash(sibling, current)
        index //= 2
        count = (count + 1) // 2
    return count == 1 and current == root


@dataclass(frozen=True, slots=True)
class MerkleNonMembershipProof:
    key: str
    count: int
    predecessor: MerkleMembershipProof | None
    successor: MerkleMembershipProof | None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key or "\x00" in self.key:
            raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_KEY_INVALID")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count < 0:
            raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_COUNT_INVALID")
        if self.count == 0:
            if self.predecessor is not None or self.successor is not None:
                raise SEDBReadOnlyAdapterError("MERKLE_EMPTY_NONMEMBERSHIP_NEIGHBOR_FORBIDDEN")
        elif self.predecessor is None and self.successor is None:
            raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_NEIGHBOR_REQUIRED")

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "count": self.count,
            "predecessor": None if self.predecessor is None else self.predecessor.to_dict(),
            "successor": None if self.successor is None else self.successor.to_dict(),
        }


def _nonmembership_proof(
    leaves: tuple[tuple[str, object], ...],
    key: str,
) -> MerkleNonMembershipProof:
    keys = [leaf_key for leaf_key, _ in leaves]
    pos = bisect_left(keys, key)
    if pos < len(keys) and keys[pos] == key:
        raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_KEY_EXISTS")
    predecessor = _membership_proof(leaves, pos - 1) if pos > 0 else None
    successor = _membership_proof(leaves, pos) if pos < len(leaves) else None
    return MerkleNonMembershipProof(
        key=key,
        count=len(leaves),
        predecessor=predecessor,
        successor=successor,
    )


def verify_nonmembership_proof(proof: MerkleNonMembershipProof, root_sha256: str) -> bool:
    if not isinstance(proof, MerkleNonMembershipProof):
        raise SEDBReadOnlyAdapterError("MERKLE_NONMEMBERSHIP_PROOF_REQUIRED")
    root_sha256 = _require_hex64(root_sha256, "MERKLE_ROOT_HASH_INVALID")
    if proof.count == 0:
        return root_sha256 == _EMPTY_ROOT.hex()

    predecessor = proof.predecessor
    successor = proof.successor
    if predecessor is not None:
        if predecessor.count != proof.count or not verify_membership_proof(predecessor, root_sha256):
            return False
        if not predecessor.key < proof.key:
            return False
    if successor is not None:
        if successor.count != proof.count or not verify_membership_proof(successor, root_sha256):
            return False
        if not proof.key < successor.key:
            return False

    if predecessor is None:
        return successor is not None and successor.index == 0
    if successor is None:
        return predecessor.index == proof.count - 1
    return successor.index == predecessor.index + 1


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


def _entity_cell_leaves(snapshot: SEDBEntitySnapshot) -> tuple[tuple[str, object], ...]:
    return _canonical_leaves(
        (cell.field.field_id, _cell_payload(cell)) for cell in snapshot.cells
    )


def _read_field_registry(
    adapter: SEDBReadOnlyAdapter,
) -> tuple[tuple[SEDBFieldBindingSnapshot, ...], tuple[tuple[str, object], ...]]:
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
    leaves = _canonical_leaves((field.field_id, field.to_dict()) for field in fields)
    return fields, leaves


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
    cell_leaves = _entity_cell_leaves(snapshot)
    cell_keys = [key for key, _ in cell_leaves]
    cell_by_id = {cell.field.field_id: cell for cell in snapshot.cells}

    fields, field_leaves = _read_field_registry(adapter)
    field_by_id = {field.field_id: field for field in fields}
    field_keys = [key for key, _ in field_leaves]

    entity_commitment = EntityStateCommitment(
        entity_id=snapshot.entity_id,
        legacy_snapshot_sha256=snapshot.sha256(),
        entity_metadata_sha256=entity_metadata.sha256(),
        cell_root_sha256=_merkle_root(cell_leaves).hex(),
        cell_count=len(cell_leaves),
    )
    field_commitment = FieldRegistryCommitment(
        field_root_sha256=_merkle_root(field_leaves).hex(),
        field_count=len(field_leaves),
    )

    claims: list[FieldClaimProof] = []
    for slot in projection.fields:
        field = field_by_id.get(slot.field.field_id)
        if field is None:
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_NOT_IN_REGISTRY")
        if field.key != slot.field.key:
            raise SEDBReadOnlyAdapterError("PROOF_FIELD_KEY_BINDING_MISMATCH")
        field_index = bisect_left(field_keys, field.field_id)
        field_membership = _membership_proof(field_leaves, field_index)

        cell_membership: MerkleMembershipProof | None = None
        cell_nonmembership: MerkleNonMembershipProof | None = None
        cell = cell_by_id.get(field.field_id)

        if slot.state in (FieldProjectionState.PRESENT, FieldProjectionState.BLANK):
            if cell is None or _cell_payload(cell) != _slot_cell_payload(slot):
                raise SEDBReadOnlyAdapterError("PROOF_CELL_PAYLOAD_BINDING_MISMATCH")
            cell_index = bisect_left(cell_keys, field.field_id)
            cell_membership = _membership_proof(cell_leaves, cell_index)
        elif slot.state in (FieldProjectionState.ABSENT, FieldProjectionState.UNKNOWN):
            if cell is not None:
                raise SEDBReadOnlyAdapterError("PROOF_NONMEMBERSHIP_CONFLICTS_WITH_CELL")
            cell_nonmembership = _nonmembership_proof(cell_leaves, field.field_id)
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
        if claim.field_membership.count != field_commitment.field_count:
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
            if claim.cell_membership.count != entity_commitment.cell_count:
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
            if claim.cell_nonmembership.count != entity_commitment.cell_count:
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

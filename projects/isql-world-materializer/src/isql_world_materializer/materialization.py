from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .placement import ExactContentIdentity, PlacementError, PlacementPolicy
from .range_fetch import VerifiedRangeFetch, VerifiedRangeFetcher
from .range_proof import RangeCommitment, RangeProofIndex

MATERIALIZATION_MANIFEST_SCHEMA = "isql-world-materialization-manifest/v0.1"


class MaterializationError(PlacementError):
    pass


def _identity_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise MaterializationError(code)
    return value


def _hex64(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise MaterializationError(code)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise MaterializationError(code) from exc
    if len(raw) != 32:
        raise MaterializationError(code)
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MaterializationError("MATERIALIZATION_NOT_CANONICAL_JSON") from exc


@dataclass(frozen=True, slots=True)
class MaterializationArtifactBinding:
    artifact_ref: str
    source_identity: ExactContentIdentity
    range_commitment_sha256: str
    size_bytes: int
    chunk_size: int
    chunk_count: int
    chunk_root_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_ref", _identity_text(self.artifact_ref, "MATERIALIZATION_ARTIFACT_REF_INVALID"))
        if not isinstance(self.source_identity, ExactContentIdentity):
            raise MaterializationError("MATERIALIZATION_SOURCE_IDENTITY_REQUIRED")
        object.__setattr__(self, "range_commitment_sha256", _hex64(self.range_commitment_sha256, "MATERIALIZATION_RANGE_COMMITMENT_HASH_INVALID"))
        object.__setattr__(self, "chunk_root_sha256", _hex64(self.chunk_root_sha256, "MATERIALIZATION_CHUNK_ROOT_INVALID"))
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise MaterializationError("MATERIALIZATION_SIZE_INVALID")
        if type(self.chunk_size) is not int or self.chunk_size <= 0:
            raise MaterializationError("MATERIALIZATION_CHUNK_SIZE_INVALID")
        expected_count = max(1, (self.size_bytes + self.chunk_size - 1) // self.chunk_size)
        if self.chunk_count != expected_count:
            raise MaterializationError("MATERIALIZATION_CHUNK_COUNT_INVALID")

    @classmethod
    def from_commitment(cls, artifact_ref: str, commitment: RangeCommitment) -> "MaterializationArtifactBinding":
        if not isinstance(commitment, RangeCommitment):
            raise TypeError("commitment must be RangeCommitment")
        return cls(
            artifact_ref=artifact_ref,
            source_identity=commitment.source_identity,
            range_commitment_sha256=commitment.commitment_sha256,
            size_bytes=commitment.size_bytes,
            chunk_size=commitment.chunk_size,
            chunk_count=commitment.chunk_count,
            chunk_root_sha256=commitment.chunk_root_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_ref": self.artifact_ref,
            "source_identity": {
                "algorithm": self.source_identity.algorithm,
                "digest": self.source_identity.digest,
            },
            "range_commitment_sha256": self.range_commitment_sha256,
            "size_bytes": self.size_bytes,
            "chunk_size": self.chunk_size,
            "chunk_count": self.chunk_count,
            "chunk_root_sha256": self.chunk_root_sha256,
        }


@dataclass(frozen=True, slots=True)
class WorldMaterializationManifest:
    world_id: str
    world_head_manifest_sha256: str
    profile_id: str
    artifacts: tuple[MaterializationArtifactBinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", _identity_text(self.world_id, "MATERIALIZATION_WORLD_ID_INVALID"))
        object.__setattr__(self, "world_head_manifest_sha256", _hex64(self.world_head_manifest_sha256, "MATERIALIZATION_WORLD_HEAD_HASH_INVALID"))
        object.__setattr__(self, "profile_id", _identity_text(self.profile_id, "MATERIALIZATION_PROFILE_ID_INVALID"))
        artifacts = tuple(self.artifacts)
        if any(not isinstance(binding, MaterializationArtifactBinding) for binding in artifacts):
            raise MaterializationError("MATERIALIZATION_BINDING_INVALID")
        refs = [binding.artifact_ref for binding in artifacts]
        if len(set(refs)) != len(refs):
            raise MaterializationError("MATERIALIZATION_ARTIFACT_REF_DUPLICATE")
        object.__setattr__(self, "artifacts", tuple(sorted(artifacts, key=lambda binding: binding.artifact_ref)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": MATERIALIZATION_MANIFEST_SCHEMA,
            "world_id": self.world_id,
            "world_head_manifest_sha256": self.world_head_manifest_sha256,
            "profile_id": self.profile_id,
            "artifacts": [binding.to_dict() for binding in self.artifacts],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def binding(self, artifact_ref: str) -> MaterializationArtifactBinding:
        artifact_ref = _identity_text(artifact_ref, "MATERIALIZATION_ARTIFACT_REF_INVALID")
        for binding in self.artifacts:
            if binding.artifact_ref == artifact_ref:
                return binding
        raise MaterializationError("MATERIALIZATION_ARTIFACT_NOT_FOUND")


@dataclass(frozen=True, slots=True)
class MaterializationManifestVerification:
    manifest_sha256: str
    manifest_hash_valid: bool
    world_head_binding_valid: bool
    artifact_commitments_valid: bool

    @property
    def valid(self) -> bool:
        return self.manifest_hash_valid and self.world_head_binding_valid and self.artifact_commitments_valid


def build_materialization_manifest(
    *,
    world_id: str,
    world_head_manifest_sha256: str,
    profile_id: str,
    commitments: Mapping[str, RangeCommitment],
) -> WorldMaterializationManifest:
    bindings = tuple(
        MaterializationArtifactBinding.from_commitment(artifact_ref, commitment)
        for artifact_ref, commitment in commitments.items()
    )
    return WorldMaterializationManifest(world_id, world_head_manifest_sha256, profile_id, bindings)


def _binding_matches_commitment(binding: MaterializationArtifactBinding, commitment: RangeCommitment) -> bool:
    return (
        binding.source_identity == commitment.source_identity
        and binding.range_commitment_sha256 == commitment.commitment_sha256
        and binding.size_bytes == commitment.size_bytes
        and binding.chunk_size == commitment.chunk_size
        and binding.chunk_count == commitment.chunk_count
        and binding.chunk_root_sha256 == commitment.chunk_root_sha256
    )


def verify_materialization_manifest(
    manifest: WorldMaterializationManifest,
    *,
    expected_manifest_sha256: str,
    expected_world_head_manifest_sha256: str,
    proof_indexes: Mapping[str, RangeProofIndex],
) -> MaterializationManifestVerification:
    if not isinstance(manifest, WorldMaterializationManifest):
        raise TypeError("manifest must be WorldMaterializationManifest")
    expected_manifest = _hex64(expected_manifest_sha256, "MATERIALIZATION_EXPECTED_HASH_INVALID")
    expected_world_head = _hex64(expected_world_head_manifest_sha256, "MATERIALIZATION_EXPECTED_WORLD_HEAD_INVALID")
    manifest_hash_valid = manifest.manifest_sha256 == expected_manifest
    world_head_binding_valid = manifest.world_head_manifest_sha256 == expected_world_head

    required_refs = {binding.artifact_ref for binding in manifest.artifacts}
    artifact_commitments_valid = required_refs.issubset(set(proof_indexes))
    if artifact_commitments_valid:
        for binding in manifest.artifacts:
            index = proof_indexes.get(binding.artifact_ref)
            if not isinstance(index, RangeProofIndex):
                artifact_commitments_valid = False
                break
            try:
                commitment = index.commitment()
            except Exception:
                artifact_commitments_valid = False
                break
            if not _binding_matches_commitment(binding, commitment):
                artifact_commitments_valid = False
                break

    return MaterializationManifestVerification(
        manifest_sha256=manifest.manifest_sha256,
        manifest_hash_valid=manifest_hash_valid,
        world_head_binding_valid=world_head_binding_valid,
        artifact_commitments_valid=artifact_commitments_valid,
    )


class MaterializationRangeReader:
    """Resolve an artifact binding and delegate only after manifest/proof validation."""

    def __init__(
        self,
        manifest: WorldMaterializationManifest,
        *,
        expected_manifest_sha256: str,
        expected_world_head_manifest_sha256: str,
        proof_indexes: Mapping[str, RangeProofIndex],
        range_fetcher: VerifiedRangeFetcher,
    ):
        if not isinstance(range_fetcher, VerifiedRangeFetcher):
            raise TypeError("range_fetcher must be VerifiedRangeFetcher")
        verification = verify_materialization_manifest(
            manifest,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_world_head_manifest_sha256=expected_world_head_manifest_sha256,
            proof_indexes=proof_indexes,
        )
        if not verification.valid:
            raise MaterializationError("MATERIALIZATION_MANIFEST_VERIFICATION_FAILED")
        self.manifest = manifest
        self.proof_indexes = dict(proof_indexes)
        self.range_fetcher = range_fetcher

    def fetch_range(
        self,
        artifact_ref: str,
        *,
        offset: int,
        length: int,
        policy: PlacementPolicy | None = None,
    ) -> VerifiedRangeFetch:
        binding = self.manifest.binding(artifact_ref)
        proof_index = self.proof_indexes[binding.artifact_ref]
        return self.range_fetcher.fetch_range(
            binding.source_identity,
            proof_index,
            expected_commitment_sha256=binding.range_commitment_sha256,
            offset=offset,
            length=length,
            policy=policy,
        )

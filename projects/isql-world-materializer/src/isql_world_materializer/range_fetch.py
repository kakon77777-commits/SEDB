from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .fetch import FetchAttempt, RangeFetchProvider
from .placement import ExactContentIdentity, PhysicalPlacementResolver, PlacementError, PlacementPolicy, PlacementRecord
from .range_proof import RangeProofError, RangeProofIndex, verify_chunk_proof


class VerifiedRangeFetchError(PlacementError):
    def __init__(self, code: str, attempts: tuple[FetchAttempt, ...] = ()):
        self.attempts = attempts
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class VerifiedRangeFetch:
    identity: ExactContentIdentity
    range_commitment_sha256: str
    placement: PlacementRecord
    offset: int
    length: int
    content: bytes
    chunk_indices: tuple[int, ...]
    attempted_placement_ids: tuple[str, ...]


def _expected_hash(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise VerifiedRangeFetchError("RANGE_FETCH_EXPECTED_COMMITMENT_INVALID")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise VerifiedRangeFetchError("RANGE_FETCH_EXPECTED_COMMITMENT_INVALID") from exc
    if len(raw) != 32:
        raise VerifiedRangeFetchError("RANGE_FETCH_EXPECTED_COMMITMENT_INVALID")
    return value


class VerifiedRangeFetcher:
    """Fetch only covering chunks and verify each against one trusted range commitment."""

    def __init__(
        self,
        resolver: PhysicalPlacementResolver,
        providers: Mapping[str, RangeFetchProvider],
    ):
        if not isinstance(resolver, PhysicalPlacementResolver):
            raise TypeError("resolver must be PhysicalPlacementResolver")
        self.resolver = resolver
        normalized: dict[str, RangeFetchProvider] = {}
        for provider_id, provider in providers.items():
            if not isinstance(provider_id, str) or not provider_id or provider_id != provider_id.strip() or "\x00" in provider_id:
                raise PlacementError("RANGE_FETCH_PROVIDER_ID_INVALID")
            if not hasattr(provider, "read_range"):
                raise PlacementError("RANGE_FETCH_PROVIDER_INVALID")
            normalized[provider_id] = provider
        self.providers = normalized

    def fetch_range(
        self,
        identity: ExactContentIdentity,
        proof_index: RangeProofIndex,
        *,
        expected_commitment_sha256: str,
        offset: int,
        length: int,
        policy: PlacementPolicy | None = None,
    ) -> VerifiedRangeFetch:
        if not isinstance(identity, ExactContentIdentity):
            raise TypeError("identity must be ExactContentIdentity")
        if not isinstance(proof_index, RangeProofIndex):
            raise TypeError("proof_index must be RangeProofIndex")
        expected_commitment = _expected_hash(expected_commitment_sha256)
        if type(offset) is not int or offset < 0:
            raise VerifiedRangeFetchError("RANGE_FETCH_OFFSET_INVALID")
        if type(length) is not int or length <= 0:
            raise VerifiedRangeFetchError("RANGE_FETCH_LENGTH_INVALID")

        try:
            commitment = proof_index.commitment()
        except RangeProofError as exc:
            raise VerifiedRangeFetchError("RANGE_FETCH_PROOF_INDEX_INVALID") from exc
        if commitment.commitment_sha256 != expected_commitment:
            raise VerifiedRangeFetchError("RANGE_FETCH_COMMITMENT_MISMATCH")
        if commitment.source_identity != identity:
            raise VerifiedRangeFetchError("RANGE_FETCH_SOURCE_IDENTITY_MISMATCH")
        if offset + length > commitment.size_bytes:
            raise VerifiedRangeFetchError("RANGE_FETCH_OUT_OF_BOUNDS")

        start_index = offset // commitment.chunk_size
        end_index = (offset + length - 1) // commitment.chunk_size
        chunk_indices = tuple(range(start_index, end_index + 1))
        try:
            proofs = {index: proof_index.proof(index) for index in chunk_indices}
        except RangeProofError as exc:
            raise VerifiedRangeFetchError("RANGE_FETCH_PROOF_UNAVAILABLE") from exc

        candidates = self.resolver.resolve(identity, policy)
        if not candidates:
            raise VerifiedRangeFetchError("RANGE_FETCH_NO_PLACEMENT")

        attempts: list[FetchAttempt] = []
        attempted_ids: list[str] = []
        for placement in candidates:
            attempted_ids.append(placement.placement_id)
            if placement.size_bytes != commitment.size_bytes:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "RANGE_FETCH_PLACEMENT_SIZE_MISMATCH"))
                continue
            provider = self.providers.get(placement.provider_id)
            if provider is None:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "RANGE_FETCH_PROVIDER_UNAVAILABLE"))
                continue

            chunks: list[bytes] = []
            failed_code: str | None = None
            for index in chunk_indices:
                proof = proofs[index]
                chunk_offset = index * commitment.chunk_size
                try:
                    block = provider.read_range(
                        placement.object_key,
                        offset=chunk_offset,
                        length=proof.chunk_length,
                        max_bytes=proof.chunk_length,
                    )
                except PlacementError as exc:
                    failed_code = exc.code
                    break
                except Exception:
                    failed_code = "RANGE_FETCH_PROVIDER_ERROR"
                    break
                if len(block) != proof.chunk_length:
                    failed_code = "RANGE_FETCH_CHUNK_SIZE_MISMATCH"
                    break
                if not verify_chunk_proof(commitment, block, proof):
                    failed_code = "RANGE_FETCH_CHUNK_PROOF_INVALID"
                    break
                chunks.append(block)

            if failed_code is not None:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, failed_code))
                continue

            joined = b"".join(chunks)
            relative_start = offset - start_index * commitment.chunk_size
            selected = joined[relative_start : relative_start + length]
            if len(selected) != length:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "RANGE_FETCH_RESULT_SIZE_MISMATCH"))
                continue
            return VerifiedRangeFetch(
                identity=identity,
                range_commitment_sha256=commitment.commitment_sha256,
                placement=placement,
                offset=offset,
                length=length,
                content=selected,
                chunk_indices=chunk_indices,
                attempted_placement_ids=tuple(attempted_ids),
            )

        raise VerifiedRangeFetchError("RANGE_FETCH_ALL_PLACEMENTS_FAILED", tuple(attempts))

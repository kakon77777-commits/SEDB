from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import stat
from typing import Mapping, Protocol

from .placement import (
    ExactContentIdentity,
    PhysicalPlacementResolver,
    PlacementError,
    PlacementPolicy,
    PlacementRecord,
)


class ProviderReadError(PlacementError):
    pass


class FetchProvider(Protocol):
    def read(self, object_key: str, *, max_bytes: int | None = None) -> bytes: ...


class RangeFetchProvider(FetchProvider, Protocol):
    def read_range(
        self,
        object_key: str,
        *,
        offset: int,
        length: int,
        max_bytes: int | None = None,
    ) -> bytes: ...


class LocalDirectoryProvider:
    """Read-only local provider used by D11/D12 experimental fetchers."""

    def __init__(self, root: str | Path):
        root_path = Path(root)
        try:
            resolved = root_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProviderReadError("PROVIDER_ROOT_UNAVAILABLE", str(root_path)) from exc
        if not resolved.is_dir():
            raise ProviderReadError("PROVIDER_ROOT_NOT_DIRECTORY", str(root_path))
        self.root = resolved

    @staticmethod
    def _parts(object_key: str) -> tuple[str, ...]:
        if not isinstance(object_key, str) or not object_key or "\x00" in object_key:
            raise ProviderReadError("PROVIDER_OBJECT_KEY_INVALID")
        if "\\" in object_key:
            raise ProviderReadError("PROVIDER_OBJECT_KEY_INVALID")
        path = PurePosixPath(object_key)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ProviderReadError("PROVIDER_OBJECT_KEY_INVALID")
        if path.as_posix() != object_key:
            raise ProviderReadError("PROVIDER_OBJECT_KEY_NONCANONICAL")
        return tuple(path.parts)

    def _resolved_regular(self, object_key: str) -> tuple[Path, int]:
        parts = self._parts(object_key)
        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProviderReadError("PROVIDER_OBJECT_UNAVAILABLE", object_key) from exc
        if not resolved.is_relative_to(self.root):
            raise ProviderReadError("PROVIDER_OBJECT_ESCAPE", object_key)
        try:
            info = resolved.stat()
        except OSError as exc:
            raise ProviderReadError("PROVIDER_OBJECT_UNAVAILABLE", object_key) from exc
        if not stat.S_ISREG(info.st_mode):
            raise ProviderReadError("PROVIDER_OBJECT_NOT_REGULAR", object_key)
        return resolved, info.st_size

    def read(self, object_key: str, *, max_bytes: int | None = None) -> bytes:
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise ProviderReadError("PROVIDER_MAX_BYTES_INVALID")
        resolved, size = self._resolved_regular(object_key)
        if max_bytes is not None and size > max_bytes:
            raise ProviderReadError("PROVIDER_OBJECT_TOO_LARGE", object_key)
        try:
            with resolved.open("rb") as stream:
                content = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        except OSError as exc:
            raise ProviderReadError("PROVIDER_OBJECT_READ_FAILED", object_key) from exc
        if max_bytes is not None and len(content) > max_bytes:
            raise ProviderReadError("PROVIDER_OBJECT_TOO_LARGE", object_key)
        return content

    def read_range(
        self,
        object_key: str,
        *,
        offset: int,
        length: int,
        max_bytes: int | None = None,
    ) -> bytes:
        if type(offset) is not int or offset < 0:
            raise ProviderReadError("PROVIDER_RANGE_OFFSET_INVALID")
        if type(length) is not int or length < 0:
            raise ProviderReadError("PROVIDER_RANGE_LENGTH_INVALID")
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise ProviderReadError("PROVIDER_MAX_BYTES_INVALID")
        if max_bytes is not None and length > max_bytes:
            raise ProviderReadError("PROVIDER_RANGE_TOO_LARGE")
        resolved, size = self._resolved_regular(object_key)
        if offset > size or offset + length > size:
            raise ProviderReadError("PROVIDER_RANGE_OUT_OF_BOUNDS")
        try:
            with resolved.open("rb") as stream:
                stream.seek(offset)
                content = stream.read(length)
        except OSError as exc:
            raise ProviderReadError("PROVIDER_OBJECT_READ_FAILED", object_key) from exc
        if len(content) != length:
            raise ProviderReadError("PROVIDER_RANGE_SHORT_READ")
        return content


@dataclass(frozen=True, slots=True)
class FetchAttempt:
    placement_id: str
    provider_id: str
    code: str


@dataclass(frozen=True, slots=True)
class VerifiedFetch:
    identity: ExactContentIdentity
    placement: PlacementRecord
    content: bytes
    attempted_placement_ids: tuple[str, ...]


class VerifiedFetchError(PlacementError):
    def __init__(self, code: str, attempts: tuple[FetchAttempt, ...] = ()):
        self.attempts = attempts
        super().__init__(code)


class VerifiedFetcher:
    """Resolve placements, fetch bytes, and verify the requested exact identity."""

    def __init__(
        self,
        resolver: PhysicalPlacementResolver,
        providers: Mapping[str, FetchProvider],
    ):
        if not isinstance(resolver, PhysicalPlacementResolver):
            raise TypeError("resolver must be PhysicalPlacementResolver")
        self.resolver = resolver
        normalized: dict[str, FetchProvider] = {}
        for provider_id, provider in providers.items():
            if not isinstance(provider_id, str) or not provider_id or provider_id != provider_id.strip() or "\x00" in provider_id:
                raise PlacementError("FETCH_PROVIDER_ID_INVALID")
            if provider_id in normalized:
                raise PlacementError("FETCH_PROVIDER_ID_DUPLICATE")
            if not hasattr(provider, "read"):
                raise PlacementError("FETCH_PROVIDER_INVALID")
            normalized[provider_id] = provider
        self.providers = normalized

    @staticmethod
    def _digest(identity: ExactContentIdentity, content: bytes) -> str:
        if identity.algorithm != "sha256":
            raise VerifiedFetchError("FETCH_IDENTITY_ALGORITHM_UNSUPPORTED")
        return hashlib.sha256(content).hexdigest()

    def fetch(
        self,
        identity: ExactContentIdentity,
        policy: PlacementPolicy | None = None,
    ) -> VerifiedFetch:
        if not isinstance(identity, ExactContentIdentity):
            raise TypeError("identity must be ExactContentIdentity")
        candidates = self.resolver.resolve(identity, policy)
        if not candidates:
            raise VerifiedFetchError("FETCH_NO_PLACEMENT")

        attempts: list[FetchAttempt] = []
        attempted_ids: list[str] = []
        for placement in candidates:
            attempted_ids.append(placement.placement_id)
            provider = self.providers.get(placement.provider_id)
            if provider is None:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "FETCH_PROVIDER_UNAVAILABLE"))
                continue
            try:
                content = provider.read(placement.object_key, max_bytes=placement.size_bytes)
            except PlacementError as exc:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, exc.code))
                continue
            except Exception:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "FETCH_PROVIDER_ERROR"))
                continue

            if len(content) != placement.size_bytes:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "FETCH_SIZE_MISMATCH"))
                continue
            if self._digest(identity, content) != identity.digest:
                attempts.append(FetchAttempt(placement.placement_id, placement.provider_id, "FETCH_DIGEST_MISMATCH"))
                continue
            return VerifiedFetch(identity, placement, content, tuple(attempted_ids))

        raise VerifiedFetchError("FETCH_ALL_PLACEMENTS_FAILED", tuple(attempts))

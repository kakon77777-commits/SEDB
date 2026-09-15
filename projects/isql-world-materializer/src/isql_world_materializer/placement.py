from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, Path
import sqlite3
from typing import Iterable


class PlacementError(ValueError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _identity_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or value != value.strip():
        raise PlacementError(code)
    return value


def _digest_hex(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise PlacementError(code)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise PlacementError(code) from exc
    if len(raw) != 32:
        raise PlacementError(code)
    return value


def _object_key(value: object) -> str:
    value = _identity_text(value, "PLACEMENT_OBJECT_KEY_INVALID")
    if "\\" in value:
        raise PlacementError("PLACEMENT_OBJECT_KEY_INVALID", "object keys use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PlacementError("PLACEMENT_OBJECT_KEY_INVALID", "object key must be normalized and relative")
    normalized = path.as_posix()
    if normalized != value:
        raise PlacementError("PLACEMENT_OBJECT_KEY_NONCANONICAL")
    return normalized


@dataclass(frozen=True, slots=True)
class ExactContentIdentity:
    algorithm: str
    digest: str

    def __post_init__(self) -> None:
        algorithm = _identity_text(self.algorithm, "EXACT_IDENTITY_ALGORITHM_INVALID")
        if algorithm != "sha256":
            raise PlacementError("EXACT_IDENTITY_ALGORITHM_UNSUPPORTED")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "digest", _digest_hex(self.digest, "EXACT_IDENTITY_DIGEST_INVALID"))

    @property
    def canonical_ref(self) -> str:
        return f"{self.algorithm}:{self.digest}"


@dataclass(frozen=True, slots=True)
class PlacementRecord:
    identity: ExactContentIdentity
    placement_id: str
    provider_id: str
    object_key: str
    size_bytes: int
    region: str
    tier: str
    priority: int = 100
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ExactContentIdentity):
            raise PlacementError("PLACEMENT_IDENTITY_REQUIRED")
        object.__setattr__(self, "placement_id", _identity_text(self.placement_id, "PLACEMENT_ID_INVALID"))
        object.__setattr__(self, "provider_id", _identity_text(self.provider_id, "PLACEMENT_PROVIDER_ID_INVALID"))
        object.__setattr__(self, "object_key", _object_key(self.object_key))
        object.__setattr__(self, "region", _identity_text(self.region, "PLACEMENT_REGION_INVALID"))
        object.__setattr__(self, "tier", _identity_text(self.tier, "PLACEMENT_TIER_INVALID"))
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise PlacementError("PLACEMENT_SIZE_INVALID")
        if type(self.priority) is not int or self.priority < 0:
            raise PlacementError("PLACEMENT_PRIORITY_INVALID")
        if type(self.enabled) is not bool:
            raise PlacementError("PLACEMENT_ENABLED_INVALID")


@dataclass(frozen=True, slots=True)
class PlacementPolicy:
    preferred_region: str | None = None
    allowed_provider_ids: tuple[str, ...] = ()
    allowed_tiers: tuple[str, ...] = ()
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.preferred_region is not None:
            object.__setattr__(
                self,
                "preferred_region",
                _identity_text(self.preferred_region, "PLACEMENT_POLICY_REGION_INVALID"),
            )
        providers = tuple(self.allowed_provider_ids)
        tiers = tuple(self.allowed_tiers)
        if len(set(providers)) != len(providers) or len(set(tiers)) != len(tiers):
            raise PlacementError("PLACEMENT_POLICY_DUPLICATE_FILTER")
        for provider in providers:
            _identity_text(provider, "PLACEMENT_POLICY_PROVIDER_INVALID")
        for tier in tiers:
            _identity_text(tier, "PLACEMENT_POLICY_TIER_INVALID")
        object.__setattr__(self, "allowed_provider_ids", providers)
        object.__setattr__(self, "allowed_tiers", tiers)
        if self.max_bytes is not None and (type(self.max_bytes) is not int or self.max_bytes < 0):
            raise PlacementError("PLACEMENT_POLICY_MAX_BYTES_INVALID")


class PlacementCatalog:
    """Derived mutable placement catalog keyed by exact content identity.

    Placement changes do not alter exact content identity. The catalog is not a
    canonical state source and can be rebuilt from external placement metadata.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _initialize(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS placements (
                    algorithm TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    placement_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    region TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    PRIMARY KEY (algorithm, digest, placement_id)
                );
                CREATE INDEX IF NOT EXISTS idx_placements_identity
                    ON placements(algorithm, digest, enabled, priority, placement_id);
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PlacementRecord:
        return PlacementRecord(
            identity=ExactContentIdentity(str(row["algorithm"]), str(row["digest"])),
            placement_id=str(row["placement_id"]),
            provider_id=str(row["provider_id"]),
            object_key=str(row["object_key"]),
            size_bytes=int(row["size_bytes"]),
            region=str(row["region"]),
            tier=str(row["tier"]),
            priority=int(row["priority"]),
            enabled=bool(row["enabled"]),
        )

    def register(self, record: PlacementRecord, *, replace: bool = False) -> None:
        if not isinstance(record, PlacementRecord):
            raise TypeError("record must be PlacementRecord")
        with self._connect() as con:
            existing = con.execute(
                """SELECT * FROM placements
                   WHERE algorithm=? AND digest=? AND placement_id=?""",
                (record.identity.algorithm, record.identity.digest, record.placement_id),
            ).fetchone()
            if existing is not None and not replace:
                if self._row_to_record(existing) == record:
                    return
                raise PlacementError("PLACEMENT_ALREADY_EXISTS")
            if existing is None:
                con.execute(
                    """INSERT INTO placements VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.identity.algorithm,
                        record.identity.digest,
                        record.placement_id,
                        record.provider_id,
                        record.object_key,
                        record.size_bytes,
                        record.region,
                        record.tier,
                        record.priority,
                        1 if record.enabled else 0,
                    ),
                )
            else:
                con.execute(
                    """UPDATE placements
                       SET provider_id=?, object_key=?, size_bytes=?, region=?, tier=?, priority=?, enabled=?
                       WHERE algorithm=? AND digest=? AND placement_id=?""",
                    (
                        record.provider_id,
                        record.object_key,
                        record.size_bytes,
                        record.region,
                        record.tier,
                        record.priority,
                        1 if record.enabled else 0,
                        record.identity.algorithm,
                        record.identity.digest,
                        record.placement_id,
                    ),
                )

    def remove(self, identity: ExactContentIdentity, placement_id: str) -> bool:
        if not isinstance(identity, ExactContentIdentity):
            raise TypeError("identity must be ExactContentIdentity")
        placement_id = _identity_text(placement_id, "PLACEMENT_ID_INVALID")
        with self._connect() as con:
            cursor = con.execute(
                "DELETE FROM placements WHERE algorithm=? AND digest=? AND placement_id=?",
                (identity.algorithm, identity.digest, placement_id),
            )
            return cursor.rowcount > 0

    def records(self, identity: ExactContentIdentity) -> tuple[PlacementRecord, ...]:
        if not isinstance(identity, ExactContentIdentity):
            raise TypeError("identity must be ExactContentIdentity")
        with self._connect() as con:
            rows = con.execute(
                """SELECT * FROM placements
                   WHERE algorithm=? AND digest=?
                   ORDER BY priority, placement_id""",
                (identity.algorithm, identity.digest),
            ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def replace_all(self, records: Iterable[PlacementRecord]) -> None:
        records = tuple(records)
        seen: set[tuple[str, str, str]] = set()
        for record in records:
            if not isinstance(record, PlacementRecord):
                raise TypeError("records must contain PlacementRecord")
            key = (record.identity.algorithm, record.identity.digest, record.placement_id)
            if key in seen:
                raise PlacementError("PLACEMENT_DUPLICATE_RECORD")
            seen.add(key)
        with self._connect() as con:
            con.execute("DELETE FROM placements")
            con.executemany(
                "INSERT INTO placements VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        record.identity.algorithm,
                        record.identity.digest,
                        record.placement_id,
                        record.provider_id,
                        record.object_key,
                        record.size_bytes,
                        record.region,
                        record.tier,
                        record.priority,
                        1 if record.enabled else 0,
                    )
                    for record in records
                ],
            )


class PhysicalPlacementResolver:
    def __init__(self, catalog: PlacementCatalog):
        if not isinstance(catalog, PlacementCatalog):
            raise TypeError("catalog must be PlacementCatalog")
        self.catalog = catalog

    def resolve(
        self,
        identity: ExactContentIdentity,
        policy: PlacementPolicy | None = None,
    ) -> tuple[PlacementRecord, ...]:
        if policy is None:
            policy = PlacementPolicy()
        if not isinstance(policy, PlacementPolicy):
            raise TypeError("policy must be PlacementPolicy")

        candidates = []
        for record in self.catalog.records(identity):
            if not record.enabled:
                continue
            if policy.allowed_provider_ids and record.provider_id not in policy.allowed_provider_ids:
                continue
            if policy.allowed_tiers and record.tier not in policy.allowed_tiers:
                continue
            if policy.max_bytes is not None and record.size_bytes > policy.max_bytes:
                continue
            region_rank = 0 if policy.preferred_region is not None and record.region == policy.preferred_region else 1
            candidates.append((region_rank, record.priority, record.placement_id, record))
        candidates.sort(key=lambda item: item[:3])
        return tuple(item[3] for item in candidates)

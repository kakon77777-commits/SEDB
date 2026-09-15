from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .placement import ExactContentIdentity, PlacementError

RANGE_COMMITMENT_SCHEMA = "isql-range-commitment/v0.1"
RANGE_PROOF_SIDECAR_SCHEMA = "isql-range-proof-sidecar/v0.1"
MAX_CHUNK_SIZE = 16 * 1024 * 1024
_LEAF_DOMAIN = b"ISQL-RANGE-LEAF-v1\x00"
_PAD_DOMAIN = b"ISQL-RANGE-PAD-v1\x00"
_NODE_DOMAIN = b"ISQL-RANGE-NODE-v1\x00"


class RangeProofError(PlacementError):
    pass


def _hex64(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise RangeProofError(code)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise RangeProofError(code) from exc
    if len(raw) != 32:
        raise RangeProofError(code)
    return value


def _u64(value: int) -> bytes:
    if type(value) is not int or value < 0 or value >= 1 << 64:
        raise RangeProofError("RANGE_INTEGER_OUT_OF_DOMAIN")
    return value.to_bytes(8, "big")


def _leaf_hash(index: int, content: bytes) -> bytes:
    return hashlib.sha256(_LEAF_DOMAIN + _u64(index) + _u64(len(content)) + content).digest()


def _pad_hash(index: int) -> bytes:
    return hashlib.sha256(_PAD_DOMAIN + _u64(index)).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise RangeProofError("RANGE_NODE_HASH_INVALID")
    return hashlib.sha256(_NODE_DOMAIN + left + right).digest()


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RangeProofError("RANGE_COMMITMENT_NOT_CANONICAL_JSON") from exc


@dataclass(frozen=True, slots=True)
class RangeCommitment:
    source_identity: ExactContentIdentity
    size_bytes: int
    chunk_size: int
    chunk_count: int
    tree_depth: int
    chunk_root_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, ExactContentIdentity):
            raise RangeProofError("RANGE_SOURCE_IDENTITY_REQUIRED")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise RangeProofError("RANGE_SIZE_INVALID")
        if type(self.chunk_size) is not int or not (1 <= self.chunk_size <= MAX_CHUNK_SIZE):
            raise RangeProofError("RANGE_CHUNK_SIZE_INVALID")
        expected_count = max(1, (self.size_bytes + self.chunk_size - 1) // self.chunk_size)
        if self.chunk_count != expected_count:
            raise RangeProofError("RANGE_CHUNK_COUNT_INVALID")
        expected_depth = (self.chunk_count - 1).bit_length()
        if self.tree_depth != expected_depth:
            raise RangeProofError("RANGE_TREE_DEPTH_INVALID")
        object.__setattr__(self, "chunk_root_sha256", _hex64(self.chunk_root_sha256, "RANGE_ROOT_INVALID"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RANGE_COMMITMENT_SCHEMA,
            "source_identity": {
                "algorithm": self.source_identity.algorithm,
                "digest": self.source_identity.digest,
            },
            "size_bytes": self.size_bytes,
            "chunk_size": self.chunk_size,
            "chunk_count": self.chunk_count,
            "tree_depth": self.tree_depth,
            "chunk_root_sha256": self.chunk_root_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def expected_chunk_length(self, index: int) -> int:
        if type(index) is not int or not (0 <= index < self.chunk_count):
            raise RangeProofError("RANGE_CHUNK_INDEX_INVALID")
        if self.size_bytes == 0:
            return 0
        if index < self.chunk_count - 1:
            return self.chunk_size
        return self.size_bytes - self.chunk_size * (self.chunk_count - 1)


@dataclass(frozen=True, slots=True)
class ChunkProof:
    chunk_index: int
    chunk_length: int
    sibling_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.chunk_index) is not int or self.chunk_index < 0:
            raise RangeProofError("RANGE_CHUNK_INDEX_INVALID")
        if type(self.chunk_length) is not int or self.chunk_length < 0:
            raise RangeProofError("RANGE_CHUNK_LENGTH_INVALID")
        object.__setattr__(
            self,
            "sibling_sha256s",
            tuple(_hex64(value, "RANGE_SIBLING_HASH_INVALID") for value in self.sibling_sha256s),
        )


def verify_chunk_proof(commitment: RangeCommitment, content: bytes, proof: ChunkProof) -> bool:
    if not isinstance(commitment, RangeCommitment) or not isinstance(proof, ChunkProof):
        return False
    try:
        if proof.chunk_index >= commitment.chunk_count:
            return False
        if proof.chunk_length != commitment.expected_chunk_length(proof.chunk_index):
            return False
        if len(content) != proof.chunk_length or len(proof.sibling_sha256s) != commitment.tree_depth:
            return False
        current = _leaf_hash(proof.chunk_index, content)
        node_index = proof.chunk_index
        for sibling_hex in proof.sibling_sha256s:
            sibling = bytes.fromhex(sibling_hex)
            current = _node_hash(current, sibling) if node_index % 2 == 0 else _node_hash(sibling, current)
            node_index //= 2
        return current.hex() == commitment.chunk_root_sha256
    except (RangeProofError, ValueError):
        return False


def _commitment_from_dict(value: dict[str, object]) -> RangeCommitment:
    if value.get("schema") != RANGE_COMMITMENT_SCHEMA:
        raise RangeProofError("RANGE_COMMITMENT_SCHEMA_INVALID")
    source = value.get("source_identity")
    if not isinstance(source, dict):
        raise RangeProofError("RANGE_SOURCE_IDENTITY_INVALID")
    return RangeCommitment(
        source_identity=ExactContentIdentity(str(source.get("algorithm")), str(source.get("digest"))),
        size_bytes=int(value["size_bytes"]),
        chunk_size=int(value["chunk_size"]),
        chunk_count=int(value["chunk_count"]),
        tree_depth=int(value["tree_depth"]),
        chunk_root_sha256=str(value["chunk_root_sha256"]),
    )


def build_range_proof_sidecar(
    source_path: str | Path,
    sidecar_path: str | Path,
    identity: ExactContentIdentity,
    *,
    chunk_size: int = 1024 * 1024,
    overwrite: bool = False,
) -> RangeCommitment:
    source = Path(source_path).resolve(strict=True)
    sidecar = Path(sidecar_path)
    if not source.is_file():
        raise RangeProofError("RANGE_SOURCE_NOT_REGULAR")
    if source == sidecar.resolve(strict=False):
        raise RangeProofError("RANGE_SIDECAR_SOURCE_COLLISION")
    if sidecar.exists() and not overwrite:
        raise RangeProofError("RANGE_SIDECAR_EXISTS")
    if type(chunk_size) is not int or not (1 <= chunk_size <= MAX_CHUNK_SIZE):
        raise RangeProofError("RANGE_CHUNK_SIZE_INVALID")

    chunks: list[tuple[int, bytes, bytes]] = []
    full_hasher = hashlib.sha256()
    size = 0
    with source.open("rb") as stream:
        index = 0
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            full_hasher.update(block)
            size += len(block)
            chunks.append((index, block, _leaf_hash(index, block)))
            index += 1
    if not chunks:
        chunks.append((0, b"", _leaf_hash(0, b"")))
    if full_hasher.hexdigest() != identity.digest:
        raise RangeProofError("RANGE_SOURCE_DIGEST_MISMATCH")

    chunk_count = len(chunks)
    depth = (chunk_count - 1).bit_length()
    leaf_capacity = 1 << depth
    levels: list[list[bytes]] = []
    leaves = [item[2] for item in chunks]
    leaves.extend(_pad_hash(index) for index in range(chunk_count, leaf_capacity))
    levels.append(leaves)
    while len(levels[-1]) > 1:
        previous = levels[-1]
        levels.append([_node_hash(previous[i], previous[i + 1]) for i in range(0, len(previous), 2)])
    root = levels[-1][0]
    commitment = RangeCommitment(identity, size, chunk_size, chunk_count, depth, root.hex())

    sidecar.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar.with_name(f".{sidecar.name}.{uuid4().hex}.tmp")
    try:
        with sqlite3.connect(tmp) as con:
            con.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE chunks (chunk_index INTEGER PRIMARY KEY, chunk_length INTEGER NOT NULL, leaf_hash BLOB NOT NULL);
                CREATE TABLE nodes (level INTEGER NOT NULL, node_index INTEGER NOT NULL, node_hash BLOB NOT NULL, PRIMARY KEY(level,node_index));
                CREATE TRIGGER metadata_no_update BEFORE UPDATE ON metadata BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                CREATE TRIGGER metadata_no_delete BEFORE DELETE ON metadata BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                CREATE TRIGGER chunks_no_update BEFORE UPDATE ON chunks BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                CREATE TRIGGER chunks_no_delete BEFORE DELETE ON chunks BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                CREATE TRIGGER nodes_no_update BEFORE UPDATE ON nodes BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                CREATE TRIGGER nodes_no_delete BEFORE DELETE ON nodes BEGIN SELECT RAISE(ABORT, 'RANGE_SIDECAR_IMMUTABLE'); END;
                """
            )
            con.execute("INSERT INTO metadata VALUES (?,?)", ("schema", RANGE_PROOF_SIDECAR_SCHEMA.encode()))
            con.execute("INSERT INTO metadata VALUES (?,?)", ("commitment_json", commitment.canonical_bytes()))
            con.execute("INSERT INTO metadata VALUES (?,?)", ("commitment_sha256", commitment.commitment_sha256.encode()))
            con.executemany("INSERT INTO chunks VALUES (?,?,?)", [(i, len(block), leaf) for i, block, leaf in chunks])
            con.executemany(
                "INSERT INTO nodes VALUES (?,?,?)",
                [(level, idx, node_hash) for level, nodes in enumerate(levels) for idx, node_hash in enumerate(nodes)],
            )
        if sidecar.exists() and not overwrite:
            raise RangeProofError("RANGE_SIDECAR_EXISTS")
        os.replace(tmp, sidecar)
    finally:
        if tmp.exists():
            tmp.unlink()
    return commitment


class RangeProofIndex:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise RangeProofError("RANGE_SIDECAR_UNAVAILABLE")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
        return con

    def commitment(self) -> RangeCommitment:
        with self._connect() as con:
            rows = dict((str(row[0]), bytes(row[1])) for row in con.execute("SELECT key,value FROM metadata"))
        if rows.get("schema") != RANGE_PROOF_SIDECAR_SCHEMA.encode():
            raise RangeProofError("RANGE_SIDECAR_SCHEMA_INVALID")
        try:
            value = json.loads(rows["commitment_json"].decode("utf-8"))
        except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise RangeProofError("RANGE_SIDECAR_COMMITMENT_INVALID") from exc
        commitment = _commitment_from_dict(value)
        if rows.get("commitment_sha256") != commitment.commitment_sha256.encode():
            raise RangeProofError("RANGE_SIDECAR_COMMITMENT_HASH_MISMATCH")
        return commitment

    def proof(self, chunk_index: int) -> ChunkProof:
        commitment = self.commitment()
        expected_length = commitment.expected_chunk_length(chunk_index)
        with self._connect() as con:
            row = con.execute("SELECT chunk_length,leaf_hash FROM chunks WHERE chunk_index=?", (chunk_index,)).fetchone()
            if row is None or int(row[0]) != expected_length:
                raise RangeProofError("RANGE_SIDECAR_CHUNK_MISSING")
            node_index = chunk_index
            siblings: list[str] = []
            for level in range(commitment.tree_depth):
                sibling_index = node_index ^ 1
                sibling_row = con.execute("SELECT node_hash FROM nodes WHERE level=? AND node_index=?", (level, sibling_index)).fetchone()
                if sibling_row is None or len(bytes(sibling_row[0])) != 32:
                    raise RangeProofError("RANGE_SIDECAR_NODE_MISSING")
                siblings.append(bytes(sibling_row[0]).hex())
                node_index //= 2
        return ChunkProof(chunk_index, expected_length, tuple(siblings))

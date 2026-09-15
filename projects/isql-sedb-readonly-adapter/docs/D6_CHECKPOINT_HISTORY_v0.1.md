# D6 Checkpoint History and Head Anchoring — Internal Experimental Boundary

**Status:** Internal / Experimental  
**Scope:** append-only temporal anchoring for D5 proof-sidecar checkpoints.

## Goal

D5 produces a cryptographically checkable checkpoint:

$$
C_K=(H(C_F),R_E,N_E).
$$

But a valid checkpoint alone does not answer:

- When was this checkpoint accepted into a state stream?
- Which checkpoint preceded it?
- Is it the current head of that stream?
- Which authority context claims the append?

D6 adds an append-only checkpoint history ledger:

$$
\boxed{
C_{K,0}\rightarrow C_{K,1}\rightarrow\cdots\rightarrow C_{K,n}
}
$$

with a hash-chained record for every append.

## Record model

Each record contains:

```text
stream_id
sequence
parent_record_sha256
checkpoint
checkpoint_sha256
observed_at
authority_ref
note
```

and:

$$
H(R_i)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(R_i)).
$$

For a non-genesis record:

$$
R_i.parent=H(R_{i-1}).
$$

The checkpoint object itself is embedded in the record and its canonical hash must equal `checkpoint_sha256`.

## Expected-head append

Appending uses a compare-and-swap-like precondition:

$$
\boxed{
H_{expected}=H_{current}
}
$$

under one SQLite `BEGIN IMMEDIATE` transaction.

A stale or missing expected head fails with `CheckpointHistoryConflict` rather than silently branching or overwriting.

Genesis requires:

```text
expected_head_sha256 = None
```

and sequence `0`.

## Streams

`stream_id` is an exact identity string, not semantically normalized text. Different streams evolve independently and may represent later branch/domain concepts without forcing one universe-wide head.

D6 v0.1 keeps each individual stream linear. Explicit fork/merge semantics belong to a later DSR/history layer.

## Head verification

A D5 proof envelope can now be checked at three distinct levels:

1. **Proof validity** — field/cell/entity sparse-Merkle proofs are internally valid.
2. **History validity** — the ledger record chain is contiguous and hash-linked.
3. **Head validity** — the envelope checkpoint hash equals the latest checkpoint hash in the selected stream.

Thus:

$$
\boxed{
\text{ValidProof}
\neq
\text{AnchoredCheckpoint}
\neq
\text{CurrentHead}
}
$$

`verify_sidecar_envelope_at_head()` reports these dimensions separately.

## Authority boundary

`authority_ref` is an exact declared identity label carried by the record. It is **not** a cryptographic signature.

D6 therefore establishes:

```text
this ledger says authority_ref appended this checkpoint
```

not:

```text
a cryptographic signature proves the named authority performed the append
```

A later signature / RAL / organizational authority layer may bind record hashes to cryptographic credentials.

## Append-only enforcement

The ledger uses SQLite triggers to reject row updates and deletes through the normal database interface. Record hashes and parent hashes detect modified/reordered interior history.

However, an attacker with arbitrary file-level control can remove triggers or truncate a valid tail. A self-contained local hash chain cannot prove that no later valid tail once existed.

Therefore:

$$
\boxed{
\text{Hash Chain Integrity}
\neq
\text{External Non-Truncation Guarantee}
}
$$

External anchoring of a known head record hash is required to detect tail rollback across trust boundaries.

## Time semantics

`observed_at` is caller-supplied, timezone-aware, and canonicalized to UTC RFC3339 with microseconds.

It records the asserted observation/append time. D6 does not claim trusted time synchronization or secure timestamping.

## Separation from SEDB current

The history ledger is an external integration artifact. It does not alter SEDB `current/` v0.4B and does not become a SEDB canonical mutation log merely because it references SEDB-derived checkpoints.

## Next step

After D6, the most useful next step is **cryptographic checkpoint attestation / RAL binding** or DSR branch-history integration, so a head record hash can be bound to an authenticated authority and, eventually, branch/fork/merge semantics.

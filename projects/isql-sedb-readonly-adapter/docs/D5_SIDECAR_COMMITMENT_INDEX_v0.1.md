# D5 Sidecar Commitment Index — Internal Experimental Boundary

**Status:** Internal / Experimental  
**Scope:** persistent proof-index checkpoint for D4 sparse-Merkle commitments without modifying SEDB `current/`.

## Goal

D4 proved that a partial projection can be verified from commitments and sparse-Merkle paths, but the D4 proof issuer still reconstructs those commitments from a complete current SEDB read.

D5 separates **checkpoint construction** from **partial proof issuance**:

$$
\boxed{
\text{SEDB checkpoint}
\rightarrow
\text{Proof Sidecar}
\rightarrow
\text{targeted leaf/path reads}
\rightarrow
\text{proof envelope}
}
$$

The sidecar is an independent SQLite artifact. It does not alter SEDB's validated v0.4B schema or mutation paths.

## Checkpoint structure

D5 persists:

- the D4 `FieldRegistryCommitment`;
- canonical field leaf payloads;
- non-default field sparse-tree nodes;
- every D4 `EntityStateCommitment` and entity metadata;
- canonical sparse cell leaf payloads;
- per-entity non-default cell sparse-tree nodes;
- a global sparse tree mapping `entity_id -> entity_commitment_sha256`.

The top-level checkpoint is:

$$
C_K=(H(C_F),R_E,N_E)
$$

where:

- $H(C_F)$ is the field-registry commitment hash;
- $R_E$ is the global entity-commitment sparse-tree root;
- $N_E$ is the checkpoint entity count.

Thus an entity proof chain becomes:

$$
\boxed{
C_K
\rightarrow
C_E
\rightarrow
\text{field/cell proof}
}
$$

A future history, signature, consensus, or RAL layer can anchor one checkpoint hash rather than independently anchoring every entity.

## Consistent source checkpoint

The sidecar builder opens one read-only SEDB connection and starts one explicit read transaction before reading the field registry and entity states. SQLite snapshot semantics then provide one consistent source checkpoint for the build.

D5 does not claim that a sidecar automatically tracks later SEDB writes. A later source state requires a later checkpoint.

## Targeted proof issuance

After the sidecar exists, proof issuance no longer consults source SEDB.

For each requested projection it reads only:

- the checkpoint and two commitment records;
- the selected entity commitment/metadata;
- one field leaf and one 256-sibling path per projected field;
- for `present` / `blank`, one cell leaf and one cell path;
- for `absent` / `unknown`, one missing-cell lookup and one empty-leaf path;
- for `unloaded`, **no cell leaf lookup and no cell path**.

The v0.1 implementation uses point queries for each sibling node. This is deliberately simple and auditable; batched retrieval and compressed default siblings are later optimizations.

## Read statistics

Every issued envelope reports:

```text
field_leaf_reads
cell_leaf_reads
node_hash_lookups
commitment_reads
```

These are logical sidecar lookups, not physical disk-page counters. They make the prototype's asymptotic boundary observable without overstating storage-engine I/O.

## Historical checkpoint semantics

A proof sidecar is immutable-by-convention after construction. If source SEDB later changes, the old sidecar still proves the old checkpoint.

A new D3 projection carrying a new D1 exact SHA must not be accepted by the old sidecar. Building a new sidecar produces a new checkpoint hash.

Therefore:

$$
\boxed{
\text{Current Source State}
\neq
\text{Historical Sidecar Checkpoint}
}
$$

## Authority boundary

The sidecar checkpoint is a commitment artifact, not an authority statement by itself.

Verification proves consistency with the supplied checkpoint. It does not prove that the checkpoint is the globally authoritative current head until another layer anchors that checkpoint hash.

## Non-goals

D5 does not:

- modify SEDB `current/`;
- add write authority;
- automatically update sidecars after source mutation;
- sign checkpoints;
- establish consensus/current-head authority;
- compress 256-sibling sparse proofs;
- claim SQLite point-query counts equal physical storage I/O.

## Next step

After D5, the highest-value architectural step is **checkpoint anchoring / append-only state-head history**. Compression and batching are useful optimizations, but authority and temporal identity must be established before treating sidecar checkpoints as distributed world-state heads.

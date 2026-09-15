# D4 Proof-Carrying Partial Read — Internal Experimental Boundary

**Status:** Internal / Experimental  
**Scope:** read-only commitment and proof layer over the D1/D2/D3 ISQL–SEDB integration project.

## Goal

D3 established:

$$
P_{D_Q}(X)\neq X
$$

and made `present / blank / unknown / absent / unloaded` explicit. D4 adds a commitment layer so selected field claims can be checked against compact roots without requiring the verifier to fetch the complete D1 entity snapshot.

The target is:

$$
\boxed{
C_E + C_F + \pi_{D_Q} + P_{D_Q}(X)
\rightarrow
\operatorname{VerifyPartial}
}
$$

where:

- $C_E$ is an entity-state commitment;
- $C_F$ is a field-registry commitment;
- $\pi_{D_Q}$ is membership/non-membership evidence for selected fields;
- $P_{D_Q}(X)$ is the D3 partial projection.

## Two-root design

D4 deliberately does **not** place the global field-registry root inside the entity-state identity.

```text
EntityStateCommitment
  = entity metadata hash + sparse cell root

FieldRegistryCommitment
  = field-definition root
```

This prevents an unrelated global field addition from changing every entity commitment.

## Sparse Merkle design

D4 uses a fixed-depth 256-bit sparse Merkle tree rather than an ordered-neighbor Merkle list.

Each stable `field_id` maps to a tree path:

$$
K_f=\operatorname{SHA256}(0x02\parallel\operatorname{UTF8}(field\_id)).
$$

The path bits of $K_f$ select left/right branches from leaf depth 256 to the root.

Domain-separated hashes:

```text
present leaf = SHA-256(0x00 || "present" || key_digest || canonical-json(payload))
empty leaf   = SHA-256(0x00 || "empty")
internal     = SHA-256(0x01 || left || right)
```

Default empty-subtree hashes are precomputed recursively from the empty leaf.

A proof carries exactly 256 sibling hashes. The verifier derives branch direction from the field-id key digest; it does not trust a direction bit supplied by the proof.

### Why sparse Merkle instead of ordered-neighbor non-membership

An ordinary sorted Merkle list can represent a deterministic tree, but a local non-membership proof based on predecessor/successor adjacency still relies on the global assumption that the committed tree was actually constructed in canonical sorted order.

A sparse Merkle tree avoids that global ordering assumption for absence: the target `field_id` has one fixed cryptographic path. A non-membership proof starts from the canonical empty leaf at that exact path and folds the sibling hashes to the committed root.

This gives native membership and non-membership under the same root.

The v0.1 prototype uses full 256-sibling proofs for clarity. Future versions may compress runs of default empty siblings without changing root semantics.

## Cell claims

### present / blank

Require:

1. field-definition membership under $C_F$;
2. cell membership under $C_E$;
3. proof payload equality with the D3 projected value/provenance.

### absent

Require:

1. field-definition membership under $C_F$;
2. sparse-Merkle empty-leaf proof for that `field_id` under $C_E$.

### unknown

`unknown` is an external epistemic annotation, not a stored SEDB cell state. D4 therefore requires the same empty-leaf proof as `absent`, plus the explicit `unknown_reason` already required by D3.

### unloaded

`unloaded` deliberately makes no cell-existence claim. D4 proves the field definition but must not attach either a cell membership or a cell non-membership proof.

Therefore:

$$
\boxed{
\text{unloaded}\neq\text{absent}\neq\text{unknown}\neq\text{blank}
}
$$

## Key-digest collisions

The proof issuer rejects two distinct field IDs that map to the same 256-bit sparse-tree key digest. This is a defensive protocol condition; security otherwise relies on SHA-256 collision resistance.

## Legacy D1 SHA bridge

D1 currently identifies the complete adapter snapshot by:

$$
H_{D1}(X)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(X)).
$$

A Merkle proof cannot, in general, prove equality to that pre-existing flat hash without the full JSON preimage (or a stronger proof system). D4 therefore does **not** pretend otherwise.

During commitment issuance the builder performs a full D1 read, derives the sparse-Merkle commitments from that same state, and records `legacy_snapshot_sha256` as a bridge reference. Later partial verification proves consistency with the D4 commitments, not self-authenticating equivalence to the legacy flat hash.

The architectural progression is therefore:

```text
D1 flat exact snapshot SHA
    -> D4 issued commitment object
    -> future state-head/history anchoring of commitment SHA
```

Until a D4 commitment SHA is anchored by an authority/history layer, verification establishes consistency **with the supplied commitment**, not global authority over that commitment.

## Issuance vs verification cost

Prototype issuance is correctness-first and may read the complete current entity state plus field registry.

Verification is DB-independent and consumes only:

- the commitments;
- entity metadata;
- selected field definitions;
- selected cell payloads or empty-leaf proofs;
- sparse Merkle sibling paths.

Thus D4 proves the cryptographic/data-structural boundary for future partial storage/network reads without claiming the current SQLite proof issuer is already I/O optimal.

## Non-goals

D4 does not:

- modify SEDB `current/` v0.4B;
- replace D1 exact snapshot identity;
- define public SEDB canonical state;
- add write authority;
- add signatures, consensus, or RAL attestation;
- prove historical/current-head authority;
- claim a D3 projection is a complete entity state;
- claim the uncompressed 256-sibling proof format is bandwidth-optimal.

## Next step

After D4, the next storage-level experiment can persist commitment heads and sparse-tree node/proof indexes at mutation/checkpoint time so readers retrieve only selected field/cell leaves and required sibling nodes instead of asking a proof issuer to reconstruct them from a complete SQLite view on demand.

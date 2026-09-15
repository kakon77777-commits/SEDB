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
  = entity metadata hash + sparse cell Merkle root

FieldRegistryCommitment
  = field-definition Merkle root
```

This prevents an unrelated global field addition from changing every entity commitment.

## Merkle domain separation

```text
leaf     = SHA-256(0x00 || canonical-json(leaf))
internal = SHA-256(0x01 || left || right)
empty    = SHA-256(0x02 || "empty")
```

Leaves are sorted by stable key (`field_id`) and must be unique. Odd nodes duplicate the final hash at that level. Membership proofs carry leaf index, total leaf count, and sibling hashes; proof direction is derived from `(index,count)` rather than trusted from the proof payload.

## Cell claims

### present / blank

Require:

1. field-definition membership under $C_F$;
2. cell membership under $C_E$;
3. proof payload equality with the D3 projected value/provenance.

### absent

Require:

1. field-definition membership under $C_F$;
2. cell **non-membership** under $C_E$.

Non-membership is proven over the canonical sorted sparse-cell sequence using adjacent predecessor/successor membership proofs (or an empty tree proof). Adjacency and boundary indices are checked.

### unknown

`unknown` is an external epistemic annotation, not a stored SEDB cell state. D4 therefore requires cell non-membership and preserves the explicit `unknown_reason` from D3.

### unloaded

`unloaded` deliberately makes no cell-existence claim. D4 may prove the field definition, but must not attach a cell membership or non-membership proof.

Therefore:

$$
\boxed{
\text{unloaded}\neq\text{absent}
}
$$

## Legacy D1 SHA bridge

D1 currently identifies the complete adapter snapshot by:

$$
H_{D1}(X)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(X)).
$$

A Merkle proof cannot, in general, prove equality to that pre-existing flat hash without the full JSON preimage (or a stronger proof system). D4 therefore does **not** pretend otherwise.

During commitment issuance the builder performs a full D1 read, derives the Merkle commitments from that same state, and records `legacy_snapshot_sha256` as a bridge reference. Later partial verification proves consistency with the D4 commitments, not self-authenticating equivalence to the legacy flat hash.

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
- selected cell payloads or sparse non-membership neighbors;
- Merkle paths.

Thus D4 proves the cryptographic/data-structural boundary for future partial storage/network reads without claiming the current SQLite proof issuer is already I/O optimal.

## Non-goals

D4 does not:

- modify SEDB `current/` v0.4B;
- replace D1 exact snapshot identity;
- define public SEDB canonical state;
- add write authority;
- add signatures, consensus, or RAL attestation;
- prove historical/current-head authority;
- claim a D3 projection is a complete entity state.

## Next step

After D4, the next storage-level experiment can persist commitment heads/proof indexes at mutation/checkpoint time so readers retrieve only selected cell/field leaves and Merkle paths instead of asking a proof issuer to reconstruct them from a complete SQLite view on demand.

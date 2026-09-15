# D13 World Materialization Manifest v0.1

**Status:** Experimental cross-layer materialization contract

## Purpose

D9 defines exact world-state synchronization identity.

D12 defines exact range-proof commitments for physical partial reads.

Those identities must remain separate.

D13 introduces:

$$
\boxed{
M_W=
\left(
H(W_H),
\{H(X_i),H(C_{R,i})\}
\right)
}
$$

where:

- $H(W_H)$ is the D9 world-head manifest SHA-256;
- $H(X_i)$ is one exact source-content identity;
- $H(C_{R,i})$ is the exact D12 range-commitment identity chosen for that source.

The D13 manifest has its own SHA-256 identity.

## Why D13 is not D9 v0.2

A world does not become a different world merely because a client changes:

- chunk size;
- proof-tree layout;
- local cache strategy;
- physical replica.

Therefore:

$$
\boxed{
\text{World State Identity}
\neq
\text{Materialization Proof Layout}
\neq
\text{Physical Placement}
}
$$

D13 remains a separate materialization manifest rather than modifying D9 world identity.

## Artifact binding

Each artifact binding contains:

```text
artifact_ref
source exact identity
range-commitment SHA-256
source size
chunk size/count
chunk Merkle root
```

The range fields must match the actual D12 `RangeProofIndex` commitment before the manifest is considered usable.

Artifact refs are exact, case-sensitive application references. D13 does not apply semantic normalization to them.

## Deterministic identity

Artifact bindings are canonicalized by exact `artifact_ref` order.

Thus input mapping order does not change:

$$
H(M_W)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(M_W))
$$

## Verification

D13 verification separately checks:

- expected D13 manifest SHA;
- expected D9 world-head SHA;
- every required artifact's D12 commitment sidecar.

Extra locally cached proof indexes do not invalidate a manifest.

This preserves:

$$
\boxed{
\text{Required Active Set}
\subseteq
\text{Local Cache}
}
$$

rather than requiring them to be identical.

## Reader path

After D13 verification:

```text
artifact_ref
-> exact source identity + exact range commitment
-> D12 VerifiedRangeFetcher
-> D11 physical placement resolution
-> bounded range read
-> Merkle verification
```

So the caller no longer supplies an arbitrary range commitment at read time; it receives the commitment selected by the trusted materialization manifest.

## Historical boundary

D13 is bound to one exact D9 world-head hash.

If the world advances, an old D13 manifest remains an exact materialization description for its historical world head, but it is not automatically a materialization plan for a newer D9 head.

D13 itself does not query D9 currentness. The caller must first establish which D9 head it trusts.

## Trust boundary

D13 v0.1 still requires a trusted expected `H(M_W)`.

D13 does not yet anchor its own manifest hash into RAL/CTCL.

A later anchor profile can externally retain `H(M_W)` while keeping D9 identity unchanged.

## Non-claims

D13 does not:

- mutate D9 world identity;
- mutate D12 range commitments;
- choose physical replicas;
- grant authorization;
- prove D9 currentness;
- add network providers;
- modify Public ISQL formats.

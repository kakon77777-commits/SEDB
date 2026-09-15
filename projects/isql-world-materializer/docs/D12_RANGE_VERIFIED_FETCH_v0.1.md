# D12 Range Commitment + Proof-Verified Partial Fetch v0.1

**Status:** Experimental world-materialization infrastructure  
**Build model:** full-read commitment issuance, partial-read verification afterward

## Problem

D11 verifies a fetched replica by hashing the complete object.

That is correct, but it means each fetch cost still scales with the full object size.

A normal SHA-256 content identity does not support proving an arbitrary byte range from the range alone:

$$
\boxed{
H(X)
+X[i:j]
\not\Rightarrow
\operatorname{Verify}(X[i:j]\subset X)
}
$$

D12 therefore does **not** pretend that a partial hash is the full-object hash.

Instead it introduces a separately identified chunk-Merkle commitment that is created only after the complete source object has first been verified against its exact SHA-256 identity.

## Commitment issuance

At sidecar-build time:

1. read the complete source object;
2. recompute and require its D11 `ExactContentIdentity`;
3. split it into fixed-size chunks;
4. hash each chunk with its exact index and length;
5. build a deterministic binary Merkle tree;
6. persist the commitment and proof nodes in an immutable sidecar.

The commitment contains:

```text
source exact identity
source size
chunk size
chunk count
tree depth
chunk Merkle root
```

and receives its own identity:

$$
H(C_R)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(C_R))
$$

Therefore:

$$
\boxed{
H(C_R)\neq H(X)
}
$$

The commitment is a proof structure **about** the exact source object; it is not a replacement content identity.

## Trust boundary

A range verifier must be given an **expected range-commitment SHA-256** from a trusted or externally anchored control plane.

Without such an expected commitment identity, an untrusted party could fabricate a different Merkle tree and merely write the desired source SHA into its metadata.

So D12 requires:

$$
\boxed{
H(X)
+
H(C_R)_{trusted}
+
\pi_i
+
X_i
\rightarrow
\operatorname{VerifyPartial}
}
$$

D12 v0.1 does not yet anchor `H(C_R)` into D9/D10. That is a later integration step.

## Chunk hashing

Each actual chunk leaf binds:

```text
chunk index
chunk byte length
chunk bytes
```

Padding leaves use a separate hash domain and their exact padded index.

Internal nodes also use a separate domain.

This prevents leaf/internal/padding reinterpretation.

The tree is padded to the next power-of-two leaf capacity. A one-chunk object has depth zero.

## Range proof sidecar

The SQLite sidecar stores:

- commitment JSON and commitment SHA;
- actual chunk leaf metadata;
- Merkle nodes for proof paths.

Normal `UPDATE` / `DELETE` operations are rejected by triggers.

After construction, `RangeProofIndex` opens the sidecar read-only and can issue one targeted proof without reading the original source object.

The original source may be removed after sidecar construction and proof issuance still works.

## Partial physical fetch

`LocalDirectoryProvider.read_range()` reads only the requested physical interval.

`VerifiedRangeFetcher.fetch_range()`:

1. requires exact source identity $H(X)$;
2. requires trusted expected commitment identity $H(C_R)$;
3. verifies sidecar commitment identity and source binding;
4. resolves D11 physical placements for $H(X)$;
5. determines only chunks covering the requested byte range;
6. reads those chunks with bounded `read_range()` calls;
7. verifies every chunk against its Merkle proof;
8. slices the verified chunks to the exact requested range.

For a request spanning chunks $i..j$:

$$
\operatorname{ReadCost}
\approx
\sum_{k=i}^{j}|X_k|
+
O((j-i+1)\log N)
$$

rather than $|X|$ for every read.

## Replica failover

D12 preserves the D11 rule:

$$
\boxed{
\text{Replica Failover}
\neq
\text{Identity Failover}
}
$$

If a preferred replica returns a corrupt chunk, the Merkle proof fails and the runtime may retry the **same exact source identity and same trusted range commitment** at a later placement.

It never changes $H(X)$ or $H(C_R)$ to make a fetch succeed.

## Historical and rebuild boundary

The range sidecar is a derived proof index.

Rebuilding it from identical source bytes with identical chunk size produces the same logical commitment.

Changing chunk size produces a different range commitment even though the source exact identity remains the same.

Thus:

$$
\boxed{
\text{Proof Layout}
\neq
\text{Source Identity}
}
$$

## Non-claims

D12 v0.1 does not provide:

- proof of the full-file SHA directly from partial bytes without a trusted commitment;
- remote/network range providers;
- range commitment anchoring in D9/D10;
- content encryption;
- authorization;
- hostile concurrent-filesystem race resistance;
- proof compression;
- multi-range batching;
- per-chunk cross-replica mixing;
- Public ISQL wire changes.

## Next integration boundary

The next high-value step is to bind the required range-commitment identities into the world/materialization manifest, so a trusted D9/D10 world head can tell a client both:

```text
which exact source object
which exact range-proof commitment
```

before any physical replica is contacted.

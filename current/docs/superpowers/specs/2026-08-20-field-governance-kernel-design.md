# SEDB v0.2A Field Governance Kernel Design

**Status:** Approved for implementation  
**Date:** 2026-08-20  
**Base:** SEDB local v0.1 (31-test green baseline)  
**Development mode:** local-first; do not push to GitHub during this checkpoint

## Goal

Add a deterministic governance kernel that prevents open-ended field expansion from degrading into duplicate canonical fields, untracked definition drift, or lineage-free merge/split operations.

## Scope

v0.2A adds five capabilities while preserving v0.1 sparse-cell and Task View semantics:

1. proposal accept/reject decisions with reason, evaluator, evidence, and canonical target;
2. deterministic normalized duplicate detection before proposal acceptance or direct field creation;
3. namespace metadata and aliases that resolve to one canonical field identity;
4. immutable field definition versions;
5. explicit merge/split lineage edges.

AI semantic similarity, embeddings, remote model providers, distributed storage, and million-field performance work remain out of scope.

## Compatibility rule

Existing v0.1 databases must open without manual migration. `Database(...)` applies idempotent forward migration that adds governance structures and backfills identity/version metadata without changing existing entity, cell, Task View, or field IDs.

The legacy `fields.key` remains globally unique in v0.2A for migration safety. `namespace` provides governance grouping and alias scope, but v0.2A does not yet permit two canonical fields to share the same raw key in separate namespaces.

## Deterministic normalization

Normalization is deliberately conservative and model-free:

1. Unicode NFKC;
2. trim;
3. lower-case;
4. replace runs of whitespace, hyphen, dot, and slash with `_`;
5. collapse repeated `_`;
6. strip leading/trailing `_`.

For namespace `n`, direct creation or accepted proposals must not silently create a second canonical field when an existing field has the same normalized key.

## Schema additions

Existing tables gain migration-safe columns:

- `fields.namespace TEXT NOT NULL DEFAULT 'global'`
- `fields.normalized_key TEXT`
- `field_proposals.namespace TEXT NOT NULL DEFAULT 'global'`

New tables:

- `field_aliases`
- `field_versions`
- `field_lineage`
- `proposal_decisions`

No destructive table rebuild is allowed in v0.2A.

## Proposal decisions

A proposal begins `pending` and may be decided once.

Acceptance flow:

```text
pending proposal
  -> normalize(namespace, key)
  -> existing canonical normalized match?
       yes -> record alias (when useful) -> accepted -> target existing field
       no  -> create canonical field       -> accepted -> target new field
  -> immutable proposal_decision row
```

Rejection requires a non-empty decision reason and records no canonical field.

Acceptance of a duplicate must never create a second canonical field.

## Aliases

Aliases are scoped by namespace and normalize with the same deterministic function. An alias may resolve to only one canonical field within a namespace. Alias creation must reject collisions that would map the same normalized alias to a different field.

Field resolution order:

1. exact field ID;
2. exact canonical key;
3. normalized canonical key in namespace;
4. normalized alias in namespace.

Entity cell operations and Task View field selection must use governance-aware resolution so aliases behave as references, not copied fields.

## Definition versions

Every field has immutable version `1`. Existing v0.1 fields receive a migration snapshot as version `1`.

Definition updates may change:

- label;
- value type;
- description.

They must not rewrite historical versions and must require a reason. Canonical key and namespace identity changes are deferred beyond v0.2A.

Each successful update appends version `N+1` and updates the current `fields` row.

## Merge lineage

`merge_fields(sources, target)`:

- requires at least one source distinct from target;
- requires a non-empty reason;
- records one `merged_into` edge per source;
- transitions sources to `merged`;
- does not copy or delete sparse cells.

Cell migration policy is explicitly deferred; lineage describes semantic field identity, not automatic data rewriting.

## Split lineage

`split_field(source, children)`:

- requires at least two distinct children;
- requires a non-empty reason;
- records one `split_into` edge per child;
- transitions source to `split`;
- does not auto-copy source cells to children.

## API additions

- `POST /api/proposals/{id}/decision`
- `GET /api/proposals/{id}/decision`
- `POST /api/fields/{id}/aliases`
- `GET /api/fields/{id}/aliases`
- `POST /api/fields/{id}/definition`
- `GET /api/fields/{id}/versions`
- `POST /api/governance/merge`
- `POST /api/governance/split`
- `GET /api/fields/{id}/lineage`

The Browser UI receives a small governance panel for pending proposal accept/reject operations; advanced lineage editing can remain API-first in v0.2A.

## Safety invariants

1. Duplicate normalized proposals cannot create duplicate canonical fields.
2. Alias resolution does not create new field rows.
3. Field version history is append-only.
4. Merge/split cannot occur without explicit lineage.
5. Merge/split does not silently migrate cell values.
6. v0.1 sparse blank-by-absence semantics remain unchanged.
7. Existing v0.1 databases open and retain IDs/data.

## Verification gates

- all existing 31 v0.1 tests remain green;
- new governance tests cover duplicate acceptance, rejection, alias resolution, version immutability, merge/split lineage, API behavior, and v0.1 database migration;
- release ZIP is extracted and re-tested independently;
- UTF-8 source and archive integrity are validated before handoff.

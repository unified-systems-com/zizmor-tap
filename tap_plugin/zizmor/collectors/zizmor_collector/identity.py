"""Deterministic UUIDv5 entity ids for the zizmor collector's own nodes and edges.

Spec: specs/spec-zizmor-v0.md (req-zizmor-collector, req-zizmor-finding, req-zizmor-run).

**The namespace is frozen.** Changing it re-identifies every zizmor node on every grid this
collector has ever touched.

The identity decision that matters here is the FINDING's natural key, and it is deliberately
*not* keyed on the run. A finding keyed on its run would mint a fresh node every six hours for
a defect nobody has touched, and the grid would grow a new copy of the same fact per pass. It is
keyed on the assertion instead — this workflow, this audit, this symbolic route, this persona —
so a re-scan RE-OBSERVES the same node (`observed_at` moves, `known_since` does not) and each
run's `PRODUCED_FINDING` edge records that it saw it. That is what makes "how long has this been
here" answerable, and it is why the model carries both timestamps.

The symbolic route, not the row/column, is the site: a whitespace edit above a finding moves
every concrete coordinate in the file while changing nothing about the finding, and keying on
rows would report the entire file as newly-defective after a reformat.

github_core's endpoint ids are NEVER re-derived here — they are imported from
`tap_plugin.github_core.collectors.github_collector.identity`, which owns that recipe.
"""

from __future__ import annotations

from uuid import NAMESPACE_DNS, UUID, uuid5

ZIZMOR_NAMESPACE: UUID = uuid5(NAMESPACE_DNS, "zizmor.tap")


def _id(entity_type: str, natural_key: str) -> UUID:
    return uuid5(ZIZMOR_NAMESPACE, f"{entity_type}:{natural_key}")


def run_id(collection_job_entity_id: UUID | str) -> UUID:
    """One run node per CollectionJob.

    Keyed on the job rather than on a fresh uuid so that re-importing a run's batch is
    idempotent: the same execution can only ever produce the same run node.
    """
    return _id("zizmor__run", str(collection_job_entity_id))


def finding_id(
    *,
    full_name: str,
    workflow_id_int: int | str,
    audit_id: str,
    route: str,
    persona: str,
    subfeature: str | None = None,
    occurrence: int = 0,
) -> UUID:
    """One finding node per (workflow, audit, symbolic route, persona, narrowed fragment).

    `subfeature` is the fragment the scanner narrowed to inside the located feature — the single
    expression inside a `run:` block. It is load-bearing, not decorative: four `template-injection`
    findings on one step share an audit, a route and a persona, and two of them share a row and
    column as well (*observed* 2026-09-10). The fragment is the only thing that tells them apart,
    so leaving it out of the key would silently collapse four real defects into one.

    `occurrence` disambiguates the case the natural key cannot separate — two findings of the
    same audit at the same route and persona in one run. It is 0 for the ordinary case; the
    collector only increments it on an observed collision, and records that it did, rather than
    letting GRIFT reject the batch on a duplicate id.
    """
    key = f"{full_name}#{workflow_id_int}:{audit_id}:{route}:{persona}"
    if subfeature:
        key = f"{key}:{subfeature}"
    if occurrence:
        key = f"{key}:{occurrence}"
    return _id("zizmor__finding", key)


def edge_id(edge_type: str, source: UUID, target: UUID) -> UUID:
    """Deterministic id for an edge by (type, source, target)."""
    return uuid5(ZIZMOR_NAMESPACE, f"edge:{edge_type}:{source}:{target}")

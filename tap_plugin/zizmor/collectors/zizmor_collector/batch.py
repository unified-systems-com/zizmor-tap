"""GRIFT envelope + batch assembly for the zizmor collector.

Document shape per `tap_grid/schemas/grift-document.schema.json`. One run submits one batch, under
the GRIFT format "1" header core writes for it (`tap_grid.grift.upgrade.build_header`).

These three helpers are the same shape every collector builds by hand, because core publishes no
envelope builder — the GRIFT envelope's structure is currently authored independently in each
plugin, and each copy can drift from the schema on its own. Filed as tap#401; when a shared
builder lands, this module becomes an import.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

COLLECTION_FORMAT = "tap.zizmor.collection-v0"


def node_envelope(
    *,
    entity_id: UUID,
    entity_type: str,
    name: str,
    dimensions: dict[str, str],
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": str(entity_id),
            "entity_type": entity_type,
            "name": name,
            "dimensions": dimensions,
        },
        "node": fields,
    }


def edge_envelope(
    *,
    entity_id: UUID,
    edge_type: str,
    source_id: UUID,
    target_id: UUID,
    dimensions: dict[str, str],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # `entity.entity_type` is the literal "edge"; the slug rides in `entity.name` and
    # `edge.edge_type`. `edge.properties` is required even when empty.
    return {
        "entity": {
            "entity_id": str(entity_id),
            "entity_type": "edge",
            "name": edge_type,
            "dimensions": dimensions,
        },
        "edge": {
            "from_entity_id": str(source_id),
            "to_entity_id": str(target_id),
            "edge_type": edge_type,
            "properties": properties or {},
        },
    }


def assemble_batch(
    *,
    batch_name: str,
    description: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    summary: dict[str, Any],
    batch_dimensions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Wrap nodes + edges into a single-batch GRIFT document with core's format "1" header.

    The header states the spine version and the version of every type the batch carries, read off
    the grid, so this needs the database; the collector only calls it inside a run.
    """
    from tap_grid.grift.upgrade import build_header

    moment = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    batch = {
        "batch_entity": {
            "entity_id": str(uuid7()),
            "entity_type": "batch",
            "name": batch_name,
            "dimensions": batch_dimensions or {"git.host": "github.com"},
        },
        "batch_node": {
            "source": "tap_plugin.zizmor.collectors.zizmor_collector",
            "name": batch_name,
            "description": description,
            "description_json": {
                "format": COLLECTION_FORMAT,
                "collected_at": moment,
                "counts": {"nodes": len(nodes), "edges": len(edges)},
                "run": summary,
            },
        },
        "nodes": nodes,
        "edges": edges,
    }
    document: dict[str, Any] = {"metadata": {}, "_reserved": {}, "batches": [batch]}
    document["metadata"] = build_header(document)
    return document

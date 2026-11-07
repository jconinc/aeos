"""Canonical Memgraph parameter projection for immutable graph snapshots."""

from __future__ import annotations

from typing import Any

from aeos_kernel.canonical import canonical_json, stable_fingerprint
from aeos_kernel.graph import GraphSnapshot


def snapshot_parameters(*, project_key: str, snapshot: GraphSnapshot) -> dict[str, Any]:
    snapshot_key = stable_fingerprint(
        {"project_key": project_key, "digest": snapshot.snapshot_digest}
    )
    node_keys = {
        node.entity_id: stable_fingerprint(
            {"snapshot_key": snapshot_key, "entity_id": node.entity_id}
        )
        for node in snapshot.nodes
    }
    return {
        "project_key": project_key,
        "project_id": snapshot.project_id,
        "vertical_id": snapshot.vertical_id,
        "tenant_id": snapshot.tenant_id,
        "generation": snapshot.generation,
        "snapshot_key": snapshot_key,
        "snapshot_digest": snapshot.snapshot_digest,
        "vocabulary_digest": snapshot.vocabulary_digest,
        "source_heads_json": canonical_json(dict(snapshot.source_head_pins)),
        "built_at": snapshot.built_at.isoformat(),
        "nodes": [
            {
                "entity_key": node_keys[node.entity_id],
                "entity_id": node.entity_id,
                "kind": node.kind,
                "revision": node.revision,
                "content_digest": node.content_digest,
                "privacy_classification": node.privacy_classification.value,
                "properties_json": canonical_json(dict(node.properties)),
            }
            for node in snapshot.nodes
        ],
        "edges": [
            {
                "edge_key": stable_fingerprint(
                    {"snapshot_key": snapshot_key, "edge_id": edge.edge_id}
                ),
                "edge_id": edge.edge_id,
                "kind": edge.kind,
                "from_key": node_keys[edge.from_entity_id],
                "to_key": node_keys[edge.to_entity_id],
                "evidence_json": canonical_json(list(edge.evidence_ids)),
                "properties_json": canonical_json(dict(edge.properties)),
            }
            for edge in snapshot.edges
        ],
    }


def snapshot_from_rows(
    *, project_id: str, vertical_id: str, tenant_id: str, generation: int,
    digest: str, snapshot_key: str, metadata: tuple[Any, ...],
    node_rows: list[tuple[Any, ...]], edge_rows: list[tuple[Any, ...]],
) -> GraphSnapshot:
    """Reconstruct the stored graph, refusing mixed-scope or altered content."""
    import json
    from datetime import datetime

    from aeos_kernel.errors import ContractError
    from aeos_kernel.graph import GraphEdge, GraphNode
    from aeos_kernel.vocabulary import PrivacyClass

    scope = (project_id, vertical_id, tenant_id)
    try:
        if any(tuple(row[6:9]) != scope or tuple(row[9:12]) != scope for row in node_rows):
            raise ContractError("stored graph node is outside snapshot scope")
        if any(tuple(row[6:9]) != scope or tuple(row[9:11]) != (snapshot_key, snapshot_key)
               for row in edge_rows):
            raise ContractError("stored graph edge is outside snapshot scope")
        nodes = tuple(GraphNode(
            entity_id=row[0], kind=row[1], revision=row[2], content_digest=row[3],
            properties=json.loads(row[4]), privacy_classification=PrivacyClass(row[5]),
        ) for row in node_rows)
        edges = tuple(GraphEdge(
            edge_id=row[0], kind=row[1], from_entity_id=row[2], to_entity_id=row[3],
            evidence_ids=tuple(json.loads(row[4])), properties=json.loads(row[5]),
        ) for row in edge_rows)
        result = GraphSnapshot(
            project_id=project_id, vertical_id=vertical_id, tenant_id=tenant_id,
            generation=generation, vocabulary_digest=metadata[0],
            source_head_pins=json.loads(metadata[1]), nodes=nodes, edges=edges,
            built_at=datetime.fromisoformat(metadata[2]), snapshot_digest=digest,
        )
        if not result.has_canonical_digest():
            raise ContractError("stored graph snapshot digest is not canonical")
        return result
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise ContractError("invalid stored graph snapshot") from error

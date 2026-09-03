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

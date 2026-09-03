"""Validation and deterministic assembly of immutable graph snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.graph import GraphEdge, GraphNode, GraphSnapshot
from aeos_kernel.graph_vocabulary import GraphVocabulary


def build_graph_snapshot(
    *,
    project_id: str,
    vertical_id: str,
    tenant_id: str,
    generation: int,
    vocabulary: GraphVocabulary,
    source_head_pins: Mapping[str, str],
    nodes: tuple[GraphNode, ...],
    edges: tuple[GraphEdge, ...],
    built_at: datetime,
) -> GraphSnapshot:
    allowed_nodes = set(vocabulary.node_kinds)
    allowed_edges = set(vocabulary.edge_kinds)
    allowed_properties = set(vocabulary.property_keys)
    for node in nodes:
        if node.kind not in allowed_nodes:
            raise ContractError(f"graph node kind {node.kind!r} is not registered")
        unknown = set(node.properties) - allowed_properties
        if unknown:
            raise ContractError(f"graph node has unregistered properties: {sorted(unknown)}")
    for edge in edges:
        if edge.kind not in allowed_edges:
            raise ContractError(f"graph edge kind {edge.kind!r} is not registered")
        unknown = set(edge.properties) - allowed_properties
        if unknown:
            raise ContractError(f"graph edge has unregistered properties: {sorted(unknown)}")
    values: dict[str, Any] = {
        "project_id": project_id,
        "vertical_id": vertical_id,
        "tenant_id": tenant_id,
        "generation": generation,
        "vocabulary_digest": vocabulary.digest,
        "source_head_pins": source_head_pins,
        "nodes": nodes,
        "edges": edges,
        "built_at": built_at,
    }
    provisional = GraphSnapshot(snapshot_digest="0" * 64, **values)
    return GraphSnapshot(snapshot_digest=stable_fingerprint(provisional.digest_payload()), **values)

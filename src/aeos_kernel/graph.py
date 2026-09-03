"""Project-neutral, privacy-minimized graph projection contracts.

The graph is an advisory read model. Hosts retain canonical evidence, decisions, authority,
effects, and receipts. A projection can be rebuilt from those sources and never grants an
effect or expands a candidate vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel._validation import digest, immutable_json_object, required, thaw_json, utc
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.graph_vocabulary import _unique_clean
from aeos_kernel.vocabulary import PrivacyClass


@dataclass(frozen=True, slots=True)
class GraphNode:
    entity_id: str
    kind: str
    revision: str
    content_digest: str
    properties: Mapping[str, Any]
    privacy_classification: PrivacyClass = PrivacyClass.INTERNAL

    def __post_init__(self) -> None:
        required(self.entity_id, "graph entity_id")
        required(self.kind, "graph node kind")
        required(self.revision, "graph node revision")
        digest(self.content_digest, "graph node content_digest")
        if self.privacy_classification in {PrivacyClass.RESTRICTED, PrivacyClass.PROHIBITED}:
            raise ContractError("restricted or prohibited data cannot enter an AEOS graph")
        object.__setattr__(
            self,
            "properties",
            immutable_json_object(self.properties, "graph node properties"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "properties": thaw_json(self.properties),
            "privacy_classification": self.privacy_classification.value,
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: str
    kind: str
    from_entity_id: str
    to_entity_id: str
    evidence_ids: tuple[str, ...]
    properties: Mapping[str, Any]

    def __post_init__(self) -> None:
        for value, name in (
            (self.edge_id, "graph edge_id"),
            (self.kind, "graph edge kind"),
            (self.from_entity_id, "graph edge from_entity_id"),
            (self.to_entity_id, "graph edge to_entity_id"),
        ):
            required(value, name)
        _unique_clean(self.evidence_ids, "graph edge evidence_ids")
        object.__setattr__(
            self,
            "properties",
            immutable_json_object(self.properties, "graph edge properties"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind,
            "from_entity_id": self.from_entity_id,
            "to_entity_id": self.to_entity_id,
            "evidence_ids": list(self.evidence_ids),
            "properties": thaw_json(self.properties),
        }


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    project_id: str
    vertical_id: str
    tenant_id: str
    generation: int
    vocabulary_digest: str
    source_head_pins: Mapping[str, str]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    built_at: datetime
    snapshot_digest: str
    schema_version: str = "1"

    def __post_init__(self) -> None:
        for value, name in (
            (self.project_id, "graph project_id"),
            (self.vertical_id, "graph vertical_id"),
            (self.tenant_id, "graph tenant_id"),
        ):
            required(value, name)
        if self.schema_version != "1":
            raise ContractError("unsupported graph snapshot schema version")
        if self.generation <= 0:
            raise ContractError("graph generation must be positive")
        digest(self.vocabulary_digest, "graph vocabulary_digest")
        digest(self.snapshot_digest, "graph snapshot_digest")
        if not self.nodes:
            raise ContractError("a graph snapshot must contain at least one node")
        node_ids = [node.entity_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ContractError("graph node identities must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ContractError("graph edge identities must be unique")
        available = set(node_ids)
        for edge in self.edges:
            if edge.from_entity_id not in available or edge.to_entity_id not in available:
                raise ContractError("every graph edge endpoint must exist in the same snapshot")
        if not self.source_head_pins:
            raise ContractError("graph source_head_pins must be nonempty")
        for name, value in self.source_head_pins.items():
            required(str(name), "graph source head name")
            required(value, "graph source head value")
        object.__setattr__(
            self,
            "source_head_pins",
            immutable_json_object(self.source_head_pins, "graph source_head_pins"),
        )
        utc(self.built_at, "graph built_at")

    def digest_payload(self) -> dict[str, object]:
        """Return the reproducible, identity-bearing snapshot content.

        ``built_at`` is receipt metadata rather than source content. Excluding it means a
        crashed publisher can rebuild the same generation from the same pinned sources and
        obtain the same identity instead of manufacturing a conflicting snapshot.
        """

        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "vertical_id": self.vertical_id,
            "tenant_id": self.tenant_id,
            "generation": self.generation,
            "vocabulary_digest": self.vocabulary_digest,
            "source_head_pins": thaw_json(self.source_head_pins),
            "nodes": [
                node.as_dict() for node in sorted(self.nodes, key=lambda item: item.entity_id)
            ],
            "edges": [edge.as_dict() for edge in sorted(self.edges, key=lambda item: item.edge_id)],
        }

    def has_canonical_digest(self) -> bool:
        return self.snapshot_digest == stable_fingerprint(self.digest_payload())

    def as_dict(self) -> dict[str, object]:
        return {
            **self.digest_payload(),
            "built_at": self.built_at.isoformat(),
            "snapshot_digest": self.snapshot_digest,
        }

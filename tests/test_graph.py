from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from aeos_kernel import (
    ContractError,
    GraphEdge,
    GraphNode,
    GraphVocabulary,
    PrivacyClass,
    build_graph_snapshot,
)
from aeos_kernel.adapters.memgraph import SCHEMA_STATEMENTS, MemgraphProjectStore, mgclient_factory

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
VOCABULARY = GraphVocabulary(
    vocabulary_id="example.decision-graph",
    version="1",
    node_kinds=("article", "question"),
    edge_kinds=("answers",),
    property_keys=("title", "text", "score"),
)


def snapshot(*, project_id: str = "project-one", generation: int = 1):
    nodes = (
        GraphNode(
            entity_id="article-1",
            kind="article",
            revision="1",
            content_digest="a" * 64,
            properties={"title": "A steady first hour", "score": 0.8},
            privacy_classification=PrivacyClass.PUBLIC,
        ),
        GraphNode(
            entity_id="question-1",
            kind="question",
            revision="1",
            content_digest="b" * 64,
            properties={"text": "What should I do first?"},
            privacy_classification=PrivacyClass.PUBLIC,
        ),
    )
    edges = (
        GraphEdge(
            edge_id="answers-1",
            kind="answers",
            from_entity_id="article-1",
            to_entity_id="question-1",
            evidence_ids=("article-version-1",),
            properties={"score": 1.0},
        ),
    )
    return build_graph_snapshot(
        project_id=project_id,
        vertical_id="example",
        tenant_id="tenant-one",
        generation=generation,
        vocabulary=VOCABULARY,
        source_head_pins={"database": "snapshot-12"},
        nodes=nodes,
        edges=edges,
        built_at=NOW,
    )


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.errors = errors or {}
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute(self, operation: str, parameters: Any = None) -> object:
        self.executed.append((operation, dict(parameters or {})))
        for marker, error in self.errors.items():
            if marker in operation:
                raise error
        return object()

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self.rows
        self.rows = []
        return rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.autocommit = False
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


def store(connection: FakeConnection) -> MemgraphProjectStore:
    return MemgraphProjectStore(
        project_id="project-one",
        vertical_id="example",
        tenant_id="tenant-one",
        connect=lambda: connection,
    )


def test_graph_snapshot_is_order_stable_and_closed_to_unknown_vocabulary() -> None:
    current = snapshot()
    assert current.has_canonical_digest()
    assert (
        current.snapshot_digest
        == build_graph_snapshot(
            project_id=current.project_id,
            vertical_id=current.vertical_id,
            tenant_id=current.tenant_id,
            generation=current.generation,
            vocabulary=VOCABULARY,
            source_head_pins=current.source_head_pins,
            nodes=tuple(reversed(current.nodes)),
            edges=current.edges,
            built_at=current.built_at,
        ).snapshot_digest
    )
    assert current.as_dict()["snapshot_digest"] == current.snapshot_digest
    assert (
        build_graph_snapshot(
            project_id=current.project_id,
            vertical_id=current.vertical_id,
            tenant_id=current.tenant_id,
            generation=current.generation,
            vocabulary=VOCABULARY,
            source_head_pins=current.source_head_pins,
            nodes=current.nodes,
            edges=current.edges,
            built_at=datetime(2026, 9, 3, 13, 0, tzinfo=UTC),
        ).snapshot_digest
        == current.snapshot_digest
    )

    bad = GraphNode(
        entity_id="channel-1",
        kind="channel",
        revision="1",
        content_digest="c" * 64,
        properties={"title": "Email"},
    )
    with pytest.raises(ContractError, match="not registered"):
        build_graph_snapshot(
            project_id="project-one",
            vertical_id="example",
            tenant_id="tenant-one",
            generation=1,
            vocabulary=VOCABULARY,
            source_head_pins={"database": "snapshot-12"},
            nodes=(bad,),
            edges=(),
            built_at=NOW,
        )

    unknown_property = replace(current.nodes[0], properties={"unknown": True})
    with pytest.raises(ContractError, match="unregistered properties"):
        build_graph_snapshot(
            project_id="project-one",
            vertical_id="example",
            tenant_id="tenant-one",
            generation=1,
            vocabulary=VOCABULARY,
            source_head_pins={"database": "snapshot-12"},
            nodes=(unknown_property,),
            edges=(),
            built_at=NOW,
        )


def test_graph_refuses_sensitive_classification_and_cross_project_edges() -> None:
    with pytest.raises(ContractError, match="cannot enter"):
        GraphNode(
            entity_id="private-1",
            kind="article",
            revision="1",
            content_digest="d" * 64,
            properties={"title": "Private"},
            privacy_classification=PrivacyClass.RESTRICTED,
        )
    dangling = GraphEdge(
        edge_id="bad-edge",
        kind="answers",
        from_entity_id="article-1",
        to_entity_id="other-project-entity",
        evidence_ids=("evidence-1",),
        properties={},
    )
    with pytest.raises(ContractError, match="same snapshot"):
        build_graph_snapshot(
            project_id="project-one",
            vertical_id="example",
            tenant_id="tenant-one",
            generation=1,
            vocabulary=VOCABULARY,
            source_head_pins={"database": "snapshot-12"},
            nodes=(snapshot().nodes[0],),
            edges=(dangling,),
            built_at=NOW,
        )


def test_memgraph_publish_stamps_scope_on_every_stored_row_and_edge() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    publication = store(connection).publish(snapshot())

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed == 1
    assert publication.node_count == 2
    assert publication.edge_count == 1
    assert not publication.already_current
    write_parameters = [params for query, params in cursor.executed if "UNWIND" in query]
    assert len(write_parameters) == 2
    for parameters in write_parameters:
        assert parameters["project_id"] == "project-one"
        assert parameters["vertical_id"] == "example"
        assert parameters["tenant_id"] == "tenant-one"
        assert parameters["snapshot_key"]
    assert write_parameters[1]["edges"][0]["edge_key"]


def test_memgraph_publish_is_idempotent_and_rejects_stale_or_cross_scope_snapshots() -> None:
    current = snapshot()
    cursor = FakeCursor(rows=[(1, current.snapshot_digest)])
    connection = FakeConnection(cursor)
    publication = store(connection).publish(current)
    assert publication.already_current
    assert publication.receipt_digest == replace(publication, already_current=False).receipt_digest
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert len(cursor.executed) == 1

    cross_scope = FakeConnection(FakeCursor())
    with pytest.raises(ContractError, match="outside"):
        store(cross_scope).publish(snapshot(project_id="project-two"))
    assert cross_scope.closed == 0

    changed = snapshot(generation=1)
    stale = FakeConnection(FakeCursor(rows=[(1, "f" * 64)]))
    with pytest.raises(ContractError, match="must advance"):
        store(stale).publish(changed)
    assert stale.rollbacks == 1

    invalid = FakeConnection(FakeCursor())
    with pytest.raises(ContractError, match="not canonical"):
        store(invalid).publish(replace(changed, snapshot_digest="0" * 64))
    assert invalid.closed == 0


def test_memgraph_neighborhood_uses_only_the_bound_current_project() -> None:
    cursor = FakeCursor(
        rows=[
            (
                "answers-1",
                "answers",
                "outgoing",
                "question-1",
                "question",
                "1",
                "b" * 64,
                '{"text":"What should I do first?"}',
            )
        ]
    )
    connection = FakeConnection(cursor)
    result = store(connection).neighborhood("article-1")
    assert result[0]["entity_id"] == "question-1"
    _, params = cursor.executed[0]
    assert params["project_id"] == "project-one"
    assert params["tenant_id"] == "tenant-one"
    assert params["project_key"]


def test_memgraph_schema_is_idempotent_but_other_failures_roll_back() -> None:
    duplicate = FakeConnection(
        FakeCursor(errors={"AEOSSnapshot": RuntimeError("constraint already exists")})
    )
    store(duplicate).ensure_schema()
    assert duplicate.autocommit
    assert duplicate.commits == 0
    assert duplicate.closed == 1
    assert len(duplicate._cursor.executed) == len(SCHEMA_STATEMENTS)

    broken = FakeConnection(FakeCursor(errors={"AEOSEntity": RuntimeError("disk unavailable")}))
    with pytest.raises(RuntimeError, match="disk unavailable"):
        store(broken).ensure_schema()
    assert broken.commits == 0
    assert broken.rollbacks == 1
    assert broken.closed == 1


def test_memgraph_current_snapshot_and_invalid_neighborhood_are_fail_closed() -> None:
    connection = FakeConnection(FakeCursor(rows=[(8, "e" * 64)]))
    assert store(connection).current_snapshot() == (8, "e" * 64)
    assert connection.closed == 1

    unopened = FakeConnection(FakeCursor())
    with pytest.raises(ContractError, match="clean nonempty"):
        store(unopened).neighborhood(" dirty ")
    assert unopened.closed == 0


def test_lazy_mgclient_factory_passes_only_connection_configuration(monkeypatch: Any) -> None:
    received: dict[str, Any] = {}

    def connect(**values: Any) -> FakeConnection:
        received.update(values)
        return FakeConnection(FakeCursor())

    monkeypatch.setitem(sys.modules, "mgclient", SimpleNamespace(connect=connect))
    result = mgclient_factory(
        host="graph.internal", port=7689, username="project", password="secret", sslmode=1
    )()
    assert isinstance(result, FakeConnection)
    assert received == {
        "host": "graph.internal",
        "port": 7689,
        "username": "project",
        "password": "secret",
        "sslmode": 1,
    }

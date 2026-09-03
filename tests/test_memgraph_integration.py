from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import mgclient
import pytest

from aeos_kernel import (
    GraphEdge,
    GraphNode,
    GraphVocabulary,
    PrivacyClass,
    build_graph_snapshot,
)
from aeos_kernel.adapters.memgraph import MemgraphProjectStore, mgclient_factory

pytestmark = pytest.mark.integration

PORT = int(os.environ.get("AEOS_MEMGRAPH_TEST_PORT", "0"))
HOST = os.environ.get("AEOS_MEMGRAPH_TEST_HOST", "127.0.0.1")
USERNAME = os.environ.get("AEOS_MEMGRAPH_TEST_USERNAME", "")
PASSWORD = os.environ.get("AEOS_MEMGRAPH_TEST_PASSWORD", "")
SSLMODE = int(os.environ.get("AEOS_MEMGRAPH_TEST_SSLMODE", "0"))
VOCABULARY = GraphVocabulary(
    vocabulary_id="aeos.integration",
    version="1",
    node_kinds=("article", "question"),
    edge_kinds=("answers",),
    property_keys=("title", "text"),
)


def _snapshot(project_id: str, *, generation: int, title: str):
    return build_graph_snapshot(
        project_id=project_id,
        vertical_id="integration",
        tenant_id="tenant-one",
        generation=generation,
        vocabulary=VOCABULARY,
        source_head_pins={"fixture": f"generation-{generation}"},
        nodes=(
            GraphNode(
                entity_id="article-1",
                kind="article",
                revision=str(generation),
                content_digest=("a" if title == "First" else "c") * 64,
                properties={"title": title},
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
        ),
        edges=(
            GraphEdge(
                edge_id="answers-1",
                kind="answers",
                from_entity_id="article-1",
                to_entity_id="question-1",
                evidence_ids=(f"fixture-{generation}",),
                properties={},
            ),
        ),
        built_at=datetime.now(UTC),
    )


@pytest.mark.skipif(PORT == 0, reason="set AEOS_MEMGRAPH_TEST_PORT to an isolated Memgraph")
def test_real_memgraph_isolation_replay_query_and_concurrent_generation() -> None:
    prefix = f"integration-{uuid4().hex}"
    connect = mgclient_factory(
        host=HOST,
        port=PORT,
        username=USERNAME,
        password=PASSWORD,
        sslmode=SSLMODE,
    )
    first_store = MemgraphProjectStore(
        project_id=f"{prefix}-one",
        vertical_id="integration",
        tenant_id="tenant-one",
        connect=connect,
    )
    second_store = MemgraphProjectStore(
        project_id=f"{prefix}-two",
        vertical_id="integration",
        tenant_id="tenant-one",
        connect=connect,
    )
    first_store.ensure_schema()
    initial = _snapshot(f"{prefix}-one", generation=1, title="First")
    first = first_store.publish(initial)
    replay = first_store.publish(initial)
    second_store.publish(_snapshot(f"{prefix}-two", generation=1, title="Other"))

    assert not first.already_current
    assert replay.already_current
    assert replay.receipt_digest == first.receipt_digest
    assert first_store.neighborhood("article-1")[0]["properties"] == {
        "text": "What should I do first?"
    }
    assert second_store.neighborhood("article-1")[0]["properties"] == {
        "text": "What should I do first?"
    }
    assert first_store.current_snapshot() == (1, initial.snapshot_digest)

    barrier = threading.Barrier(2)

    class BarrierCursor:
        def __init__(self, cursor: Any) -> None:
            self._cursor = cursor

        def execute(self, operation: str, parameters: Any = None) -> Any:
            result = self._cursor.execute(operation, parameters)
            if "RETURN s.generation, s.snapshot_digest" in operation:
                barrier.wait(timeout=5)
            return result

        def fetchone(self) -> Any:
            return self._cursor.fetchone()

        def fetchall(self) -> Any:
            return self._cursor.fetchall()

    class BarrierConnection:
        def __init__(self) -> None:
            self._connection = mgclient.connect(
                host=HOST,
                port=PORT,
                username=USERNAME,
                password=PASSWORD,
                sslmode=SSLMODE,
            )
            self.autocommit = False

        def cursor(self) -> BarrierCursor:
            return BarrierCursor(self._connection.cursor())

        def commit(self) -> None:
            self._connection.commit()

        def rollback(self) -> None:
            self._connection.rollback()

        def close(self) -> None:
            self._connection.close()

    racing_store = MemgraphProjectStore(
        project_id=f"{prefix}-one",
        vertical_id="integration",
        tenant_id="tenant-one",
        connect=BarrierConnection,
    )
    candidates = (
        _snapshot(f"{prefix}-one", generation=2, title="First"),
        _snapshot(f"{prefix}-one", generation=2, title="Changed"),
    )

    def publish_result(candidate: Any) -> tuple[str, Any]:
        try:
            return ("published", racing_store.publish(candidate))
        except Exception as error:  # the losing database transaction must abort
            return ("aborted", error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish_result, candidates))

    assert [status for status, _ in results].count("published") == 1
    assert [status for status, _ in results].count("aborted") == 1
    assert first_store.current_snapshot() in {
        (2, candidates[0].snapshot_digest),
        (2, candidates[1].snapshot_digest),
    }

    for generation in (3, 4, 5):
        first_store.publish(
            _snapshot(f"{prefix}-one", generation=generation, title=f"Generation {generation}")
        )
    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            MATCH (s:AEOSSnapshot {project_id: $project_id, vertical_id: $vertical_id,
                                   tenant_id: $tenant_id})
            RETURN count(s), min(s.generation), max(s.generation)
            """,
            {
                "project_id": f"{prefix}-one",
                "vertical_id": "integration",
                "tenant_id": "tenant-one",
            },
        )
        assert cursor.fetchone() == (3, 3, 5)
    finally:
        connection.close()

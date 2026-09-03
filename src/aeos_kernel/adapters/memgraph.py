"""Memgraph persistence for immutable, project-bound AEOS graph snapshots.

The store accepts no caller-supplied Cypher. Its fixed query set is the security boundary;
product-specific discovery remains in vertical adapters and supplies only graph contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from aeos_kernel.adapters.memgraph_driver import (
    ConnectionFactory,
    Cursor,
)
from aeos_kernel.adapters.memgraph_driver import (
    mgclient_factory as mgclient_factory,
)
from aeos_kernel.adapters.memgraph_queries import (
    CREATE_EDGES,
    CREATE_ENTITIES,
    CREATE_SNAPSHOT,
    CURRENT_SNAPSHOT,
    FLIP_CURRENT,
    NEIGHBORHOOD,
    SCHEMA_STATEMENTS,
    UPSERT_PROJECT,
)
from aeos_kernel.adapters.memgraph_serialization import snapshot_parameters
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError
from aeos_kernel.graph import GraphSnapshot


@dataclass(frozen=True, slots=True)
class SnapshotPublication:
    project_id: str
    generation: int
    snapshot_digest: str
    node_count: int
    edge_count: int
    already_current: bool

    @property
    def receipt_digest(self) -> str:
        return stable_fingerprint(
            {
                "project_id": self.project_id,
                "generation": self.generation,
                "snapshot_digest": self.snapshot_digest,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
            }
        )


class MemgraphProjectStore:
    """A store bound to one isolated project endpoint and tenant."""

    def __init__(
        self,
        *,
        project_id: str,
        vertical_id: str,
        tenant_id: str,
        connect: ConnectionFactory,
    ) -> None:
        if not project_id or not vertical_id or not tenant_id:
            raise ContractError("Memgraph store scope must be nonempty")
        self._project_id = project_id
        self._vertical_id = vertical_id
        self._tenant_id = tenant_id
        self._connect = connect

    def ensure_schema(self) -> None:
        connection = self._connect()
        try:
            # Memgraph schema DDL is legal only in implicit auto-commit transactions.
            connection.autocommit = True
            cursor = connection.cursor()
            for statement in SCHEMA_STATEMENTS:
                try:
                    cursor.execute(statement)
                except Exception as error:
                    message = str(error).lower()
                    if not any(item in message for item in ("already exists", "equivalent")):
                        raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def publish(self, snapshot: GraphSnapshot) -> SnapshotPublication:
        self._validate_snapshot(snapshot)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            current = self._current_row(cursor)
            if current is not None and str(current[1]) == snapshot.snapshot_digest:
                connection.rollback()
                return self._publication(snapshot, already_current=True)
            if current is not None and int(current[0]) >= snapshot.generation:
                raise ContractError("graph generation must advance when the snapshot changes")
            params = snapshot_parameters(project_key=self._project_key, snapshot=snapshot)
            cursor.execute(UPSERT_PROJECT, params)
            cursor.execute(CREATE_SNAPSHOT, params)
            cursor.execute(CREATE_ENTITIES, params)
            cursor.execute(CREATE_EDGES, params)
            cursor.execute(FLIP_CURRENT, params)
            connection.commit()
            return self._publication(snapshot, already_current=False)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def current_snapshot(self) -> tuple[int, str] | None:
        connection = self._connect()
        try:
            return self._current_row(connection.cursor())
        finally:
            connection.close()

    def neighborhood(self, entity_id: str) -> tuple[dict[str, Any], ...]:
        if not entity_id or entity_id != entity_id.strip():
            raise ContractError("graph entity_id must be a clean nonempty string")
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                NEIGHBORHOOD,
                {
                    "project_key": self._project_key,
                    "project_id": self._project_id,
                    "vertical_id": self._vertical_id,
                    "tenant_id": self._tenant_id,
                    "entity_id": entity_id,
                },
            )
            rows = cursor.fetchall()
            return tuple(
                {
                    "edge_id": str(row[0]),
                    "edge_kind": str(row[1]),
                    "direction": str(row[2]),
                    "entity_id": str(row[3]),
                    "entity_kind": str(row[4]),
                    "revision": str(row[5]),
                    "content_digest": str(row[6]),
                    "properties": json.loads(str(row[7])),
                }
                for row in rows
            )
        finally:
            connection.close()

    @property
    def _project_key(self) -> str:
        return stable_fingerprint(
            {
                "project_id": self._project_id,
                "vertical_id": self._vertical_id,
                "tenant_id": self._tenant_id,
            }
        )

    def _validate_snapshot(self, snapshot: GraphSnapshot) -> None:
        if not snapshot.has_canonical_digest():
            raise ContractError("graph snapshot digest is not canonical")
        actual = (snapshot.project_id, snapshot.vertical_id, snapshot.tenant_id)
        expected = (self._project_id, self._vertical_id, self._tenant_id)
        if actual != expected:
            raise ContractError("graph snapshot is outside the bound project scope")

    def _current_row(self, cursor: Cursor) -> tuple[int, str] | None:
        cursor.execute(
            CURRENT_SNAPSHOT,
            {
                "project_key": self._project_key,
                "project_id": self._project_id,
                "vertical_id": self._vertical_id,
                "tenant_id": self._tenant_id,
            },
        )
        row = cursor.fetchone()
        return None if row is None else cast(tuple[int, str], row)

    @staticmethod
    def _publication(snapshot: GraphSnapshot, *, already_current: bool) -> SnapshotPublication:
        return SnapshotPublication(
            project_id=snapshot.project_id,
            generation=snapshot.generation,
            snapshot_digest=snapshot.snapshot_digest,
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            already_current=already_current,
        )

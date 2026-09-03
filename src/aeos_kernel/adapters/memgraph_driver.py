"""Small DB-API boundary for the optional Memgraph driver."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast


class Cursor(Protocol):
    def execute(self, operation: str, parameters: Mapping[str, Any] | None = None) -> object: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...


class Connection(Protocol):
    autocommit: bool

    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]


def mgclient_factory(
    *, host: str, port: int, username: str = "", password: str = "", sslmode: int = 0
) -> ConnectionFactory:
    """Build a lazy pymgclient connection factory without a mandatory dependency."""

    def connect() -> Connection:
        try:
            import mgclient
        except ImportError as error:  # pragma: no cover - environment boundary
            raise RuntimeError("install aeos-kernel[memgraph] to connect to Memgraph") from error
        return cast(
            Connection,
            mgclient.connect(
                host=host,
                port=port,
                username=username,
                password=password,
                sslmode=sslmode,
            ),
        )

    return connect

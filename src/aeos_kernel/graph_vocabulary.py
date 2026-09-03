"""Closed graph vocabulary contracts owned by vertical adapters."""

from __future__ import annotations

from dataclasses import dataclass

from aeos_kernel._validation import required
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError


def _unique_clean(values: tuple[str, ...], field_name: str) -> None:
    if not values or len(values) != len(set(values)):
        raise ContractError(f"{field_name} must be nonempty and unique")
    for value in values:
        required(value, field_name)


@dataclass(frozen=True, slots=True)
class GraphVocabulary:
    """One adapter-owned closed graph vocabulary."""

    vocabulary_id: str
    version: str
    node_kinds: tuple[str, ...]
    edge_kinds: tuple[str, ...]
    property_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        required(self.vocabulary_id, "vocabulary_id")
        required(self.version, "vocabulary version")
        _unique_clean(self.node_kinds, "node_kinds")
        _unique_clean(self.edge_kinds, "edge_kinds")
        _unique_clean(self.property_keys, "property_keys")

    @property
    def digest(self) -> str:
        return stable_fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "vocabulary_id": self.vocabulary_id,
            "version": self.version,
            "node_kinds": list(self.node_kinds),
            "edge_kinds": list(self.edge_kinds),
            "property_keys": list(self.property_keys),
        }

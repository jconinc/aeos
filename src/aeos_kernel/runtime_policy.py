"""PB-232 policy compilation before a governed network attempt.

This pure contract cannot admit a connection. The Wema adapter must first resolve the
current PB-167 binding, PB-169 work fence and active policy heads, then enforce the
result at the actual connect boundary. Missing inputs never become an allow decision.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from uuid import UUID

from aeos_kernel._validation import digest, required
from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.errors import ContractError

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


def _key(value: str, name: str) -> str:
    required(value, name)
    if not _KEY.fullmatch(value):
        raise ContractError(f"{name} is not a canonical key")
    return value


def _reference(value: str, name: str, *, limit: int = 256) -> str:
    required(value, name)
    if len(value) > limit:
        raise ContractError(f"{name} is too long")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{name} must be a positive integer")
    return value


def _unique(values: tuple[object, ...], name: str) -> None:
    if len(values) != len(set(values)):
        raise ContractError(f"{name} contains duplicates")


def _host(value: str) -> str:
    if not isinstance(value, str) or not value.isascii() or value != value.lower():
        raise ContractError("host must be a lower-case IDNA DNS name")
    if len(value) > 253 or value.endswith(".") or value.startswith("."):
        raise ContractError("host must be a canonical DNS name")
    labels = value.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise ContractError("host must be a canonical DNS name")
    if all(label.isdecimal() for label in labels):
        raise ContractError("host cannot look like an IP literal")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ContractError("host cannot be an IP literal")
    for label in labels:
        if label.startswith("xn--"):
            try:
                if label.encode("ascii").decode("idna").encode("idna").decode("ascii") != label:
                    raise ContractError("host has a noncanonical IDNA label")
            except UnicodeError as error:
                raise ContractError("host has an invalid IDNA label") from error
    return value


@dataclass(frozen=True, slots=True)
class HostTarget:
    """One exact host, port and protocol purpose; never a URL or wildcard."""

    scheme: str
    host: str
    port: int
    purpose: str

    def __post_init__(self) -> None:
        if self.scheme not in {"http", "https"}:
            raise ContractError("host scheme is not supported")
        _host(self.host)
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ContractError("host port must be between 1 and 65535")
        _key(self.purpose, "host purpose")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "purpose": self.purpose,
        }


@dataclass(frozen=True, slots=True)
class TransportBinding:
    """A source-inventoried route for one tool and exact transport authority."""

    target: HostTarget
    tool_key: str
    transport_authority: str
    source_root: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, HostTarget):
            raise ContractError("transport target must be a HostTarget")
        _key(self.tool_key, "tool key")
        _reference(self.transport_authority, "transport authority")
        _reference(self.source_root, "source root")

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target.as_dict(),
            "tool_key": self.tool_key,
            "transport_authority": self.transport_authority,
            "source_root": self.source_root,
        }


def transport_inventory_digest(bindings: tuple[TransportBinding, ...]) -> str:
    """Bind policy compilation to a complete, unique source inventory."""
    _unique(tuple((b.source_root, b.target, b.tool_key) for b in bindings), "transport inventory")
    return stable_fingerprint(
        [
            b.as_dict()
            for b in sorted(
                bindings,
                key=lambda b: (
                    b.source_root,
                    b.tool_key,
                    b.target.host,
                    b.target.scheme,
                    b.target.port,
                    b.target.purpose,
                ),
            )
        ]
    )


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """The exact platform policy payload supplied by an active version reader."""

    policy_id: UUID
    generation: int
    allowed_hosts: tuple[HostTarget, ...]
    untrusted_sources: tuple[str, ...]
    prompt_boundary: str
    go_live_mode: str
    at_rest_required: bool
    in_transit_required: bool
    key_rotation_days: int
    audit_retention_days: int
    source_inventory_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, UUID):
            raise ContractError("policy id must be a UUID")
        _positive(self.generation, "policy generation")
        if not isinstance(self.allowed_hosts, tuple) or not isinstance(
            self.untrusted_sources, tuple
        ):
            raise ContractError("policy lists must be immutable tuples")
        if any(not isinstance(host, HostTarget) for host in self.allowed_hosts):
            raise ContractError("platform allowed hosts must be canonical targets")
        _unique(self.allowed_hosts, "platform allowed hosts")
        _unique(self.untrusted_sources, "untrusted sources")
        for source in self.untrusted_sources:
            _key(source, "untrusted source")
        if self.prompt_boundary != "write":
            raise ContractError("prompt injection boundary must be write")
        if self.go_live_mode not in {"staging", "live"}:
            raise ContractError("policy mode is not recognized")
        if not isinstance(self.at_rest_required, bool) or not isinstance(
            self.in_transit_required, bool
        ):
            raise ContractError("encryption policy must use booleans")
        _positive(self.key_rotation_days, "key rotation days")
        _positive(self.audit_retention_days, "audit retention days")
        digest(self.source_inventory_digest, "source inventory digest")


@dataclass(frozen=True, slots=True)
class ProductSecurity:
    """A product selection derived by the source-owned Manifest.security parser."""

    product_slug: str
    manifest_digest: str
    selected_hosts: tuple[HostTarget, ...] | None
    untrusted_sources: tuple[str, ...]
    go_live_mode: str
    at_rest_required: bool
    in_transit_required: bool
    key_rotation_days: int
    audit_retention_days: int

    def __post_init__(self) -> None:
        _reference(self.product_slug, "product slug", limit=128)
        digest(self.manifest_digest, "manifest digest")
        if self.selected_hosts is not None:
            if not isinstance(self.selected_hosts, tuple):
                raise ContractError("product selected hosts must be an immutable tuple")
            if any(not isinstance(host, HostTarget) for host in self.selected_hosts):
                raise ContractError("product selected hosts must be canonical targets")
            _unique(self.selected_hosts, "product selected hosts")
        if not isinstance(self.untrusted_sources, tuple):
            raise ContractError("product untrusted sources must be an immutable tuple")
        _unique(self.untrusted_sources, "product untrusted sources")
        for source in self.untrusted_sources:
            _key(source, "untrusted source")
        if self.go_live_mode not in {"staging", "live"}:
            raise ContractError("product mode is not recognized")
        if not isinstance(self.at_rest_required, bool) or not isinstance(
            self.in_transit_required, bool
        ):
            raise ContractError("product encryption policy must use booleans")
        _positive(self.key_rotation_days, "product key rotation days")
        _positive(self.audit_retention_days, "product audit retention days")


@dataclass(frozen=True, slots=True)
class PermissionLaneIdentity:
    """Exact authenticated PB-167 permission and role/scope generation."""

    permission_id: UUID
    binding_id: UUID
    binding_generation: int
    permission_generation: int
    product_slug: str
    tool_key: str
    move_types: tuple[str, ...]
    egress_reference: str
    role_scope_epoch: int

    def __post_init__(self) -> None:
        if not isinstance(self.permission_id, UUID) or not isinstance(self.binding_id, UUID):
            raise ContractError("permission and binding ids must be UUIDs")
        _positive(self.binding_generation, "binding generation")
        _positive(self.permission_generation, "permission generation")
        _reference(self.product_slug, "permission product", limit=128)
        _key(self.tool_key, "permission tool")
        if not isinstance(self.move_types, tuple) or not self.move_types:
            raise ContractError("permission Move scope must be a nonempty tuple")
        for move_type in self.move_types:
            _reference(move_type, "permission Move type", limit=128)
        if tuple(sorted(set(self.move_types))) != self.move_types:
            raise ContractError("permission Move scope must be canonical")
        _reference(self.egress_reference, "permission egress reference")
        _positive(self.role_scope_epoch, "role scope epoch")


@dataclass(frozen=True, slots=True)
class ToolEgressScope:
    """An already authenticated PB-167 grant's requested host scope."""

    product_slug: str
    move_type: str
    tool_key: str
    permission_generation: int
    hosts: tuple[HostTarget, ...]
    permission_lane: PermissionLaneIdentity

    def __post_init__(self) -> None:
        _reference(self.product_slug, "product slug", limit=128)
        _reference(self.move_type, "Move type", limit=128)
        _key(self.tool_key, "tool key")
        _positive(self.permission_generation, "permission generation")
        if not isinstance(self.permission_lane, PermissionLaneIdentity) or (
            self.permission_lane.product_slug != self.product_slug
            or self.permission_lane.tool_key != self.tool_key
            or self.permission_lane.permission_generation != self.permission_generation
            or self.move_type not in self.permission_lane.move_types
        ):
            raise ContractError("tool scope does not match its exact permission lane")
        if not isinstance(self.hosts, tuple):
            raise ContractError("tool hosts must be an immutable tuple")
        if any(not isinstance(host, HostTarget) for host in self.hosts):
            raise ContractError("tool hosts must be canonical targets")
        _unique(self.hosts, "tool egress scope")


@dataclass(frozen=True, slots=True)
class EffectiveRuntimePolicy:
    platform_policy_id: UUID
    platform_generation: int
    manifest_digest: str | None
    permission_generation: int
    permission_lane: PermissionLaneIdentity
    allowed_hosts: tuple[HostTarget, ...]
    untrusted_sources: tuple[str, ...]
    go_live_mode: str
    at_rest_required: bool
    in_transit_required: bool
    key_rotation_days: int
    audit_retention_days: int

    def permits(self, target: HostTarget) -> bool:
        """A pure scope check, not network or effect admission."""
        return target in self.allowed_hosts


def compile_runtime_policy(
    *,
    platform: RuntimePolicy | None,
    product: ProductSecurity | None,
    tool_scope: ToolEgressScope | None,
    transport_inventory: tuple[TransportBinding, ...],
) -> EffectiveRuntimePolicy:
    """Intersect current scopes; fail closed on missing, stale or overbroad inputs.

    Product ``selected_hosts=None`` means no selection restriction. An empty tuple
    selects no hosts. No live mode is issued here: SEC-061/C42 is a separate gate.
    """
    if platform is None or tool_scope is None:
        raise ContractError("runtime policy or authenticated tool scope is unavailable")
    if transport_inventory_digest(transport_inventory) != platform.source_inventory_digest:
        raise ContractError("runtime policy source inventory is stale")
    inventory = {(binding.target, binding.tool_key) for binding in transport_inventory}
    platform_hosts = set(platform.allowed_hosts)
    if any(not any(target == bound for bound, _ in inventory) for target in platform_hosts):
        raise ContractError("platform host has no source-inventoried transport")
    selected = platform_hosts
    if product is not None:
        if product.product_slug != tool_scope.product_slug:
            raise ContractError("product policy does not match the authenticated tool scope")
        if product.selected_hosts is not None:
            selected = set(product.selected_hosts)
            if not selected <= platform_hosts:
                raise ContractError("product selection exceeds the platform ceiling")
    scope_hosts = set(tool_scope.hosts)
    if not scope_hosts <= selected:
        raise ContractError("tool scope exceeds the effective host ceiling")
    if any((target, tool_scope.tool_key) not in inventory for target in scope_hosts):
        raise ContractError("tool scope has no source-inventoried transport")
    at_rest = platform.at_rest_required or (product.at_rest_required if product else False)
    in_transit = platform.in_transit_required or (product.in_transit_required if product else False)
    if in_transit and any(target.scheme != "https" for target in scope_hosts):
        raise ContractError("an unencrypted host exceeds the effective transport policy")
    return EffectiveRuntimePolicy(
        platform_policy_id=platform.policy_id,
        platform_generation=platform.generation,
        manifest_digest=product.manifest_digest if product else None,
        permission_generation=tool_scope.permission_generation,
        permission_lane=tool_scope.permission_lane,
        allowed_hosts=tuple(
            sorted(scope_hosts, key=lambda h: (h.host, h.scheme, h.port, h.purpose))
        ),
        untrusted_sources=tuple(
            sorted(
                set(platform.untrusted_sources) | set(product.untrusted_sources if product else ())
            )
        ),
        go_live_mode="staging",
        at_rest_required=at_rest,
        in_transit_required=in_transit,
        key_rotation_days=min(
            platform.key_rotation_days,
            product.key_rotation_days if product else platform.key_rotation_days,
        ),
        audit_retention_days=max(
            platform.audit_retention_days,
            product.audit_retention_days if product else platform.audit_retention_days,
        ),
    )

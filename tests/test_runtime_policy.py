"""PB-232 §2: canonical, source-bound policy compilation stays default-deny."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.runtime_policy import (
    HostTarget,
    PermissionLaneIdentity,
    ProductSecurity,
    RuntimePolicy,
    ToolEgressScope,
    TransportBinding,
    compile_runtime_policy,
    transport_inventory_digest,
)

A = HostTarget("https", "a.example.com", 443, "model_call")
B = HostTarget("https", "b.example.com", 443, "model_call")
C = HostTarget("https", "c.example.com", 443, "model_call")
INVENTORY = (
    TransportBinding(A, "model", "guarded_http", "hosted_assistance"),
    TransportBinding(B, "model", "guarded_http", "hosted_assistance"),
    TransportBinding(C, "model", "guarded_http", "hosted_assistance"),
)


def _platform(**changes: object) -> RuntimePolicy:
    values = {
        "policy_id": UUID("00000000-0000-4000-8000-000000000001"),
        "generation": 1,
        "allowed_hosts": (A, B),
        "untrusted_sources": ("email",),
        "prompt_boundary": "write",
        "go_live_mode": "live",
        "at_rest_required": True,
        "in_transit_required": True,
        "key_rotation_days": 90,
        "audit_retention_days": 30,
        "source_inventory_digest": transport_inventory_digest(INVENTORY),
    }
    values.update(changes)
    return RuntimePolicy(**values)  # type: ignore[arg-type]


def _product(**changes: object) -> ProductSecurity:
    values = {
        "product_slug": "care",
        "manifest_digest": "a" * 64,
        "selected_hosts": (A,),
        "untrusted_sources": ("web",),
        "go_live_mode": "live",
        "at_rest_required": True,
        "in_transit_required": True,
        "key_rotation_days": 30,
        "audit_retention_days": 60,
    }
    values.update(changes)
    return ProductSecurity(**values)  # type: ignore[arg-type]


def _tool(*hosts: HostTarget) -> ToolEgressScope:
    lane = PermissionLaneIdentity(
        permission_id=UUID("00000000-0000-4000-8000-000000000010"),
        binding_id=UUID("00000000-0000-4000-8000-000000000011"),
        binding_generation=2,
        permission_generation=3,
        product_slug="care",
        tool_key="model",
        move_types=("draft_reply",),
        egress_reference="guarded_http",
        role_scope_epoch=4,
    )
    return ToolEgressScope("care", "draft_reply", "model", 3, hosts, lane)


def test_exact_intersection_and_tightening_are_staging_only() -> None:
    effective = compile_runtime_policy(
        platform=_platform(),
        product=_product(),
        tool_scope=_tool(A),
        transport_inventory=INVENTORY,
    )
    assert effective.allowed_hosts == (A,)
    assert effective.permits(A)
    assert not effective.permits(B)
    assert effective.untrusted_sources == ("email", "web")
    assert effective.go_live_mode == "staging"
    assert effective.at_rest_required and effective.in_transit_required
    assert effective.key_rotation_days == 30
    assert effective.audit_retention_days == 60
    assert effective.permission_generation == 3
    assert effective.permission_lane == _tool(A).permission_lane
    assert effective.manifest_digest == "a" * 64


def test_absent_product_selection_uses_platform_ceiling_but_empty_selection_denies() -> None:
    effective = compile_runtime_policy(
        platform=_platform(),
        product=_product(selected_hosts=None),
        tool_scope=_tool(B),
        transport_inventory=INVENTORY,
    )
    assert effective.allowed_hosts == (B,)
    with pytest.raises(ContractError, match="tool scope exceeds"):
        compile_runtime_policy(
            platform=_platform(),
            product=_product(selected_hosts=()),
            tool_scope=_tool(B),
            transport_inventory=INVENTORY,
        )
    denied = compile_runtime_policy(
        platform=_platform(),
        product=_product(selected_hosts=()),
        tool_scope=_tool(),
        transport_inventory=INVENTORY,
    )
    assert denied.allowed_hosts == ()


@pytest.mark.parametrize(
    ("platform", "product", "tool", "inventory", "reason"),
    [
        (None, _product(), _tool(A), INVENTORY, "unavailable"),
        (_platform(), _product(), None, INVENTORY, "unavailable"),
        (_platform(), _product(selected_hosts=(A, C)), _tool(A), INVENTORY, "platform ceiling"),
        (_platform(), _product(), _tool(B), INVENTORY, "tool scope exceeds"),
        (_platform(), _product(product_slug="other"), _tool(A), INVENTORY, "does not match"),
        (
            _platform(source_inventory_digest="0" * 64),
            _product(),
            _tool(A),
            INVENTORY,
            "inventory is stale",
        ),
    ],
)
def test_missing_stale_and_overbroad_inputs_refuse(
    platform: RuntimePolicy | None,
    product: ProductSecurity | None,
    tool: ToolEgressScope | None,
    inventory: tuple[TransportBinding, ...],
    reason: str,
) -> None:
    with pytest.raises(ContractError, match=reason):
        compile_runtime_policy(
            platform=platform, product=product, tool_scope=tool, transport_inventory=inventory
        )


def test_tool_scope_must_name_its_exact_inventoried_transport() -> None:
    other_tool = replace(INVENTORY[0], tool_key="other")
    inventory = (other_tool, *INVENTORY[1:])
    with pytest.raises(ContractError, match="no source-inventoried transport"):
        compile_runtime_policy(
            platform=_platform(source_inventory_digest=transport_inventory_digest(inventory)),
            product=_product(),
            tool_scope=_tool(A),
            transport_inventory=inventory,
        )


def test_duplicate_inventory_and_unused_allowlist_entry_refuse() -> None:
    with pytest.raises(ContractError, match="transport inventory contains duplicates"):
        transport_inventory_digest((*INVENTORY, INVENTORY[0]))
    missing = INVENTORY[:2]
    with pytest.raises(ContractError, match="platform host"):
        compile_runtime_policy(
            platform=_platform(
                allowed_hosts=(A, C), source_inventory_digest=transport_inventory_digest(missing)
            ),
            product=_product(),
            tool_scope=_tool(A),
            transport_inventory=missing,
        )


def test_distinct_source_roots_can_share_one_guarded_route() -> None:
    other_root = replace(INVENTORY[0], source_root="another_source")
    inventory = (*INVENTORY, other_root)
    digest = transport_inventory_digest(inventory)
    assert digest == transport_inventory_digest(tuple(reversed(inventory)))
    assert digest != transport_inventory_digest(INVENTORY)
    effective = compile_runtime_policy(
        platform=_platform(source_inventory_digest=digest),
        product=_product(),
        tool_scope=_tool(A),
        transport_inventory=inventory,
    )
    assert effective.allowed_hosts == (A,)
    with pytest.raises(ContractError, match="inventory is stale"):
        compile_runtime_policy(
            platform=_platform(),
            product=_product(),
            tool_scope=_tool(A),
            transport_inventory=inventory,
        )


def test_same_source_root_duplicate_or_conflicting_authority_refuses() -> None:
    with pytest.raises(ContractError, match="transport inventory contains duplicates"):
        transport_inventory_digest((*INVENTORY, INVENTORY[0]))
    conflicting = replace(INVENTORY[0], transport_authority="other_guard")
    with pytest.raises(ContractError, match="transport inventory contains duplicates"):
        transport_inventory_digest((*INVENTORY, conflicting))


@pytest.mark.parametrize(
    "host",
    [
        "A.example.com",
        "a.example.com.",
        "*.example.com",
        "127.0.0.1",
        "999.999.999.999",
        "a.example.com/path",
        "a.example.com?token=x",
        "name:password@example.com",
        "münich.example.com",
        "localhost",
        "-a.example.com",
        "xn--broken-.example.com",
    ],
)
def test_noncanonical_or_ambiguous_host_refuses(host: str) -> None:
    with pytest.raises(ContractError, match="host"):
        HostTarget("https", host, 443, "model_call")


def test_canonical_idna_label_and_strict_policy_fields() -> None:
    assert HostTarget("https", "xn--mnich-kva.example.com", 443, "model_call").host == (
        "xn--mnich-kva.example.com"
    )
    with pytest.raises(ContractError, match="boundary"):
        _platform(prompt_boundary="read")
    with pytest.raises(ContractError, match="duplicates"):
        _platform(allowed_hosts=(A, A))
    with pytest.raises(ContractError, match="duplicates"):
        _product(untrusted_sources=("email", "email"))
    with pytest.raises(ContractError, match="positive"):
        _platform(key_rotation_days=0)
    with pytest.raises(ContractError, match="port"):
        HostTarget("https", "a.example.com", True, "model_call")


def test_effective_in_transit_requirement_refuses_plain_http() -> None:
    plain = HostTarget("http", "a.example.com", 80, "model_call")
    inventory = (TransportBinding(plain, "model", "guarded_http", "hosted_assistance"),)
    with pytest.raises(ContractError, match="unencrypted host"):
        compile_runtime_policy(
            platform=_platform(
                allowed_hosts=(plain,),
                source_inventory_digest=transport_inventory_digest(inventory),
            ),
            product=_product(selected_hosts=(plain,)),
            tool_scope=_tool(plain),
            transport_inventory=inventory,
        )


def test_authenticated_tool_scope_refuses_mutable_or_uncanonical_hosts() -> None:
    with pytest.raises(ContractError, match="tool hosts must be an immutable tuple"):
        replace(_tool(A), hosts=[A])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="tool hosts must be canonical targets"):
        replace(_tool(A), hosts=("a.example.com",))  # type: ignore[arg-type]

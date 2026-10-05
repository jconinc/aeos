"""E3: approved security is versioned, closed and separately owned."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from typing import Any

import pytest

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section, required_authority_class
from aeos_kernel.product_policy import load_canonical_manifest
from aeos_kernel.product_policy_v2 import (
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2,
    load_canonical_manifest_v2,
)
from aeos_kernel.product_policy_v3 import (
    READER_CAPABILITIES_V3,
    SCHEMA_VERSION_V3,
    load_canonical_manifest_v3,
    policy_leaf_paths_v3,
    section_paths_v3,
)


def candidate(profile: str = "base") -> dict[str, Any]:
    version = "v2" if profile == "correction_sweep" else "v1"
    source = files("aeos_kernel.schemas").joinpath(
        "product_policy", f"canonical_manifest_{version}.json"
    )
    payload = json.loads(source.read_text())
    payload.update(
        schema_version=SCHEMA_VERSION_V3,
        manifest_profile=profile,
        security={
            "selected_hosts": [
                {"scheme": "https", "host": "example.org", "port": 443, "purpose": "model_call"}
            ],
            "untrusted_sources": ["model_output"],
            "go_live_mode": "staging",
            "at_rest_required": True,
            "in_transit_required": True,
            "key_rotation_days": 30,
            "audit_retention_days": 90,
        },
    )
    payload["compatibility"].update(min_reader="3.0.0", max_reader="3.9.0")
    payload["compatibility"]["required_capabilities"] += list(READER_CAPABILITIES_V3)
    return dict(payload)


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_closed_profiles_preserve_policy_and_approval_coverage(profile: str) -> None:
    policy = load_canonical_manifest_v3(candidate(profile))
    assert policy.reader_compatible(available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2)
    if profile == "correction_sweep":
        assert not policy.reader_compatible()
        assert policy.correction_sweep
    paths = [path for section in section_paths_v3(profile).values() for path in section]
    assert len(paths) == len(set(paths))
    assert set(paths) == set(policy_leaf_paths_v3(policy.payload))
    assert policy.section("product_security") == {"security": policy.payload["security"]}
    security = policy.product_security("example")
    assert security.manifest_digest == policy.manifest_digest
    assert security.selected_hosts is not None and security.selected_hosts[0].host == "example.org"
    assert load_canonical_manifest_v3(policy.canonical_bytes) == policy
    assert (
        command_section(
            "record_manifest_decision", "product_security", schema_version=SCHEMA_VERSION_V3
        )
        == "product_security"
    )
    assert (
        required_authority_class(
            "record_manifest_decision", "product_security", schema_version=SCHEMA_VERSION_V3
        )
        == "security_role"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("key_rotation_days", 0),
        ("audit_retention_days", True),
        ("go_live_mode", "automatic"),
        ("at_rest_required", 1),
        ("untrusted_sources", ["bad/source"]),
        (
            "selected_hosts",
            [{"scheme": "https", "host": "example.org", "port": 99999, "purpose": "model_call"}],
        ),
    ],
)
def test_invalid_security_never_projects(field: str, value: Any) -> None:
    payload = candidate()
    payload["security"][field] = value
    with pytest.raises(ContractError):
        load_canonical_manifest_v3(payload)


def test_missing_unknown_wrong_identity_and_legacy_security_refuse() -> None:
    payload = candidate()
    with pytest.raises(ContractError):
        load_canonical_manifest_v3(payload, product_id="0190f2a4-1b2c-7d3e-8f40-000000000002")
    for mutate in (
        lambda p: p.pop("security"),
        lambda p: p["security"].update(extra=True),
        lambda p: p.update(manifest_profile="unknown"),
    ):
        bad = copy.deepcopy(payload)
        mutate(bad)
        with pytest.raises(ContractError):
            load_canonical_manifest_v3(bad)
    for version, loader in (("v1", load_canonical_manifest), ("v2", load_canonical_manifest_v2)):
        bad = copy.deepcopy(payload)
        bad["schema_version"] = f"aeos.product-manifest.{version}"
        with pytest.raises(ContractError):
            loader(bad)


def test_explicit_inheritance_is_distinct_from_deny_all_and_policy_change_changes_digest() -> None:
    payload = candidate()
    payload["security"]["selected_hosts"] = None
    inherited = load_canonical_manifest_v3(payload)
    assert inherited.product_security("example").selected_hosts is None
    payload["security"]["selected_hosts"] = []
    denied = load_canonical_manifest_v3(payload)
    assert denied.product_security("example").selected_hosts == ()
    assert inherited.manifest_digest != denied.manifest_digest

"""PB-224: only a complete, explicitly adopted host policy may fill the v5 source binding."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section, required_authority_class
from aeos_kernel.product_policy import load_canonical_manifest
from aeos_kernel.product_policy_v2 import (
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2,
    load_canonical_manifest_v2,
)
from aeos_kernel.product_policy_v3 import load_canonical_manifest_v3
from aeos_kernel.product_policy_v4 import load_canonical_manifest_v4
from aeos_kernel.product_policy_v5 import (
    REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5,
    SCHEMA_VERSION_V5,
    load_canonical_manifest_v5,
    policy_leaf_paths_v5,
    section_paths_v5,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
HOST_CAPABILITIES = (
    REQUIRED_SWEEP_HOST_CAPABILITIES_V2 | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
)


def candidate(profile: str = "base") -> dict[str, Any]:
    return dict(json.loads(SCHEMAS.joinpath(f"canonical_manifest_v5_{profile}.json").read_text()))


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_canonical_bound_policy_keeps_complete_sections_and_requires_host(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v5(payload)
    assert policy.reader_compatible(available_capabilities=HOST_CAPABILITIES)
    assert not policy.reader_compatible(available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2)
    assert not policy.reader_compatible("4.0.0", available_capabilities=HOST_CAPABILITIES)
    assert policy.support_measure_policy_binding == (
        payload["source_bindings"]["support_measure_policy"]
    )
    assert load_canonical_manifest_v5(policy.canonical_bytes) == policy
    assert policy.cac_ltv_thresholds == payload["commercial"]["cac_ltv_thresholds"]
    if profile == "correction_sweep":
        assert policy.correction_sweep == payload["correction_sweep"]
    assert set(policy_leaf_paths_v5(policy.payload)) == {
        path for paths in section_paths_v5(profile).values() for path in paths
    }
    assert command_section("record_manifest_decision", "source_bindings",
                           schema_version=SCHEMA_VERSION_V5) == "source_bindings"
    assert required_authority_class("record_manifest_decision", "source_bindings",
                                    schema_version=SCHEMA_VERSION_V5) == "support_owner"


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_explicit_unadopted_policy_has_no_implicit_values(profile: str) -> None:
    payload = candidate(profile)
    payload["source_bindings"]["support_measure_policy"] = None
    payload["compatibility"]["required_capabilities"].remove("support_measure_policy_source_v1")
    policy = load_canonical_manifest_v5(payload)
    assert policy.support_measure_policy_binding is None
    assert policy.reader_compatible(available_capabilities=REQUIRED_SWEEP_HOST_CAPABILITIES_V2)


@pytest.mark.parametrize("change", ["missing", "digest", "unknown", "version", "capability"])
def test_malformed_or_unavailable_source_contract_refuses(change: str) -> None:
    payload = candidate()
    binding = payload["source_bindings"]["support_measure_policy"]
    if change == "missing":
        del payload["source_bindings"]["support_measure_policy"]
    elif change == "capability":
        payload["compatibility"]["required_capabilities"].remove("support_measure_policy_source_v1")
    else:
        binding[{"digest": "digest", "unknown": "target_hours", "version": "version"}[change]] = {
            "digest": "invalid", "unknown": 24, "version": "",
        }[change]
    with pytest.raises(ContractError):
        load_canonical_manifest_v5(payload)


@pytest.mark.parametrize("loader", [load_canonical_manifest, load_canonical_manifest_v2,
                                  load_canonical_manifest_v3, load_canonical_manifest_v4])
def test_historical_reader_rejects_new_binding(loader: Any) -> None:
    with pytest.raises(ContractError):
        loader(candidate())


def test_policy_digest_tracks_binding_without_changing_grant_set() -> None:
    payload = candidate()
    old = load_canonical_manifest_v5(payload)
    payload["source_bindings"]["support_measure_policy"]["digest"] = "2" * 64
    new = load_canonical_manifest_v5(payload)
    assert old.manifest_digest != new.manifest_digest
    assert old.grant_set_digest == new.grant_set_digest
    assert old.section("source_bindings") != new.section("source_bindings")


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_packaged_fictional_vectors_match_parser_and_structural_schema(profile: str) -> None:
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v5_{profile}.vectors.json").read_text()
    )
    literal = SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    policy = load_canonical_manifest_v5(literal)
    assert SCHEMAS.joinpath(vector["input"]).read_bytes() == literal == policy.canonical_bytes
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    validator = Draft202012Validator(json.loads(SCHEMAS.joinpath(vector["schema"]).read_text()))
    validator.check_schema(validator.schema)
    validator.validate(json.loads(literal))
    malformed = json.loads(literal)
    malformed["source_bindings"]["support_measure_policy"]["unexpected"] = True
    with pytest.raises(ValidationError):
        validator.validate(malformed)

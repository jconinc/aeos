"""Probe spending limits and Authority signal methods are policy data, never approval."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section, required_authority_class
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import REQUIRED_WLG_HOST_CAPABILITIES_V6
from aeos_kernel.product_policy_v7 import load_canonical_manifest_v7
from aeos_kernel.product_policy_v8 import (
    PROBE_SPENDING_KEYS,
    SCHEMA_VERSION_V8,
    load_canonical_manifest_v8,
    policy_leaf_paths_v8,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
HOST_CAPABILITIES = (REQUIRED_SWEEP_HOST_CAPABILITIES_V2
                     | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
                     | REQUIRED_WLG_HOST_CAPABILITIES_V6)
#: Synthetic test limits only; they are no product's approved amounts.
SET_LIMITS: dict[str, Any] = {
    "window_days": 7,
    "per_call_ceiling_minor": "25",
    "window_ceiling_minor": "100",
    "daily_ceiling_minor": "50",
    "monthly_ceiling_minor": "500",
}


def candidate(profile: str = "base") -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(f"canonical_manifest_v8_{profile}.json").read_text())


def schema(version: int) -> Draft202012Validator:
    return Draft202012Validator(json.loads(
        SCHEMAS.joinpath(f"product_manifest_v{version}.schema.json").read_text()
    ))


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_frozen_policy_places_limits_in_budget_and_methods_in_targets(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v8(payload)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v8_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    prior = load_canonical_manifest_v7(
        SCHEMAS.joinpath(f"canonical_manifest_v7_{profile}.canonical").read_bytes()
    )
    assert policy.grant_set_digest == prior.grant_set_digest
    assert policy.authority_score_formula == prior.authority_score_formula
    assert policy.probe_spending == dict.fromkeys(PROBE_SPENDING_KEYS)
    assert policy.reader_compatible(available_capabilities=HOST_CAPABILITIES)
    assert not policy.reader_compatible("7.0.0", available_capabilities=HOST_CAPABILITIES)
    leaves = policy_leaf_paths_v8(policy.payload)
    assert {"authority.brand_search_methodology", "authority.platform_set"} <= set(leaves)
    budget = policy.section("budget")["authority.probe_budget"]
    assert set(PROBE_SPENDING_KEYS) <= set(budget)
    targets = policy.section("authority_targets")
    assert targets["authority.platform_set"] == policy.payload["authority"]["platform_set"]
    owners = {"budget": "finance_owner", "authority_targets": "authority_owner"}
    for section, owner in owners.items():
        assert command_section("record_manifest_decision", section,
                               schema_version=SCHEMA_VERSION_V8) == section
        assert required_authority_class("record_manifest_decision", section,
                                        schema_version=SCHEMA_VERSION_V8) == owner
    schema(8).validate(payload)
    with pytest.raises(ContractError):
        load_canonical_manifest_v7(payload)


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v7_parser_schema_and_vectors_are_unchanged(profile: str) -> None:
    payload = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v7_{profile}.json").read_text()
    )
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v7_{profile}.vectors.json").read_text()
    )
    policy = load_canonical_manifest_v7(payload)
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    for key in ("brand_search_methodology", *PROBE_SPENDING_KEYS):
        changed = json.loads(json.dumps(payload))
        target = changed["authority"] if key == "brand_search_methodology" else (
            changed["authority"]["probe_budget"]
        )
        target[key] = None
        with pytest.raises(ContractError):
            load_canonical_manifest_v7(changed)
        with pytest.raises(ValidationError):
            schema(7).validate(changed)


def test_complete_ordered_limits_load_as_canonical_minor_units() -> None:
    payload = candidate()
    payload["authority"]["probe_budget"].update(SET_LIMITS, per_call_ceiling_minor="+025")
    policy = load_canonical_manifest_v8(payload)
    assert policy.probe_spending == SET_LIMITS
    assert load_canonical_manifest_v8(policy.canonical_bytes) == policy
    payload["authority"]["probe_budget"]["per_call_ceiling_minor"] = "25"
    schema(8).validate(payload)
    # Equal ceilings are allowed: each bound is "at most".
    payload["authority"]["probe_budget"].update(
        per_call_ceiling_minor="50", window_ceiling_minor="50", monthly_ceiling_minor="50"
    )
    assert load_canonical_manifest_v8(payload).probe_spending["monthly_ceiling_minor"] == "50"


PARTIAL = [f"only_{key}_null" for key in PROBE_SPENDING_KEYS] + [
    f"only_{key}_set" for key in PROBE_SPENDING_KEYS
]


@pytest.mark.parametrize("change", PARTIAL)
def test_partly_set_limits_refuse_in_parser_and_schema(change: str) -> None:
    payload = candidate()
    budget = payload["authority"]["probe_budget"]
    key = change.removeprefix("only_").rsplit("_", 1)[0]
    if change.endswith("_null"):
        budget.update(SET_LIMITS)
        budget[key] = None
    else:
        budget[key] = SET_LIMITS[key]
    with pytest.raises(ContractError, match="is null while other spending limits are set"):
        load_canonical_manifest_v8(payload)
    with pytest.raises(ValidationError):
        schema(8).validate(payload)


@pytest.mark.parametrize(("change", "message"), [
    ({"per_call_ceiling_minor": "101"}, "exceeds window_ceiling_minor"),
    ({"per_call_ceiling_minor": "51", "window_ceiling_minor": "200"},
     "exceeds daily_ceiling_minor"),
    ({"daily_ceiling_minor": "501"}, "exceeds monthly_ceiling_minor"),
])
def test_misordered_limits_refuse(change: dict[str, str], message: str) -> None:
    payload = candidate()
    payload["authority"]["probe_budget"].update(SET_LIMITS, **change)
    with pytest.raises(ContractError, match=message):
        load_canonical_manifest_v8(payload)


@pytest.mark.parametrize("change", [
    "zero_money", "negative_money", "number_money", "zero_days", "string_days", "bool_days",
    "missing_key", "extra_budget_key", "missing_method", "extra_authority_key", "method_case",
    "empty_platforms", "platform_extra_field", "capability",
])
def test_malformed_limits_or_methods_refuse(change: str) -> None:
    payload = candidate("correction_sweep")
    authority = payload["authority"]
    budget = authority["probe_budget"]
    budget.update(SET_LIMITS)
    if change == "zero_money":
        budget["window_ceiling_minor"] = "0"
    elif change == "negative_money":
        budget["window_ceiling_minor"] = "-100"
    elif change == "number_money":
        budget["window_ceiling_minor"] = 100
    elif change == "zero_days":
        budget["window_days"] = 0
    elif change == "string_days":
        budget["window_days"] = "7"
    elif change == "bool_days":
        budget["window_days"] = True
    elif change == "missing_key":
        del budget["monthly_ceiling_minor"]
    elif change == "extra_budget_key":
        budget["per_engine_ceiling_minor"] = "10"
    elif change == "missing_method":
        del authority["platform_set"]
    elif change == "extra_authority_key":
        authority["platform_count"] = 2
    elif change == "method_case":
        authority["brand_search_methodology"] = "Example_Brand_Search_v1"
    elif change == "empty_platforms":
        authority["platform_set"]["platform_keys"] = []
    elif change == "platform_extra_field":
        authority["platform_set"]["approved"] = True
    else:
        payload["compatibility"]["required_capabilities"].remove("authority_probe_spending_v1")
    with pytest.raises(ContractError):
        load_canonical_manifest_v8(payload)


def test_changed_limits_change_only_the_budget_section_and_never_grants() -> None:
    original = load_canonical_manifest_v8(candidate())
    payload = candidate()
    payload["authority"]["probe_budget"].update(SET_LIMITS)
    changed = load_canonical_manifest_v8(payload)
    assert changed.manifest_digest != original.manifest_digest
    assert changed.section("budget") != original.section("budget")
    assert changed.section("authority_targets") == original.section("authority_targets")
    assert changed.grant_set_digest == original.grant_set_digest
    assert changed.section("product_security") == original.section("product_security")


def test_optional_paid_pilot_policy_passes_through_v8_unchanged() -> None:
    from tests.test_product_policy_paid_pilot import fictional_policy, sealed

    payload = candidate()
    policy = sealed(fictional_policy(payload["product_instance_id"]))
    payload["commercial"]["paid_pilot_policy"] = policy
    loaded = load_canonical_manifest_v8(payload)
    assert loaded.payload["commercial"]["paid_pilot_policy"]["policy_digest"] == (
        policy["policy_digest"]
    )
    assert "commercial.paid_pilot_policy" in loaded.section("commercial_terms")
    schema(8).validate(payload)

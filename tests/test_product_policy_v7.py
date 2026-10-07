"""PB-187: exact Authority formula is policy data, never implicit approval or a grant."""

from __future__ import annotations

import json
from decimal import localcontext
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import command_section, required_authority_class
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import (
    REQUIRED_WLG_HOST_CAPABILITIES_V6,
    load_canonical_manifest_v6,
)
from aeos_kernel.product_policy_v7 import (
    SCHEMA_VERSION_V7,
    load_canonical_manifest_v7,
    policy_leaf_paths_v7,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
HOST_CAPABILITIES = (REQUIRED_SWEEP_HOST_CAPABILITIES_V2
                     | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
                     | REQUIRED_WLG_HOST_CAPABILITIES_V6)


def candidate(profile: str = "base") -> dict[str, Any]:
    return json.loads(SCHEMAS.joinpath(f"canonical_manifest_v7_{profile}.json").read_text())


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_frozen_complete_policy_retains_prior_grants_and_formula_ownership(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v7(payload)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v7_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    prior = load_canonical_manifest_v6(
        SCHEMAS.joinpath(f"canonical_manifest_v6_{profile}.canonical").read_bytes()
    )
    assert policy.grant_set_digest == prior.grant_set_digest
    assert policy.payload["security"] == prior.payload["security"]
    assert policy.cac_ltv_thresholds == prior.cac_ltv_thresholds
    assert policy.reader_compatible(available_capabilities=HOST_CAPABILITIES)
    assert not policy.reader_compatible("6.0.0", available_capabilities=HOST_CAPABILITIES)
    assert "authority.score_formula" in policy_leaf_paths_v7(policy.payload)
    assert policy.section("authority_targets")["authority.score_formula"] == (
        policy.payload["authority"]["score_formula"]
    )
    assert command_section("record_manifest_decision", "authority_targets",
                           schema_version=SCHEMA_VERSION_V7) == "authority_targets"
    assert required_authority_class("record_manifest_decision", "authority_targets",
                                    schema_version=SCHEMA_VERSION_V7) == "authority_owner"
    Draft202012Validator(
        json.loads(SCHEMAS.joinpath("product_manifest_v7.schema.json").read_text())
    ).validate(payload)
    with pytest.raises(ContractError):
        load_canonical_manifest_v6(payload)


@pytest.mark.parametrize("change", [
    "missing", "extra", "missing_component", "unknown_component", "number",
    "sum", "zero_weight", "target", "bool_precision", "precision", "rounding",
    "citation_type", "negative_citation_weight", "mixed_sign", "capability",
])
def test_absent_or_ambiguous_formula_refuses_complete_manifest(change: str) -> None:
    payload = candidate()
    formula = payload["authority"]["score_formula"]
    term = formula["components"]["earned_citation_count"]
    if change == "missing":
        del payload["authority"]["score_formula"]
    elif change == "extra":
        formula["approve"] = True
    elif change == "missing_component":
        del formula["components"]["brand_search_index"]
    elif change == "unknown_component":
        formula["components"]["likes"] = dict(term)
    elif change == "number":
        term["weight"] = 0.2
    elif change == "sum":
        term["weight"] = "0.20000000000000000000000000000000000001"
    elif change == "zero_weight":
        term["weight"] = "0"
    elif change == "target":
        term["target"] = term["lower_anchor"]
    elif change == "bool_precision":
        formula["precision"] = True
    elif change == "precision":
        formula["precision"] = 3
    elif change == "rounding":
        formula["rounding"] = "half_up"
    elif change == "citation_type":
        formula["citation_authority_weights"]["social"] = "1"
    elif change == "negative_citation_weight":
        formula["citation_authority_weights"]["journalist"] = "-1"
    elif change == "mixed_sign":
        term["lower_anchor"] = "-+1"
    else:
        payload["compatibility"]["required_capabilities"].remove("authority_score_formula_v1")
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ContractError):
            load_canonical_manifest_v7(payload)


def test_exact_decimal_weights_and_signed_anchors_do_not_depend_on_ambient_precision() -> None:
    payload = candidate()
    terms = payload["authority"]["score_formula"]["components"]
    terms["earned_citation_count"]["weight"] = "0.10000000000000000000000000000000000001"
    terms["source_diversity_count"]["weight"] = "0.29999999999999999999999999999999999999"
    terms["brand_search_index"]["lower_anchor"] = "-0001.5000"
    with localcontext() as context:
        context.prec = 2
        policy = load_canonical_manifest_v7(payload)
    formula = policy.authority_score_formula
    assert formula["components"]["brand_search_index"]["lower_anchor"] == "-1.5"
    formula["components"]["brand_search_index"]["target"] = "1"
    assert policy.authority_score_formula["components"]["brand_search_index"]["target"] == "100"
    assert load_canonical_manifest_v7(policy.canonical_bytes) == policy


def test_changed_formula_changes_approval_section_and_manifest_but_never_grants() -> None:
    payload = candidate()
    original = load_canonical_manifest_v7(payload)
    payload["authority"]["score_formula"]["components"]["brand_search_index"]["target"] = "101"
    changed = load_canonical_manifest_v7(payload)
    assert changed.manifest_digest != original.manifest_digest
    assert changed.section("authority_targets") != original.section("authority_targets")
    assert changed.grant_set_digest == original.grant_set_digest
    assert changed.section("product_security") == original.section("product_security")

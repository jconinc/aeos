"""Manifest v9 lets the four probe money limits be an approved 0; nothing else changes."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.errors import ContractError
from aeos_kernel.policy_authority import required_authority_class
from aeos_kernel.product_policy_v2 import REQUIRED_SWEEP_HOST_CAPABILITIES_V2
from aeos_kernel.product_policy_v5 import REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
from aeos_kernel.product_policy_v6 import REQUIRED_WLG_HOST_CAPABILITIES_V6
from aeos_kernel.product_policy_v8 import PROBE_SPENDING_KEYS, load_canonical_manifest_v8
from aeos_kernel.product_policy_v9 import (
    PROBE_MONEY_KEYS,
    SCHEMA_VERSION_V9,
    load_canonical_manifest_v9,
)

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")
HOST_CAPABILITIES = (REQUIRED_SWEEP_HOST_CAPABILITIES_V2
                     | REQUIRED_SUPPORT_MEASURE_HOST_CAPABILITIES_V5
                     | REQUIRED_WLG_HOST_CAPABILITIES_V6)
ZEROS: dict[str, Any] = {
    "window_days": 7,
    "per_call_ceiling_minor": "0",
    "window_ceiling_minor": "0",
    "daily_ceiling_minor": "0",
    "monthly_ceiling_minor": "0",
}
#: Synthetic test limits only; they are no product's approved amounts.
SET_LIMITS: dict[str, Any] = {
    "window_days": 7,
    "per_call_ceiling_minor": "25",
    "window_ceiling_minor": "100",
    "daily_ceiling_minor": "50",
    "monthly_ceiling_minor": "500",
}


def candidate(profile: str = "base", **limits: Any) -> dict[str, Any]:
    payload = json.loads(SCHEMAS.joinpath(f"canonical_manifest_v9_{profile}.json").read_text())
    payload["authority"]["probe_budget"].update(limits)
    return payload


def schema() -> Draft202012Validator:
    return Draft202012Validator(json.loads(
        SCHEMAS.joinpath("product_manifest_v9.schema.json").read_text()
    ))


def as_v8(payload: dict[str, Any]) -> dict[str, Any]:
    changed = json.loads(json.dumps(payload))
    changed["schema_version"] = "aeos.product-manifest.v8"
    return changed


@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_v9_vectors_round_trip(profile: str) -> None:
    payload = candidate(profile)
    policy = load_canonical_manifest_v9(payload)
    vector = json.loads(
        SCHEMAS.joinpath(f"canonical_manifest_v9_{profile}.vectors.json").read_text()
    )
    assert policy.canonical_bytes == SCHEMAS.joinpath(vector["canonical_bytes"]).read_bytes()
    assert policy.manifest_digest == vector["manifest_sha256"]
    assert policy.grant_set_digest == vector["grant_set_sha256"]
    assert load_canonical_manifest_v9(policy.canonical_bytes) == policy
    assert policy.reader_compatible(available_capabilities=HOST_CAPABILITIES)
    assert not policy.reader_compatible("8.0.0", available_capabilities=HOST_CAPABILITIES)
    assert required_authority_class(
        "record_manifest_decision", "budget", schema_version=SCHEMA_VERSION_V9
    ) == "finance_owner"
    schema().validate(payload)


def test_vectors_cover_an_approved_zero_and_not_approved() -> None:
    assert load_canonical_manifest_v9(candidate("base")).probe_spending == ZEROS
    assert load_canonical_manifest_v9(candidate("correction_sweep")).probe_spending == dict.fromkeys(
        PROBE_SPENDING_KEYS
    )


#: The ordering rules make some zeros imply others: per-call is at most window and daily, and
#: daily is at most monthly. Each case sets the named key to 0 and the least else that allows it.
ZERO_WITH = {
    "per_call_ceiling_minor": ("per_call_ceiling_minor",),
    "window_ceiling_minor": ("per_call_ceiling_minor", "window_ceiling_minor"),
    "daily_ceiling_minor": ("per_call_ceiling_minor", "daily_ceiling_minor"),
    "monthly_ceiling_minor": PROBE_MONEY_KEYS,
}


@pytest.mark.parametrize("key", PROBE_MONEY_KEYS)
def test_each_money_key_accepts_zero(key: str) -> None:
    limits = {**SET_LIMITS, **dict.fromkeys(ZERO_WITH[key], "0")}
    payload = candidate(**limits)
    assert load_canonical_manifest_v9(payload).probe_spending[key] == "0"
    schema().validate(payload)


def test_all_four_at_zero_with_a_positive_window() -> None:
    policy = load_canonical_manifest_v9(candidate(**ZEROS))
    assert policy.probe_spending == ZEROS
    assert load_canonical_manifest_v9(policy.canonical_bytes).probe_spending == ZEROS
    assert load_canonical_manifest_v9(candidate(per_call_ceiling_minor="+000")).probe_spending[
        "per_call_ceiling_minor"
    ] == "0"


def test_positive_amounts_still_load() -> None:
    assert load_canonical_manifest_v9(candidate(**SET_LIMITS)).probe_spending == SET_LIMITS


def test_all_null_is_still_not_approved() -> None:
    payload = candidate(**dict.fromkeys(PROBE_SPENDING_KEYS))
    assert load_canonical_manifest_v9(payload).probe_spending == dict.fromkeys(PROBE_SPENDING_KEYS)
    schema().validate(payload)


REFUSED = {
    "window_days_zero": ({"window_days": 0}, "positive"),
    "negative_amount": ({"daily_ceiling_minor": "-1"}, ""),
    "non_numeric": ({"monthly_ceiling_minor": "free"}, ""),
    "decimal_amount": ({"window_ceiling_minor": "0.5"}, ""),
    "number_not_string": ({"per_call_ceiling_minor": 0}, ""),
}


@pytest.mark.parametrize("name", REFUSED)
def test_v9_still_refuses_invalid_limits(name: str) -> None:
    change, _ = REFUSED[name]
    payload = candidate(**ZEROS)
    payload["authority"]["probe_budget"].update(change)
    with pytest.raises(ContractError):
        load_canonical_manifest_v9(payload)
    with pytest.raises(ValidationError):
        schema().validate(payload)


@pytest.mark.parametrize("key", PROBE_SPENDING_KEYS)
@pytest.mark.parametrize("mode", ["one_null", "one_set"])
def test_v9_refuses_a_mix_of_null_and_set(key: str, mode: str) -> None:
    payload = candidate(**(ZEROS if mode == "one_null" else dict.fromkeys(PROBE_SPENDING_KEYS)))
    payload["authority"]["probe_budget"][key] = None if mode == "one_null" else ZEROS[key]
    with pytest.raises(ContractError, match="is null while other spending limits are set"):
        load_canonical_manifest_v9(payload)
    with pytest.raises(ValidationError):
        schema().validate(payload)


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        ({"per_call_ceiling_minor": "1"}, "exceeds window_ceiling_minor"),
        ({"per_call_ceiling_minor": "1", "window_ceiling_minor": "5"}, "exceeds daily_ceiling_minor"),
        ({"daily_ceiling_minor": "1", "per_call_ceiling_minor": "0", "monthly_ceiling_minor": "0"},
         "exceeds monthly_ceiling_minor"),
    ],
)
def test_v9_keeps_the_ordering_rules(limits: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message):
        load_canonical_manifest_v9(candidate(**{**ZEROS, **limits}))


def test_v8_still_refuses_zero_and_v9_manifest_is_not_v8() -> None:
    zeros = candidate(**ZEROS)
    with pytest.raises(ContractError):
        load_canonical_manifest_v8(as_v8(zeros))
    with pytest.raises(ContractError):
        load_canonical_manifest_v9(as_v8(zeros))
    with pytest.raises(ContractError):
        load_canonical_manifest_v8(zeros)
    v8_schema = Draft202012Validator(json.loads(
        SCHEMAS.joinpath("product_manifest_v8.schema.json").read_text()
    ))
    with pytest.raises(ValidationError):
        v8_schema.validate(as_v8(zeros))


def test_v9_requires_its_own_capabilities() -> None:
    payload = candidate(**ZEROS)
    caps = payload["compatibility"]["required_capabilities"]
    payload["compatibility"]["required_capabilities"] = [
        c for c in caps if c != "authority_probe_spending_v2"
    ]
    with pytest.raises(ContractError, match="every v9 capability"):
        load_canonical_manifest_v9(payload)

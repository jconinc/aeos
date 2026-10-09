"""03a's optional ``commercial.paid_pilot_policy``: absent stays valid, present is complete."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from importlib import resources
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aeos_kernel.product_policy import (
    SECTION_PATHS,
    ManifestContractError,
    load_canonical_manifest,
    policy_leaf_paths,
)
from aeos_kernel.product_policy_v2 import (
    SECTION_PATHS_V2,
    load_canonical_manifest_v2,
    policy_leaf_paths_v2,
)
from aeos_kernel.product_policy_v3 import load_canonical_manifest_v3, section_paths_v3
from aeos_kernel.product_policy_v4 import load_canonical_manifest_v4, section_paths_v4
from aeos_kernel.product_policy_v5 import load_canonical_manifest_v5, section_paths_v5
from aeos_kernel.product_policy_v6 import load_canonical_manifest_v6, section_paths_v6
from aeos_kernel.product_policy_v7 import load_canonical_manifest_v7, section_paths_v7

VECTORS = resources.files("aeos_kernel.schemas").joinpath("product_policy")
POLICY = "manifest.commercial.paid_pilot_policy"
LOADERS: dict[str, Callable[..., Any]] = {
    "v1": load_canonical_manifest,
    "v2": load_canonical_manifest_v2,
    "v3_base": load_canonical_manifest_v3,
    "v3_correction_sweep": load_canonical_manifest_v3,
    "v4_base": load_canonical_manifest_v4,
    "v4_correction_sweep": load_canonical_manifest_v4,
    "v5_base": load_canonical_manifest_v5,
    "v5_correction_sweep": load_canonical_manifest_v5,
    "v6_base": load_canonical_manifest_v6,
    "v6_correction_sweep": load_canonical_manifest_v6,
    "v7_base": load_canonical_manifest_v7,
    "v7_correction_sweep": load_canonical_manifest_v7,
}
#: Each version's section paths for a profile ("" before v3).
SECTION_PATHS_BY_VERSION: dict[str, Callable[[str], Mapping[str, tuple[str, ...]]]] = {
    "v1": lambda profile: SECTION_PATHS,
    "v2": lambda profile: SECTION_PATHS_V2,
    "v3": section_paths_v3,
    "v4": section_paths_v4,
    "v5": section_paths_v5,
    "v6": section_paths_v6,
    "v7": section_paths_v7,
}
#: SHA-256 of each packaged, policy-free vector's complete section views, as aeos-kernel 0.16.0
#: (14648fd) returned them: compact JSON of ``{section: manifest.section(section)}`` by name.
SECTIONS_0_16_0 = {
    "v1": "fe00dd7f77833150b57ba4c4e203fb7900e6b38eb13df7b3f08282417594670c",
    "v2": "76357dc663f05d6ede95bb17cc1d74a93ae3bf8fb867ec2b56e6a6e101669744",
    "v3_base": "739c501df3aa23bce3017ffbc483bf03b63274b5422d088c23db4eb834362f31",
    "v3_correction_sweep": "ee341802b62368ff497272d3d5dcec3ed7e0c595e1bedd6fd3dd32ed95ac6119",
    "v4_base": "4fbbc3eeda412b5a8eb53367c88097080bd8c57be5ad247698aa82e1bff770aa",
    "v4_correction_sweep": "209742fcbd4c72189f6ae791bd91e15b1f81c24f488e0d050109e17e65f9f5ae",
    "v5_base": "9f9838093da5e5ad4abcb03b517e46aaebe2d99918e21cc7b1c2f1f1fe0e931c",
    "v5_correction_sweep": "bf8f70c93b36ae3485504f32cda27c29086365adf4ebd0f82806b68e37a408ac",
    "v6_base": "d4901316eee7fa3f3689480a467930897042f35cfd8b5049a5d7150e79532101",
    "v6_correction_sweep": "30f9120a5b51d4c2551f645853ab942841ac8fa015e10bebcd0e615c0119cfce",
    "v7_base": "d06e2ef919846f7621d52e6572568157b13f69596c66efd18be36916738e8d4a",
    "v7_correction_sweep": "83bf61e218119bee2583483ea1948f54887795c1ba0647150609baacd50aa946",
}
#: The pinned digest of the fictional v1 policy below; it moves only if its bytes do.
V1_POLICY_DIGEST = "8cfa221ba5b4b6acf0482568e635913ba2014532ce1f1107ac9e94f7644c157b"


def candidate(name: str = "v1") -> dict[str, Any]:
    return dict(json.loads(VECTORS.joinpath(f"canonical_manifest_{name}.json").read_text()))


def digest_of(policy: dict[str, Any]) -> str:
    body = {key: value for key, value in policy.items() if key != "policy_digest"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sealed(policy: dict[str, Any]) -> dict[str, Any]:
    return {**policy, "policy_digest": digest_of(policy)}


def fictional_policy(product_id: str) -> dict[str, Any]:
    """A complete fictional policy; no field is an adopted owner value."""

    return {
        "schema_version": "PaidPilotPolicy@1",
        "product_id": product_id.lower(),
        "qualification_criteria": [
            {"ref": "fixture:criteria/second", "version": "2", "digest": "b" * 64},
            {"ref": "fixture:criteria/first", "version": "1", "digest": "a" * 64},
        ],
        "eligible_offers": [
            {"sku": "fixture-sku-2", "offer_id": "fixture-offer-2"},
            {"sku": "fixture-sku-1", "offer_id": "fixture-offer-1"},
        ],
        "currency": "USD",
        "minimum_net_collected_minor": 1,
        "distinct_by": "opportunity",
        "partial_refund_rule": "net_threshold",
        "reconciliation_max_age_seconds": 1,
        "coverage_start": "2026-01-01T00:00:00Z",
    }


def with_policy(name: str = "v1", policy: Any = None, *, seal: bool = True) -> dict[str, Any]:
    payload = candidate(name)
    if policy is None:
        policy = fictional_policy(payload["product_instance_id"])
    payload["commercial"]["paid_pilot_policy"] = sealed(policy) if seal else policy
    return payload


def changed(edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    policy = fictional_policy(candidate()["product_instance_id"])
    edit(policy)
    return policy


def refusal(payload: dict[str, Any], name: str = "v1") -> ManifestContractError:
    with pytest.raises(ManifestContractError) as caught:
        LOADERS[name](payload)
    return caught.value


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_absence_stays_valid_and_keeps_every_published_vector(name: str) -> None:
    manifest = LOADERS[name](candidate(name))
    literal = VECTORS.joinpath(f"canonical_manifest_{name}.canonical").read_bytes()
    assert manifest.canonical_bytes == literal
    assert "paid_pilot_policy" not in manifest.payload["commercial"]


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_every_manifest_version_keeps_one_complete_policy_exactly(name: str) -> None:
    payload = with_policy(name)
    supplied = copy.deepcopy(payload["commercial"]["paid_pilot_policy"])
    manifest = LOADERS[name](payload)
    assert json.loads(manifest.canonical_bytes)["commercial"]["paid_pilot_policy"] == supplied
    assert LOADERS[name](manifest.canonical_bytes).canonical_bytes == manifest.canonical_bytes
    assert manifest.manifest_digest != LOADERS[name](candidate(name)).manifest_digest

    other = fictional_policy("00000000-0000-4000-8000-000000000000")
    error = refusal(with_policy(name, other), name)
    assert (error.path, error.reason_code) == (f"{POLICY}.product_id", "manifest_identity_mismatch")
    error = refusal(with_policy(name, changed(lambda p: p.update(pilot_floor=1))), name)
    assert error.path == f"{POLICY}.pilot_floor"


@pytest.mark.parametrize("name", sorted(LOADERS))
def test_the_policy_is_a_commercial_terms_leaf_and_absence_keeps_every_section(name: str) -> None:
    version, _, profile = name.partition("_")
    paths = SECTION_PATHS_BY_VERSION[version](profile)
    leaves = policy_leaf_paths if version == "v1" else policy_leaf_paths_v2
    payload = with_policy(name)
    manifest = LOADERS[name](payload)
    assert sorted(path for section in paths.values() for path in section) == sorted(
        leaves(manifest.payload)
    )
    terms = manifest.section("commercial_terms")
    assert terms["commercial.paid_pilot_policy"] == payload["commercial"]["paid_pilot_policy"]

    absent = LOADERS[name](candidate(name))
    assert "commercial.paid_pilot_policy" not in absent.section("commercial_terms")
    views = {section: absent.section(section) for section in sorted(paths)}
    text = json.dumps(views, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(text.encode()).hexdigest() == SECTIONS_0_16_0[name]


def schema_for(name: str) -> Draft202012Validator:
    version = name.partition("_")[0]
    schema = VECTORS.joinpath(f"product_manifest_{version}.schema.json").read_text()
    return Draft202012Validator(json.loads(schema))


@pytest.mark.parametrize("name", sorted(set(LOADERS) - {"v1"}))
def test_the_published_v2_to_v7_schemas_accept_a_complete_policy(name: str) -> None:
    schema_for(name).validate(with_policy(name))


@pytest.mark.parametrize("name", sorted(set(LOADERS) - {"v1"}))
def test_the_published_schemas_refuse_an_unknown_policy_key(name: str) -> None:
    payload = with_policy(name)
    payload["commercial"]["paid_pilot_policy"]["pilot_floor"] = 1
    errors = list(schema_for(name).iter_errors(payload))
    assert [(list(error.absolute_path), error.validator) for error in errors] == [
        (["commercial", "paid_pilot_policy"], "additionalProperties")
    ]


def test_policy_digest_is_the_canonical_digest_of_the_rest_of_the_policy() -> None:
    manifest = load_canonical_manifest(with_policy())
    policy = json.loads(manifest.canonical_bytes)["commercial"]["paid_pilot_policy"]
    assert policy["policy_digest"] == V1_POLICY_DIGEST == digest_of(policy)

    # Key order is not significant; ordered lists are, and change the digest.
    reversed_keys = dict(reversed(list(with_policy()["commercial"]["paid_pilot_policy"].items())))
    reread = load_canonical_manifest(with_policy(policy=reversed_keys, seal=False))
    assert reread.canonical_bytes == manifest.canonical_bytes
    swapped = changed(lambda p: p["eligible_offers"].reverse())
    assert digest_of(swapped) != V1_POLICY_DIGEST
    stale = {**swapped, "policy_digest": V1_POLICY_DIGEST}
    assert refusal(with_policy(policy=stale, seal=False)).path == f"{POLICY}.policy_digest"


def without(key: str) -> Callable[[dict[str, Any]], None]:
    return lambda policy: policy.pop(key)


def setting(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda policy: policy.update({key: value})


REFUSALS: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    *[
        (f"missing {key}", without(key), key)
        for key in fictional_policy(candidate()["product_instance_id"])
    ],
    ("unknown key", setting("pilot_floor", 1), "pilot_floor"),
    ("wrong schema tag", setting("schema_version", "PaidPilotPolicy@2"), "schema_version"),
    ("unhyphenated product", setting("product_id", "0" * 32), "product_id"),
    ("empty criteria", setting("qualification_criteria", []), "qualification_criteria"),
    ("empty offers", setting("eligible_offers", []), "eligible_offers"),
    (
        "partial criterion",
        lambda p: p["qualification_criteria"][0].pop("version"),
        "qualification_criteria[0].version",
    ),
    (
        "extra criterion key",
        lambda p: p["qualification_criteria"][1].update(weight="1"),
        "qualification_criteria[1].weight",
    ),
    (
        "repeated criterion",
        lambda p: p["qualification_criteria"].append({**p["qualification_criteria"][0]}),
        "qualification_criteria[2]",
    ),
    (
        "uppercase criterion digest",
        lambda p: p["qualification_criteria"][0].update(digest="B" * 64),
        "qualification_criteria[0].digest",
    ),
    (
        "partial offer",
        lambda p: p["eligible_offers"][0].pop("offer_id"),
        "eligible_offers[0].offer_id",
    ),
    (
        "repeated sku",
        lambda p: p["eligible_offers"].append({**p["eligible_offers"][0], "offer_id": "other"}),
        "eligible_offers[2]",
    ),
    (
        "whitespace in sku",
        lambda p: p["eligible_offers"][0].update(sku="fixture sku"),
        "eligible_offers[0].sku",
    ),
    (
        "overlong sku",
        lambda p: p["eligible_offers"][0].update(sku="s" * 121),
        "eligible_offers[0].sku",
    ),
    (
        "overlong criterion ref",
        lambda p: p["qualification_criteria"][0].update(ref="r" * 201),
        "qualification_criteria[0].ref",
    ),
    ("lowercase currency", setting("currency", "usd"), "currency"),
    ("zero minimum", setting("minimum_net_collected_minor", 0), "minimum_net_collected_minor"),
    ("negative minimum", setting("minimum_net_collected_minor", -1), "minimum_net_collected_minor"),
    (
        "boolean minimum",
        setting("minimum_net_collected_minor", True),
        "minimum_net_collected_minor",
    ),
    ("string minimum", setting("minimum_net_collected_minor", "1"), "minimum_net_collected_minor"),
    ("wrong distinct_by", setting("distinct_by", "lead"), "distinct_by"),
    ("wildcard distinct_by", setting("distinct_by", "*"), "distinct_by"),
    ("unknown refund rule", setting("partial_refund_rule", "ignore"), "partial_refund_rule"),
    (
        "zero maximum age",
        setting("reconciliation_max_age_seconds", 0),
        "reconciliation_max_age_seconds",
    ),
    (
        "offset coverage start",
        setting("coverage_start", "2026-01-01T00:00:00+00:00"),
        "coverage_start",
    ),
]


@pytest.mark.parametrize(("label", "edit", "path"), REFUSALS, ids=[row[0] for row in REFUSALS])
def test_an_incomplete_or_widened_policy_is_refused_at_its_path(
    label: str, edit: Callable[[dict[str, Any]], None], path: str
) -> None:
    error = refusal(with_policy(policy=changed(edit)))
    assert (error.path, error.reason_code) == (f"{POLICY}.{path}", "manifest_schema_invalid")


@pytest.mark.parametrize("value", [None, {}, [], "PaidPilotPolicy@1"])
def test_null_or_empty_is_not_a_way_to_say_absent(value: Any) -> None:
    payload = candidate()
    payload["commercial"]["paid_pilot_policy"] = value
    assert refusal(payload).path.startswith(POLICY)


def test_a_missing_uppercase_or_mismatched_policy_digest_is_refused() -> None:
    unsealed = fictional_policy(candidate()["product_instance_id"])
    assert refusal(with_policy(policy=unsealed, seal=False)).path == f"{POLICY}.policy_digest"
    policy = sealed(unsealed)
    for digest in (policy["policy_digest"].upper(), "0" * 64):
        error = refusal(with_policy(policy={**policy, "policy_digest": digest}, seal=False))
        assert error.path == f"{POLICY}.policy_digest"


def test_the_pilot_floor_is_not_a_commercial_field() -> None:
    payload = candidate()
    payload["commercial"]["pilot_floor"] = 1
    assert refusal(payload).path == "manifest.commercial.pilot_floor"

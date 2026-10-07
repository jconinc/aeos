"""``paid_term_normalize_v1``, term registers and the eight-row paid class fence."""

from __future__ import annotations

import dataclasses
import itertools
import json
import traceback
from importlib import resources
from typing import Any

import pytest

from aeos_kernel.paid_terms import (
    NORMALIZATION_VERSION,
    REGISTER_SCHEMA_VERSION,
    PaidFenceFlags,
    PaidSurfaces,
    PaidTermError,
    RegisterBinding,
    TermClass,
    evaluate_paid_fence,
    load_term_register,
    normalize_text,
    url_forms,
    validate_registers,
)
from aeos_kernel.product_policy import (
    CanonicalProductManifest,
    decode_strict_json,
    load_canonical_manifest,
)
from aeos_kernel.product_policy_v2 import load_canonical_manifest_v2
from aeos_kernel.product_policy_v3 import load_canonical_manifest_v3
from aeos_kernel.product_policy_v4 import load_canonical_manifest_v4

BRAND = "Fictional Brandname"
CATEGORY = "respite planner"
OPERATOR = "Othercare Network"


def register_bytes(term_class: str, terms: list[str], **overrides: Any) -> bytes:
    body: dict[str, Any] = {
        "schema_version": REGISTER_SCHEMA_VERSION,
        "term_class": term_class,
        "normalization_version": NORMALIZATION_VERSION,
        "complete": True,
        "owner_decision_ref": "example://decision/terms",
        "artifact_version": "1",
        "terms": terms,
    }
    body.update(overrides)
    return json.dumps(body).encode()


def registers(
    brand: list[str] | None = None,
    category: list[str] | None = None,
    operator: list[str] | None = None,
) -> dict[TermClass, Any]:
    return {
        TermClass.OWN_BRAND: load_term_register(
            register_bytes("own_brand", [BRAND] if brand is None else brand)
        ),
        TermClass.CATEGORY: load_term_register(
            register_bytes("category", [CATEGORY] if category is None else category)
        ),
        TermClass.THIRD_PARTY_OPERATOR: load_term_register(
            register_bytes("third_party_operator", [OPERATOR] if operator is None else operator)
        ),
    }


def bind(held: dict[TermClass, Any]) -> dict[TermClass, RegisterBinding]:
    return {
        term_class: RegisterBinding(register.digest, register.artifact_version)
        for term_class, register in held.items()
    }


PREFIX = {
    TermClass.OWN_BRAND: "brand",
    TermClass.CATEGORY: "category",
    TermClass.THIRD_PARTY_OPERATOR: "operator",
}


def manifest(
    flags: tuple[bool, bool, bool],
    bindings: dict[TermClass, RegisterBinding],
    forbidden_phrases: list[str] | None = None,
) -> CanonicalProductManifest:
    """A fictional product policy whose paid fence names ``bindings``."""

    raw = resources.files("aeos_kernel.schemas").joinpath("product_policy")
    payload = decode_strict_json(raw.joinpath("canonical_manifest_v1.json").read_bytes())
    paid_fence = payload["authority"]["paid_fence"]
    paid_fence["allow_brand_terms"], paid_fence["allow_category_terms"] = flags[0], flags[1]
    paid_fence["allow_third_party_operator_terms"] = flags[2]
    for term_class, binding in bindings.items():
        paid_fence[f"{PREFIX[term_class]}_term_register_digest"] = binding.digest
        paid_fence[f"{PREFIX[term_class]}_term_register_version"] = binding.version
    if forbidden_phrases is not None:
        payload["tone_profile"]["forbidden_phrases"] = forbidden_phrases
    return load_canonical_manifest(payload)


def chain_text(error: BaseException) -> str:
    """The error and every exception chained to it, as a log would print them."""

    return "".join(traceback.format_exception(type(error), error, None))


def fence(flags: tuple[bool, bool, bool], surfaces: PaidSurfaces, **kwargs: Any) -> Any:
    held = kwargs.get("registers", registers())
    return evaluate_paid_fence(
        manifest=manifest(
            flags,
            kwargs.get("bindings", bind(registers())),
            kwargs.get("forbidden_phrases"),
        ),
        registers=held,
        surfaces=surfaces,
    )


def test_v2_manifest_uses_same_paid_fence_and_verifies_v2_bytes() -> None:
    raw = resources.files("aeos_kernel.schemas").joinpath("product_policy")
    payload = decode_strict_json(raw.joinpath("canonical_manifest_v2.json").read_bytes())
    held = registers()
    for term_class, binding in bind(held).items():
        paid_fence = payload["authority"]["paid_fence"]
        paid_fence[f"{PREFIX[term_class]}_term_register_digest"] = binding.digest
        paid_fence[f"{PREFIX[term_class]}_term_register_version"] = binding.version
    v2_policy = load_canonical_manifest_v2(payload)
    surfaces = PaidSurfaces(negative_keywords=(OPERATOR,))

    allowed = evaluate_paid_fence(manifest=v2_policy, registers=held, surfaces=surfaces)
    assert allowed.allowed
    assert allowed.manifest_digest == v2_policy.manifest_digest

    tampered = dataclasses.replace(v2_policy, manifest_digest="0" * 64)
    refused = evaluate_paid_fence(manifest=tampered, registers=held, surfaces=surfaces)
    assert not refused.allowed


def test_normalization_folds_width_case_punctuation_and_invisible_characters() -> None:
    assert (
        normalize_text("".join(chr(ord(c) + 0xFEE0) for c in "Fictional") + "  BRANDNAME!").words
        == "fictional brandname"
    )
    assert normalize_text("STRASSE").words == normalize_text("straße").words
    assert normalize_text("Fictional-Brand\u200bname").skeleton == "fictionalbrandname"
    assert normalize_text("re:spite\tplanner").words == "re spite planner"
    with pytest.raises(PaidTermError):
        normalize_text("bad \ud800")


def test_url_forms_decode_up_to_four_rounds_and_refuse_a_fifth() -> None:
    forms = url_forms("https://example.test/%252546ictional")
    assert "/Fictional" in forms
    with pytest.raises(PaidTermError) as caught:
        url_forms("https://example.test/%2525252546")
    assert caught.value.reason_code == "paid_term_normalization_unstable"
    with pytest.raises(PaidTermError):
        url_forms("https://example.test/%zz")
    assert "bücher.example" in url_forms("https://xn--bcher-kva.example/")
    assert "fictional.test" in url_forms("fictional.test/landing")


def test_register_loading_is_closed_and_digest_is_order_free() -> None:
    one = load_term_register(register_bytes("category", ["b", "a"]))
    two = load_term_register(register_bytes("category", ["a", "b"]))
    assert one.digest == two.digest and one.terms == ("a", "b")
    empty = load_term_register(register_bytes("own_brand", []))
    assert empty.terms == ()
    for raw in (
        register_bytes("category", ["a"], complete=False),
        register_bytes("category", ["a", "a"]),
        register_bytes("category", ["a"], normalization_version="v0"),
        register_bytes("mystery", ["a"]),
        register_bytes("category", [""]),
        b'{"schema_version":"x","schema_version":"y"}',
        json.dumps({"terms": []}).encode(),
    ):
        with pytest.raises(PaidTermError) as caught:
            load_term_register(raw)
        assert caught.value.reason_code == "paid_term_register_invalid"


@pytest.mark.parametrize(
    "held",
    [
        registers(brand=["Fictional"], category=["fictional"]),
        registers(category=["respite planner", "Respite-Planner"]),
        registers(operator=["fictional brandname"]),
        registers(category=["!!!"]),
        registers(category=["respiteplanner", "respite planner"]),
    ],
)
def test_colliding_register_forms_make_the_whole_fence_unavailable(
    held: dict[TermClass, Any],
) -> None:
    decision = fence(
        (True, True, True),
        PaidSurfaces(positive_keywords=["plain words"]),
        registers=held,
        bindings=bind(held),
    )
    assert not decision.allowed and decision.reason_code == "paid_term_register_invalid"


def test_an_approved_complete_empty_register_is_a_valid_class_with_no_terms() -> None:
    held = registers(brand=[], operator=[])
    decision = fence(
        (False, True, False),
        PaidSurfaces(positive_keywords=[BRAND, "plain words"]),
        registers=held,
        bindings=bind(held),
    )
    assert decision.allowed, decision.reason_code


def _forged(register: Any, **changes: Any) -> Any:
    return dataclasses.replace(register, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"canonical_bytes": b""},
        {"digest": "0" * 64},
        {"terms": ()},
        {"owner_decision_ref": ""},
        {"artifact_version": "2"},
    ],
)
def test_a_register_built_outside_its_signed_bytes_is_refused(changes: dict[str, Any]) -> None:
    held = registers()
    held[TermClass.OWN_BRAND] = _forged(held[TermClass.OWN_BRAND], **changes)
    decision = fence((False, True, True), PaidSurfaces(), registers=held, bindings=bind(held))
    assert decision.reason_code == "paid_term_register_invalid"


def test_a_register_the_product_policy_does_not_name_is_refused() -> None:
    other = registers(brand=["Another Brandname"])
    decision = fence((False, True, True), PaidSurfaces(), registers=other)
    assert decision.reason_code == "paid_term_register_invalid"
    newer = registers()
    newer[TermClass.CATEGORY] = load_term_register(
        register_bytes("category", [CATEGORY], artifact_version="2")
    )
    decision = fence((True, True, True), PaidSurfaces(), registers=newer)
    assert decision.reason_code == "paid_term_register_invalid"
    assert fence((True, True, True), PaidSurfaces(), registers=newer, bindings=bind(newer)).allowed
    held = registers()
    misversioned = bind(held)
    misversioned[TermClass.CATEGORY] = RegisterBinding(held[TermClass.CATEGORY].digest, "2")
    decision = fence((True, True, True), PaidSurfaces(), registers=held, bindings=misversioned)
    assert decision.reason_code == "paid_term_register_invalid"


def test_flags_read_a_canonical_manifest_paid_fence() -> None:
    held = registers()
    paid_fence: dict[str, Any] = {
        "allow_brand_terms": True,
        "allow_category_terms": False,
        "allow_third_party_operator_terms": False,
    }
    for term_class, prefix in (
        (TermClass.OWN_BRAND, "brand"),
        (TermClass.CATEGORY, "category"),
        (TermClass.THIRD_PARTY_OPERATOR, "operator"),
    ):
        paid_fence[f"{prefix}_term_register_ref"] = f"example://terms/{prefix}"
        paid_fence[f"{prefix}_term_register_digest"] = held[term_class].digest
        paid_fence[f"{prefix}_term_register_version"] = held[term_class].artifact_version
    flags = PaidFenceFlags.from_manifest(paid_fence)
    assert flags.bindings == bind(held)
    assert (flags.allow_brand_terms, flags.allow_category_terms) == (True, False)
    with pytest.raises(KeyError):
        PaidFenceFlags.from_manifest(
            {
                key: value
                for key, value in paid_fence.items()
                if key != "operator_term_register_digest"
            }
        )


def test_all_three_registers_are_required_in_their_own_slots() -> None:
    held = registers()
    with pytest.raises(PaidTermError):
        validate_registers({TermClass.OWN_BRAND: held[TermClass.OWN_BRAND]}, bind(held))
    swapped = dict(held)
    swapped[TermClass.CATEGORY] = held[TermClass.OWN_BRAND]
    swapped[TermClass.OWN_BRAND] = held[TermClass.CATEGORY]
    assert (
        fence((True, True, True), PaidSurfaces(), registers=swapped).reason_code
        == "paid_term_register_invalid"
    )


@pytest.mark.parametrize("flags", list(itertools.product((False, True), repeat=3)))
def test_the_eight_flag_rows(flags: tuple[bool, bool, bool]) -> None:
    negatives = [OPERATOR]
    for term, term_class, allowed in (
        (BRAND, "own_brand", flags[0]),
        (CATEGORY, "category", flags[1]),
        (OPERATOR, "third_party_operator", flags[2]),
    ):
        decision = fence(flags, PaidSurfaces(positive_keywords=[term], negative_keywords=negatives))
        if allowed:
            assert decision.allowed, (flags, term_class)
        else:
            assert decision.reason_code == "paid_term_class_disallowed"
            assert decision.term_class == term_class
    missing_exclusion = fence(flags, PaidSurfaces(positive_keywords=["plain words"]))
    assert missing_exclusion.allowed is flags[2]
    if not flags[2]:
        assert missing_exclusion.reason_code == "paid_third_party_exclusion_missing"


@pytest.mark.parametrize(
    ("surface", "value", "name"),
    [
        ("context", ["about fictional brandname"], "context"),
        ("copy", ["Try FICTIONAL-BRANDNAME today"], "copy"),
        ("display_urls", ["fictionalbrandname.test"], "display_urls"),
        (
            "destination_urls",
            ["https://landing.test/%2546ictional%2520Brandname"],
            "destination_urls",
        ),
        ("provider_payload", {"ad": {"headlines": ["Fictional Brandname"]}}, "provider_payload"),
        (
            "provider_payload",
            {"final_urls": ["https://landing.test/?q=fictional%2Bbrandname"]},
            "provider_payload",
        ),
    ],
)
def test_every_surface_is_inspected(surface: str, value: Any, name: str) -> None:
    decision = fence((False, True, True), PaidSurfaces(**{surface: value}))
    assert decision.reason_code == "paid_term_class_disallowed"
    assert decision.surface == name


def test_a_negative_keyword_is_not_positive_use() -> None:
    decision = fence(
        (False, False, False), PaidSurfaces(negative_keywords=[BRAND, CATEGORY, OPERATOR])
    )
    assert decision.allowed


def test_forbidden_phrases_refuse_under_every_row() -> None:
    decision = fence(
        (True, True, True),
        PaidSurfaces(copy=["A Guaranteed   CURE!"]),
        forbidden_phrases=["guaranteed cure"],
    )
    assert decision.reason_code == "paid_forbidden_phrase_present"


def test_the_decision_binds_the_exact_payload_and_carries_no_raw_text() -> None:
    first = fence((True, True, True), PaidSurfaces(provider_payload={"headline": "Plain help"}))
    second = fence((True, True, True), PaidSurfaces(provider_payload={"headline": "Plain help!"}))
    assert first.allowed and second.allowed
    assert first.provider_payload_digest != second.provider_payload_digest
    assert (
        first.normalized_input_digest
        == fence(
            (True, True, True), PaidSurfaces(provider_payload={"headline": "Plain help"})
        ).normalized_input_digest
    )
    refused = fence((False, True, True), PaidSurfaces(copy=["Fictional Brandname"]))
    assert "fictional" not in repr(refused).lower()


def test_an_unstable_url_refuses_before_any_match() -> None:
    decision = fence(
        (True, True, True), PaidSurfaces(destination_urls=["https://landing.test/%G1"])
    )
    assert decision.reason_code == "paid_term_normalization_unstable"


def test_a_prefixed_url_and_an_undecodable_punycode_name_are_inspected() -> None:
    decision = fence(
        (False, True, True),
        PaidSurfaces(provider_payload={"description": "URL:https://[fictional.test/x"}),
    )
    assert decision.reason_code == "paid_term_normalization_unstable"
    decision = fence(
        (True, True, True), PaidSurfaces(provider_payload={"description": "Visit xn--zz9 now"})
    )
    assert decision.reason_code == "paid_term_normalization_unstable"
    assert "zz9" not in repr(decision)
    assert fence(
        (True, True, True), PaidSurfaces(provider_payload={"description": "Visit bücher.example"})
    ).allowed


@pytest.mark.parametrize(
    "payload",
    [
        {"final_url": "landing.test/%46ictional%20Brandname"},
        {"final_url": "landing.test/%2546ictional%2520Brandname"},
        {"description": "Visit landing.test/%46ictional%2DBrandname today"},
        {"description": "Plain %46ictional%20Brandname help"},
    ],
)
def test_a_scheme_less_provider_string_is_decoded_like_a_url(payload: dict[str, str]) -> None:
    decision = fence((False, True, True), PaidSurfaces(provider_payload=payload))
    assert decision.reason_code == "paid_term_class_disallowed"
    assert decision.surface == "provider_payload"


def test_ordinary_percent_text_in_a_provider_string_is_not_malformed() -> None:
    decision = fence(
        (True, True, True),
        PaidSurfaces(provider_payload={"headline": "50% off planning help, 100%/month"}),
    )
    assert decision.allowed, decision.reason_code


def test_provider_text_still_encoded_after_four_rounds_is_refused() -> None:
    decision = fence(
        (True, True, True), PaidSurfaces(provider_payload={"headline": "Plain %2525252546 help"})
    )
    assert decision.reason_code == "paid_term_normalization_unstable"


def test_the_nfkc_step_never_uses_one_of_the_four_decoding_rounds() -> None:
    # Four percent-decoding rounds end in a full-width percent sign that NFKC maps to "%": text.
    four = "50%252525EF%252525BC%25252585 off planning help"
    decision = fence((True, True, True), PaidSurfaces(provider_payload={"headline": four}))
    assert decision.allowed, decision.reason_code
    five = "50%25252525EF%25252525BC%2525252585 off planning help"
    decision = fence((True, True, True), PaidSurfaces(provider_payload={"headline": five}))
    assert decision.reason_code == "paid_term_normalization_unstable"


@pytest.mark.parametrize("url", ["https://e℀.com/x", "https://[fictional.test/x"])
def test_an_unparseable_url_is_a_typed_refusal_that_never_quotes_it(url: str) -> None:
    with pytest.raises(PaidTermError) as caught:
        url_forms(url)
    assert caught.value.reason_code == "paid_term_normalization_unstable"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    rendered = chain_text(caught.value)
    assert "℀" not in rendered and "fictional" not in rendered
    decision = fence((True, True, True), PaidSurfaces(provider_payload={"final_url": url}))
    assert decision.reason_code == "paid_term_normalization_unstable"
    assert "fictional" not in repr(decision) and "℀" not in repr(decision)


def full_width(text: str) -> str:
    """The full-width compatibility form of printable ASCII, which NFKC maps back."""

    return "".join(chr(ord(char) + 0xFEE0) for char in text)


def test_a_scheme_less_punycode_host_is_read_as_its_unicode_name() -> None:
    held = registers(brand=["bücher"])
    for payload in (
        {"final_url": "xn--bcher-kva.example/landing"},
        {"description": "Visit xn--bcher-kva.example today"},
        {"description": "URL:https://xn--bcher-kva.example/x"},
        {"description": "ref=XN--BCHER-KVA.example"},
        {"description": "see/xn--bcher-kva.example"},
        {"cta": "Go|xn--bcher-kva"},
        {"description": "ref=" + full_width("xn--") + "bcher-kva.example"},
        {"description": "see/" + full_width("xn--") + "bcher-kva.example/x"},
        {"description": full_width("URL:https://xn--bcher-kva.") + "example/x"},
        {"description": "Visit " + full_width("XN--BCHER-KVA") + " today"},
        # A full-width percent sign is decoded after it normalizes, and an escape that decodes to
        # a full-width percent sign is normalized in the next round.
        {"description": "tag=" + full_width("xn--%") + "62cher-kva.example/x"},
        {"items": [{"ref=" + full_width("xn--%") + "62cher-kva.example/x": "plain"}]},
        {"description": "tag=xn--%EF%BC%85%36%32cher-kva.example"},
        # A full-width "xn--" still encoded three more times is read after its fourth round.
        {
            "description": "tag=%252525EF%252525BD%25252598%252525EF%252525BD%2525258E"
            "%252525EF%252525BC%2525258D%252525EF%252525BC%2525258Dbcher-kva.example"
        },
    ):
        decision = fence(
            (False, True, True),
            PaidSurfaces(provider_payload=payload),
            registers=held,
            bindings=bind(held),
        )
        assert decision.reason_code == "paid_term_class_disallowed", payload


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "Visit (https://xn--bcher-kva.example/x) today"},
        {"description": "Visit [xn--bcher-kva.example/x], today"},
        {"description": 'Visit "xn--bcher-kva.example." today'},
        {"description": "Visit https%3A%2F%2Fxn--bcher-kva.example/x today"},
        {"description": "Visit https%253A%252F%252Fxn--bcher-kva.example%252Fx today"},
        {"xn--bcher-kva.example/x": "plain value"},
        {"sitelinks": [{"https://xn--bcher-kva.example/x": 1}]},
    ],
)
def test_a_url_hidden_by_brackets_encoding_or_a_mapping_key_is_inspected(
    payload: dict[str, Any],
) -> None:
    held = registers(brand=["bücher"])
    decision = fence(
        (False, True, True),
        PaidSurfaces(provider_payload=payload),
        registers=held,
        bindings=bind(held),
    )
    assert decision.reason_code == "paid_term_class_disallowed", payload
    assert decision.surface == "provider_payload"


@pytest.mark.parametrize(
    "text",
    ["a\udcff", "https://landing.test/%C3%28", "https://e\u2100.com/x"],
)
def test_no_refusal_chains_an_exception_that_quotes_the_input(text: str) -> None:
    with pytest.raises(PaidTermError) as caught:
        url_forms(text) if text.startswith("https") else normalize_text(text)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(PaidTermError) as unreadable:
        load_term_register(b'{"terms": ["Fictional Brandname"], "terms": []}')
    assert unreadable.value.__cause__ is None and unreadable.value.__context__ is None
    assert "Fictional" not in chain_text(unreadable.value)


def test_a_caller_cannot_substitute_a_local_register_and_its_own_bindings() -> None:
    approved = registers()
    local = registers(brand=["Unapproved Local Term"])
    policy = manifest((True, True, True), bind(approved))
    decision = evaluate_paid_fence(manifest=policy, registers=local, surfaces=PaidSurfaces())
    assert decision.reason_code == "paid_term_register_invalid"
    assert evaluate_paid_fence(manifest=policy, registers=approved, surfaces=PaidSurfaces()).allowed


def test_a_manifest_that_disagrees_with_its_bytes_is_refused() -> None:
    approved = registers()
    honest = manifest((False, True, True), bind(approved))
    forged_payload = json.loads(honest.canonical_bytes)
    forged_payload["authority"]["paid_fence"]["allow_brand_terms"] = True
    forged = dataclasses.replace(honest, payload=load_canonical_manifest(forged_payload).payload)
    decision = evaluate_paid_fence(
        manifest=forged, registers=approved, surfaces=PaidSurfaces(copy=[BRAND])
    )
    assert decision.reason_code == "manifest_integrity_failed"
    refused = evaluate_paid_fence(
        manifest=honest, registers=approved, surfaces=PaidSurfaces(copy=[BRAND])
    )
    assert refused.reason_code == "paid_term_class_disallowed"
    assert refused.manifest_digest == honest.manifest_digest


@pytest.mark.parametrize("version", [3, 4, 5, 6, 7])
@pytest.mark.parametrize("profile", ["base", "correction_sweep"])
def test_versioned_paid_fence_checks_complete_manifest_bytes(version: int, profile: str) -> None:
    """C12/E3: shared paid fence must retain security/sweep/threshold version integrity."""
    raw = resources.files("aeos_kernel.schemas").joinpath("product_policy")
    suffix = "json" if version == 3 else "canonical"
    payload = decode_strict_json(
        raw.joinpath(f"canonical_manifest_v{version}_{profile}.{suffix}").read_bytes()
    )
    held = registers()
    for term_class, binding in bind(held).items():
        fence = payload["authority"]["paid_fence"]
        fence[f"{PREFIX[term_class]}_term_register_digest"] = binding.digest
        fence[f"{PREFIX[term_class]}_term_register_version"] = binding.version
    from aeos_kernel.product_policy_v5 import load_canonical_manifest_v5
    from aeos_kernel.product_policy_v6 import load_canonical_manifest_v6
    from aeos_kernel.product_policy_v7 import load_canonical_manifest_v7

    loader = {3: load_canonical_manifest_v3, 4: load_canonical_manifest_v4,
              5: load_canonical_manifest_v5, 6: load_canonical_manifest_v6,
              7: load_canonical_manifest_v7}[version]
    policy = loader(payload)
    surfaces = PaidSurfaces(negative_keywords=(OPERATOR,))
    result = evaluate_paid_fence(manifest=policy, registers=held, surfaces=surfaces)
    assert result.allowed and result.manifest_digest == policy.manifest_digest
    for tampered in (
        dataclasses.replace(policy, manifest_digest="0" * 64),
        dataclasses.replace(policy, canonical_bytes=policy.canonical_bytes + b" "),
        dataclasses.replace(policy, grant_set_digest="0" * 64),
    ):
        refused = evaluate_paid_fence(manifest=tampered, registers=held, surfaces=surfaces)
        assert not refused.allowed and refused.reason_code == "manifest_integrity_failed"

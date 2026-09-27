"""``paid_term_normalize_v1``, term registers and the eight-row paid class fence."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest

from aeos_kernel.paid_terms import (
    NORMALIZATION_VERSION,
    REGISTER_SCHEMA_VERSION,
    PaidFenceFlags,
    PaidSurfaces,
    PaidTermError,
    TermClass,
    evaluate_paid_fence,
    load_term_register,
    normalize_text,
    url_forms,
    validate_registers,
)

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


def fence(flags: tuple[bool, bool, bool], surfaces: PaidSurfaces, **kwargs: Any) -> Any:
    return evaluate_paid_fence(
        flags=PaidFenceFlags(*flags),
        registers=kwargs.get("registers", registers()),
        forbidden_phrases=kwargs.get("forbidden_phrases", ()),
        surfaces=surfaces,
    )


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
        registers(brand=[]),
        registers(operator=[]),
    ],
)
def test_colliding_or_empty_register_forms_make_the_whole_fence_unavailable(
    held: dict[TermClass, Any],
) -> None:
    decision = fence(
        (True, True, True), PaidSurfaces(positive_keywords=["plain words"]), registers=held
    )
    assert not decision.allowed and decision.reason_code == "paid_term_register_invalid"


def test_all_three_registers_are_required_in_their_own_slots() -> None:
    held = registers()
    with pytest.raises(PaidTermError):
        validate_registers({TermClass.OWN_BRAND: held[TermClass.OWN_BRAND]})
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

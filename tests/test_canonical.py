from __future__ import annotations

import math

import pytest

from aeos_kernel import canonical_json, stable_fingerprint


def test_stable_fingerprint_is_order_independent_and_full_sha256() -> None:
    left = stable_fingerprint({"b": 2, "a": [1, "tree"]})
    right = stable_fingerprint({"a": [1, "tree"], "b": 2})
    assert left == right
    assert len(left) == 64


@pytest.mark.parametrize("value", [{1: "not a string key"}, ("tuple",), math.nan, math.inf])
def test_canonical_json_refuses_values_that_do_not_round_trip_as_strict_json(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json(value)


def test_canonical_json_keeps_unicode_without_ascii_rewriting() -> None:
    assert canonical_json({"word": "Wema — breeze"}) == '{"word":"Wema — breeze"}'

"""Published fictional vectors freeze the v3 interchange contract."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aeos_kernel.product_policy import decode_strict_json
from aeos_kernel.product_policy_v3 import load_canonical_manifest_v3

SCHEMAS = files("aeos_kernel.schemas").joinpath("product_policy")


@pytest.mark.parametrize(
    ("profile", "stem"),
    [("base", "base"), ("correction_sweep", "correction_sweep")],
)
def test_v3_packaged_profile_vector_and_schema_are_parser_generated(
    profile: str, stem: str
) -> None:
    vectors = json.loads(SCHEMAS.joinpath(f"canonical_manifest_v3_{stem}.vectors.json").read_text())
    literal = SCHEMAS.joinpath(vectors["canonical_bytes"]).read_bytes()
    input_bytes = SCHEMAS.joinpath(vectors["input"]).read_bytes()
    schema = json.loads(SCHEMAS.joinpath(vectors["schema"]).read_text())
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(decode_strict_json(input_bytes))
    manifest = load_canonical_manifest_v3(input_bytes)

    assert vectors["schema_version"] == "aeos.product-manifest.v3"
    assert vectors["manifest_profile"] == profile
    assert vectors["provenance"] == (
        f"Fictional v3 {profile} profile; no product policy value, approval or activation."
    )
    assert input_bytes == literal == manifest.canonical_bytes
    assert hashlib.sha256(literal).hexdigest() == vectors["manifest_sha256"]
    assert manifest.manifest_digest == vectors["manifest_sha256"]
    assert manifest.grant_set_digest == vectors["grant_set_sha256"]

    invalid = decode_strict_json(input_bytes)
    invalid["unexpected"] = True
    with pytest.raises(ValidationError, match="Additional properties"):
        validator.validate(invalid)

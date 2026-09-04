from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from aeos_kernel import (
    CalibrationState,
    ContractError,
    EscalationRules,
    ExecutionProfile,
    FieldHookRegistry,
    FormatSpec,
    GenerationMode,
    Rubric,
    RubricStatus,
    ScoredExample,
    Subcriterion,
    build_scoring_prompt,
    parse_scores,
    sanitize,
    t3_check,
)
from aeos_kernel.scoring import SCORING_SYSTEM_PROMPT


def _rubric(status: RubricStatus = RubricStatus.CALIBRATING) -> Rubric:
    return Rubric(
        id="reply",
        status=status,
        target_kind="reply",
        target_field="body",
        subcriteria=(
            Subcriterion(id="prof", name="Professional", prompt="Is it calm?", blocking=True),
            Subcriterion(id="answer", name="Answers", prompt="Does it answer?", blocking=True),
            Subcriterion(id="kind", name="Warm", prompt="Is it warm?", evidence_required=True),
            Subcriterion(id="next", name="Next step", prompt="Is the next step clear?"),
            Subcriterion(id="short", name="Short", prompt="Is it short?"),
            Subcriterion(id="tone", name="Tone", prompt="Is the tone right?"),
        ),
        format_spec=FormatSpec(max_sentences=3, banned_phrases=("Rest assured",)),
    )


# ── rubric ────────────────────────────────────────────────────────────────────


def test_rubric_vocabulary_and_defaults_match_the_pipeline() -> None:
    assert [s.value for s in RubricStatus] == [
        "draft",
        "calibrating",
        "frozen",
        "degraded",
        "retired",
    ]
    assert ExecutionProfile.CALIBRATION.value == "calibration"
    assert GenerationMode.GROUP.value == "group"
    rules = EscalationRules()
    assert (rules.min_pass_rate, rules.spot_check_pct, rules.spot_check_min) == (0.67, 0.05, 10)
    assert rules.spot_check_max == 50
    assert rules.min_calibration_artifacts_per_family == 100
    assert (rules.pause_must_pass_disagreement, rules.pause_overall_disagreement) == (0.08, 0.15)


def test_rubric_contract_validation() -> None:
    with pytest.raises(ContractError):
        Subcriterion(id="", name="x", prompt="y")
    with pytest.raises(ContractError):
        EscalationRules(min_pass_rate=1.5)
    with pytest.raises(ContractError):
        Rubric(id="")
    with pytest.raises(ContractError):
        Rubric(
            id="dup",
            subcriteria=(
                Subcriterion(id="a", name="A", prompt="p"),
                Subcriterion(id="a", name="B", prompt="q"),
            ),
        )


def test_thresholds_for_status() -> None:
    rules = EscalationRules()
    assert rules.thresholds_for_status(RubricStatus.CALIBRATING)["spot_check_pct"] == 0.20
    assert rules.thresholds_for_status(RubricStatus.CALIBRATING)["spot_check_min"] == 30
    frozen = rules.thresholds_for_status(RubricStatus.FROZEN)
    assert (frozen["spot_check_pct"], frozen["spot_check_min"]) == (0.05, 10)
    assert frozen["pause_must_pass"] == 0.08
    degraded = rules.thresholds_for_status(RubricStatus.DEGRADED)
    assert (degraded["spot_check_pct"], degraded["pause_overall"]) == (1.0, 0.0)
    draft = rules.thresholds_for_status(RubricStatus.DRAFT)
    assert (draft["spot_check_min"], draft["pause_must_pass"]) == (20, 1.0)
    assert rules.thresholds_for_status(RubricStatus.RETIRED) == draft


def test_check_promotion_requires_volume_and_agreement() -> None:
    rules = EscalationRules()
    ready = CalibrationState(
        artifacts_evaluated=250,
        artifacts_by_kind={"refund": 120, "thanks": 130},
        t1_agreement_rate=0.91,
        t1_must_pass_agreement=0.96,
    )
    assert ready.check_promotion(rules)
    assert not CalibrationState(
        artifacts_by_kind={"refund": 99}, t1_agreement_rate=1.0, t1_must_pass_agreement=1.0
    ).check_promotion(rules)
    assert not CalibrationState(
        artifacts_by_kind={"refund": 100}, t1_agreement_rate=0.89, t1_must_pass_agreement=1.0
    ).check_promotion(rules)
    assert not CalibrationState(
        artifacts_by_kind={"refund": 100}, t1_agreement_rate=0.95, t1_must_pass_agreement=0.94
    ).check_promotion(rules)


def test_needs_t2_scoring_follows_status_and_host_switch() -> None:
    assert _rubric(RubricStatus.CALIBRATING).needs_t2_scoring()
    assert _rubric(RubricStatus.DRAFT).needs_t2_scoring()
    assert not _rubric(RubricStatus.FROZEN).needs_t2_scoring()
    assert not _rubric(RubricStatus.DEGRADED).needs_t2_scoring()
    assert not _rubric(RubricStatus.RETIRED).needs_t2_scoring()
    assert not _rubric(RubricStatus.CALIBRATING).needs_t2_scoring(enabled=False)
    sibling = Rubric(
        id="sib",
        status=RubricStatus.FROZEN,
        subcriteria=(
            Subcriterion(id="d", name="Distinct", prompt="Distinct from siblings?", blocking=True),
        ),
    )
    assert sibling.has_blocking_sibling_criteria
    assert sibling.needs_t2_scoring()


def test_rubric_prompt_rendering() -> None:
    rubric = _rubric()
    assert rubric.get_criterion("kind") is not None
    assert rubric.get_criterion("missing") is None
    rendered = rubric.subcriteria_to_prompt()
    assert "- prof: Professional [BLOCKING]" in rendered
    assert "- kind: Warm (cite evidence)" in rendered
    assert "  Evaluate: Is it calm?" in rendered
    assert rubric.examples_to_prompt() == "No examples provided."
    with_examples = Rubric(
        id="ex",
        examples=(
            ScoredExample(
                input_context={"class": "thanks"},
                output="Thanks for writing. Glad it helped.",
                scores={"prof": True},
                rationale="founder sent unchanged",
            ),
        ),
    )
    text = with_examples.examples_to_prompt()
    assert text.startswith("### GOOD example\n\nOutput: Thanks for writing.")
    assert "Rationale: founder sent unchanged" in text
    assert rubric.output_schema() == "A valid body value matching the format requirements above."
    schema = Rubric(id="s", format_spec=FormatSpec(json_schema={"type": "object"}))
    assert schema.output_schema() == '{\n  "type": "object"\n}'
    assert FormatSpec().to_prompt() == "No specific format requirements."
    full = FormatSpec(
        min_items=1,
        max_items=2,
        min_chars_per_item=3,
        max_chars_per_item=4,
        min_sentences=5,
        max_sentences=6,
        required_format="GIVEN/WHEN/THEN",
        banned_phrases=("a", "b"),
    ).to_prompt()
    assert full.splitlines() == [
        "- Minimum 1 items",
        "- Maximum 2 items",
        "- Each item >= 3 characters",
        "- Each item <= 4 characters",
        "- Minimum 5 sentences",
        "- Maximum 6 sentences",
        "- Format: GIVEN/WHEN/THEN",
        "- Banned phrases: a, b",
    ]


# ── text gate ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (12, "not a string"),
        ("a\x00b", "contains null bytes"),
        ("MATCH (n:Person) RETURN n", "dangerous: Cypher injection"),
        ("please DROP TABLE users", "dangerous: SQL injection"),
        ("<script>alert(1)</script>", "dangerous: XSS"),
        ("Render {{ user.name }} here", "code detected: '{{'"),
        ("SELECT name FROM people", "code detected: ['SELECT ', 'FROM ']"),
        ("run coord wlg sync now", "prompt leak: 'coord wlg'"),
        ("x" * 2001, "too long (2001 chars)"),
        ("日本語のテキストだけです", "too much non-Latin (0%)"),
    ],
)
def test_sanitize_rejections(text: object, error: str) -> None:
    assert sanitize(text) == (None, error)


def test_sanitize_normalizes_quotes_and_strips_controls() -> None:
    cleaned, error = sanitize("  We've sent it.\x07 \"Thanks\" `ok`  ")
    assert error is None
    assert cleaned == "We\u2019ve sent it. ”Thanks” \u2018ok\u2018"
    assert sanitize("Tab\tand\nnewline stay") == ("Tab\tand\nnewline stay", None)
    assert sanitize("one SELECT only") == ("one SELECT only", None)


def test_sanitize_preserves_ascii_quotes_inside_parseable_json() -> None:
    assert sanitize('["active", "canceled"]') == ('["active", "canceled"]', None)
    # Smart quotes inside a parseable JSON value collapse back to ASCII.
    assert sanitize('["it\u2019s fine"]') == ('["it\'s fine"]', None)
    # JSON-looking but not parseable: normalized like prose, smart quotes untouched.
    assert sanitize("[“active”, \u2018x\u2019]") == ("[“active”, \u2018x\u2019]", None)
    assert sanitize('{"a": }') == ("{”a”: }", None)


def test_t3_check_enforces_the_format_spec() -> None:
    spec = FormatSpec(
        min_items=1,
        max_items=2,
        min_chars_per_item=5,
        max_chars_per_item=60,
        min_sentences=1,
        max_sentences=2,
        required_format="GIVEN/WHEN/THEN",
        banned_phrases=("rest assured",),
    )
    ok = t3_check("GIVEN a form WHEN it is sent THEN a receipt shows.", spec)
    assert ok.passed and ok.errors == ()
    bad = t3_check(["tiny", "Rest assured this works. It does. Truly!", 7], spec)
    assert not bad.passed
    assert list(bad.errors) == [
        "item_count=3 > max=2",
        "item[0] length=4 < min=5",
        "item[0] missing format: GIVEN/WHEN/THEN",
        "item[1] banned phrase: 'rest assured'",
        "item[1] missing format: GIVEN/WHEN/THEN",
        "sentences=4 > max=2",
    ]
    assert t3_check([], spec).errors == ("item_count=0 < min=1", "sentences=0 < min=1")
    assert t3_check({"a": 1}, spec) == t3_check({"a": 1}, spec)
    assert t3_check(None, spec).errors == ("unexpected type: NoneType",)
    rejected = t3_check(["fine text here.", "<script>"], spec)
    assert rejected.errors == ("item[1] sanitize: dangerous: XSS",)
    assert t3_check("Any text.", FormatSpec(required_format="UNKNOWN")).passed
    short = t3_check("Only one sentence here", FormatSpec(min_sentences=2))
    assert short.errors == ("sentences=1 < min=2",)


# ── scoring ───────────────────────────────────────────────────────────────────


def test_build_scoring_prompt_uses_host_context_and_rubric() -> None:
    rubric = _rubric()
    prompt = build_scoring_prompt(
        "Hi there. Your refund is on its way.",
        {"Message class": "refund_request", "Field": "body"},
        rubric,
        sibling_outputs={"m1": "Thanks!", "m2": {"x": 1}},
    )
    assert SCORING_SYSTEM_PROMPT == "You are a quality reviewer. Return only valid JSON."
    assert "## Context\nMessage class: refund_request\nField: body\n" in prompt
    assert '## Output to evaluate\n"Hi there. Your refund is on its way."\n' in prompt
    assert "## Sibling Outputs (for distinctness evaluation)\n- m1: \"Thanks!\"" in prompt
    assert "- prof: Professional [BLOCKING]" in prompt
    assert prompt.rstrip().endswith('"confidence": "high" | "medium" | "low"\n}')
    assert "## Sibling" not in build_scoring_prompt("x", {}, rubric)


def _raw(**verdicts: str) -> dict[str, Any]:
    return {
        "scores": {key: {"verdict": value, "evidence": f"{key} evidence"} for key, value in
                   verdicts.items()},
        "composite_pass": True,
        "confidence": "high",
    }


def test_parse_scores_passes_when_blocking_pass_and_composite_reached() -> None:
    result = parse_scores(
        _raw(prof="PASS", answer="PASS", kind="PASS", next="PASS", short="PASS", tone="FAIL"),
        _rubric(),
        321,
    )
    assert result.passed and result.composite_pass  # 3 of 4 non-blocking = 0.75 >= 0.67
    assert result.blocking_failures == ()
    assert not result.has_abstain
    assert result.confidence == "high"
    assert result.tokens_used == 321
    assert result.scores["kind"].evidence == "kind evidence"
    assert result.raw_response is not None and result.raw_response["composite_pass"] is True


def test_parse_scores_fails_on_any_blocking_fail() -> None:
    result = parse_scores(
        _raw(prof="FAIL", answer="PASS", kind="PASS", next="PASS", short="PASS", tone="PASS"),
        _rubric(),
    )
    assert not result.passed
    assert result.composite_pass
    assert result.blocking_failures == ("prof",)


def test_parse_scores_fails_when_non_blocking_pass_rate_is_below_the_floor() -> None:
    result = parse_scores(
        _raw(prof="PASS", answer="PASS", kind="PASS", next="PASS", short="FAIL", tone="FAIL"),
        _rubric(),
    )
    assert not result.passed  # 2 of 4 = 0.5 < 0.67
    assert not result.composite_pass
    assert result.blocking_failures == ()
    # The floor is strict: two of three non-blocking passes (0.667) is below 0.67.
    three = Rubric(
        id="three",
        subcriteria=(
            Subcriterion(id="a", name="A", prompt="a"),
            Subcriterion(id="b", name="B", prompt="b"),
            Subcriterion(id="c", name="C", prompt="c"),
        ),
    )
    assert not parse_scores(_raw(a="PASS", b="PASS", c="FAIL"), three).composite_pass


def test_parse_scores_treats_missing_or_malformed_verdicts_as_abstain() -> None:
    result = parse_scores({"scores": {"prof": {"verdict": "maybe"}, "answer": "PASS"}}, _rubric())
    assert result.has_abstain
    assert result.scores["prof"].verdict == "ABSTAIN"
    assert result.scores["answer"].verdict == "ABSTAIN"
    assert result.scores["kind"].verdict == "ABSTAIN"
    assert result.confidence == "medium"
    assert not result.passed
    garbage = parse_scores({"scores": "nope"}, _rubric())
    assert garbage.has_abstain and not garbage.passed


def test_parse_scores_with_only_blocking_criteria_has_a_trivially_true_composite() -> None:
    rubric = Rubric(
        id="b",
        subcriteria=(Subcriterion(id="prof", name="P", prompt="p", blocking=True),),
    )
    assert parse_scores(_raw(prof="PASS"), rubric).passed
    assert parse_scores(_raw(prof="PASS"), rubric).composite_pass


# ── field hooks ───────────────────────────────────────────────────────────────


def _no_dash(value: Any, _context: Mapping[str, Any]) -> list[str] | None:
    return ["REPLY-VOICE-001"] if "—" in str(value) else None


def _needs_fact(value: Any, context: Mapping[str, Any]) -> list[str] | None:
    return None if str(context.get("amount", "")) in str(value) else ["facts"]


def _explodes(_value: Any, _context: Mapping[str, Any]) -> list[str] | None:
    raise RuntimeError("boom")


def test_field_hook_registry_runs_hooks_in_order_with_context() -> None:
    registry = FieldHookRegistry()
    registry.register("reply.body", _no_dash)
    registry.register("reply.body", _needs_fact)
    assert registry.fields() == ("reply.body",)
    assert registry.hooks_for("reply.body") == (_no_dash, _needs_fact)
    assert registry.hooks_for("other") == ()
    assert registry.run("other", "anything") == []
    assert registry.run("reply.body", "We refunded $29.", {"amount": "$29"}) == []
    assert registry.run("reply.body", "We refunded — $10.", {"amount": "$29"}) == [
        "REPLY-VOICE-001",
        "facts",
    ]


def test_field_hook_registry_fails_closed_on_a_raising_hook() -> None:
    registry = FieldHookRegistry()
    registry.register("reply.body", _explodes)
    assert registry.run("reply.body", "text") == ["hook _explodes raised RuntimeError: boom"]


def test_field_hook_registry_refuses_empty_field_and_duplicate_hook() -> None:
    registry = FieldHookRegistry()
    with pytest.raises(ContractError):
        registry.register("", _no_dash)
    registry.register("reply.body", _no_dash)
    with pytest.raises(ContractError):
        registry.register("reply.body", _no_dash)

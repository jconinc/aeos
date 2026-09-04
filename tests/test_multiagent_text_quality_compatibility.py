"""Known-answer parity for the text-quality modules lifted from the WLG pipeline.

Imports the pinned committed ``rubrics.py``, ``t3.py``, ``t2_scorer.py`` and
``validator_hooks.py`` and compares AEOS against them on the same inputs. The two
deliberate tightenings (an unrecognized scoring verdict abstains; a raising field hook is a
finding) are asserted as divergences, not hidden.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import pytest

from aeos_kernel import (
    CalibrationState,
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
from tests.test_multiagent_source_compatibility import require_pinned_source

pytestmark = pytest.mark.compatibility


def _pairs() -> tuple[Any, Any]:
    """Return (source rubric, AEOS rubric) built from the same definition."""
    from claude_coord.wlg.pipeline import rubrics as source

    criteria = (
        ("prof", "Professional", "Is it calm and respectful?", True, False),
        ("answer", "Answers the question", "Does it answer?", True, True),
        ("kind", "Warm", "Is any warmth specific to what they wrote?", False, False),
        ("next", "Next step", "Does the reader know what happens next?", False, False),
        ("short", "Short", "Is it short?", False, False),
    )
    spec = {
        "min_chars_per_item": 40,
        "max_chars_per_item": 2000,
        "max_sentences": 9,
        "banned_phrases": ["—", "Rest assured", "I hope this finds you well"],
    }
    example = {
        "input_context": {"class": "thanks"},
        "output": "Thanks for writing. Glad the page helped.",
        "scores": {"prof": True},
        "rationale": "founder sent unchanged",
        "label": "good",
    }
    source_rubric = source.Rubric(
        id="support_reply",
        version="1.0.0",
        status=source.RubricStatus.CALIBRATING,
        target_kind="support_reply",
        target_field="body",
        subcriteria=[
            source.Subcriterion(
                id=cid, name=name, prompt=prompt, blocking=blocking, evidence_required=evidence
            )
            for cid, name, prompt, blocking, evidence in criteria
        ],
        format_spec=source.FormatSpec(**spec),
        examples=[source.ScoredExample(**example)],
    )
    aeos_rubric = Rubric(
        id="support_reply",
        version="1.0.0",
        status=RubricStatus.CALIBRATING,
        target_kind="support_reply",
        target_field="body",
        subcriteria=tuple(
            Subcriterion(id=cid, name=name, prompt=prompt, blocking=blocking, evidence_required=ev)
            for cid, name, prompt, blocking, ev in criteria
        ),
        format_spec=FormatSpec(
            min_chars_per_item=40,
            max_chars_per_item=2000,
            max_sentences=9,
            banned_phrases=tuple(spec["banned_phrases"]),
        ),
        examples=(ScoredExample(**example),),
    )
    return source_rubric, aeos_rubric


def test_source_rubric_vocabulary_thresholds_and_rendering_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline import rubrics as source

    for aeos_enum, source_enum in (
        (RubricStatus, source.RubricStatus),
        (GenerationMode, source.GenerationMode),
        (ExecutionProfile, source.ExecutionProfile),
    ):
        assert [item.value for item in aeos_enum] == [item.value for item in source_enum]

    assert asdict(EscalationRules()) == asdict(source.EscalationRules())
    for status in RubricStatus:
        assert EscalationRules().thresholds_for_status(status) == (
            source.EscalationRules().thresholds_for_status(source.RubricStatus(status.value))
        )

    for by_kind, agreement, must_pass in (
        ({"a": 100, "b": 120}, 0.9, 0.95),
        ({"a": 99}, 1.0, 1.0),
        ({"a": 100}, 0.89, 1.0),
        ({"a": 100}, 1.0, 0.949),
        ({}, 0.9, 0.95),
    ):
        state = {
            "artifacts_by_kind": by_kind,
            "t1_agreement_rate": agreement,
            "t1_must_pass_agreement": must_pass,
        }
        assert CalibrationState(**state).check_promotion(EscalationRules()) == (
            source.CalibrationState(**state).check_promotion(source.EscalationRules())
        )

    source_rubric, aeos_rubric = _pairs()
    assert aeos_rubric.format_spec.to_prompt() == source_rubric.format_spec.to_prompt()
    assert aeos_rubric.subcriteria_to_prompt() == source_rubric.subcriteria_to_prompt()
    assert aeos_rubric.examples_to_prompt() == source_rubric.examples_to_prompt()
    assert aeos_rubric.output_schema() == source_rubric.output_schema()
    assert FormatSpec().to_prompt() == source.FormatSpec().to_prompt()
    # Upstream reads its global switch from the pipeline configuration; AEOS takes it as a
    # parameter. Compare under the switch value the pinned checkout actually resolves.
    from claude_coord.wlg.pipeline.pipeline_config import pcfg

    enabled = bool(pcfg("t2_scoring_enabled", True))
    for status in RubricStatus:
        source_rubric.status = source.RubricStatus(status.value)
        aeos_status = Rubric(id=aeos_rubric.id, status=status, subcriteria=aeos_rubric.subcriteria)
        assert aeos_status.needs_t2_scoring(enabled=enabled) == source_rubric.needs_t2_scoring()


_TEXTS: tuple[Any, ...] = (
    "Hi there. We\u2019ve refunded the $29 and you\u2019ll see it in 5 to 7 business days.",
    "  We've sent it.\x07 \"Thanks\" `ok`  ",
    '["active", "canceled"]',
    '["it\u2019s fine"]',
    "[“active”, \u2018x\u2019]",
    '{"a": }',
    "MATCH (n:Person) RETURN n",
    "please DROP TABLE users",
    "<script>alert(1)</script>",
    "Render {{ user.name }} here",
    "Evidence has shape {inputs:named,result:{pass:boolean}}.",
    "SELECT name FROM people",
    "one SELECT only",
    "run coord wlg sync now",
    "x" * 2001,
    "日本語のテキストだけです",
    "a\x00b",
    12,
    "Tab\tand\nnewline stay",
)


def test_source_sanitize_known_answers_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline.t3 import sanitize as source_sanitize

    for text in _TEXTS:
        assert sanitize(text) == source_sanitize(text), repr(text)


def test_source_t3_check_known_answers_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline import rubrics as source
    from claude_coord.wlg.pipeline.t3 import t3_check as source_t3_check

    source_rubric, aeos_rubric = _pairs()
    strict = {
        "min_items": 1,
        "max_items": 2,
        "min_chars_per_item": 5,
        "max_chars_per_item": 60,
        "min_sentences": 1,
        "max_sentences": 2,
        "required_format": "GIVEN/WHEN/THEN",
        "banned_phrases": ["rest assured"],
    }
    specs = (
        (aeos_rubric.format_spec, source_rubric.format_spec),
        (FormatSpec(), source.FormatSpec()),
        (
            FormatSpec(**{**strict, "banned_phrases": tuple(strict["banned_phrases"])}),
            source.FormatSpec(**strict),
        ),
    )
    outputs: tuple[Any, ...] = (
        "GIVEN a form WHEN it is sent THEN a receipt shows.",
        "Hi there. Rest assured we have sent it — today.",
        ["tiny", "Rest assured this works. It does. Truly!", 7],
        [],
        ["fine text here.", "<script>"],
        None,
        {"a": 1},
        "Only one sentence here",
        *_TEXTS,
    )
    for aeos_spec, source_spec in specs:
        for output in outputs:
            aeos_result = t3_check(output, aeos_spec)
            source_result = source_t3_check(output, source_spec)
            assert aeos_result.passed == source_result.passed, repr(output)
            assert list(aeos_result.errors) == list(source_result.errors), repr(output)


def _scoring_replies() -> tuple[Mapping[str, Any], ...]:
    def raw(**verdicts: str) -> dict[str, Any]:
        return {
            "scores": {k: {"verdict": v, "evidence": f"{k} evidence"} for k, v in verdicts.items()},
            "composite_pass": True,
            "confidence": "high",
        }

    return (
        raw(prof="PASS", answer="PASS", kind="PASS", next="PASS", short="PASS"),
        raw(prof="PASS", answer="PASS", kind="PASS", next="PASS", short="FAIL"),
        raw(prof="PASS", answer="PASS", kind="PASS", next="FAIL", short="FAIL"),
        raw(prof="FAIL", answer="PASS", kind="PASS", next="PASS", short="PASS"),
        raw(prof="ABSTAIN", answer="PASS", kind="PASS", next="PASS", short="PASS"),
        {"scores": {"prof": {"verdict": "PASS"}}, "confidence": "low"},
        {"scores": {}},
        {},
    )


def test_source_scoring_prompt_and_parse_known_answers_are_preserved() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline import t2_scorer as source

    source_rubric, aeos_rubric = _pairs()
    output = "Hi there. We\u2019ve refunded the $29."
    siblings = {"m1": "Thanks!", "m2": {"x": 1}}
    context = {
        "Shape kind": "support_reply",
        "Shape name": "refund_request",
        "Shape ID": "msg_1",
        "Field": "body",
        "Parent": "support",
    }
    source_prompt = source.T2_SCORING_PROMPT.format(
        kind="support_reply",
        name="refund_request",
        shape_id="msg_1",
        field="body",
        parent_id="support",
        output=__import__("json").dumps(output, indent=2),
        sibling_context=source._format_sibling_context(siblings),
        subcriteria=source_rubric.subcriteria_to_prompt(),
    )
    assert build_scoring_prompt(output, context, aeos_rubric, siblings) == source_prompt

    for raw in _scoring_replies():
        aeos_result = parse_scores(raw, aeos_rubric, 17)
        source_result = source._parse_scores(dict(raw), source_rubric, 17)
        assert aeos_result.passed == source_result.passed, raw
        assert aeos_result.composite_pass == source_result.composite_pass, raw
        assert list(aeos_result.blocking_failures) == source_result.blocking_failures, raw
        assert aeos_result.has_abstain == source_result.has_abstain, raw
        assert aeos_result.confidence == source_result.confidence, raw
        assert aeos_result.tokens_used == source_result.tokens_used
        assert {k: (v.verdict, v.evidence) for k, v in aeos_result.scores.items()} == {
            k: (v.verdict, v.evidence) for k, v in source_result.scores.items()
        }


def test_source_scoring_unknown_verdict_is_tightened_to_abstain() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline import t2_scorer as source

    source_rubric, aeos_rubric = _pairs()
    passes = {k: {"verdict": "PASS"} for k in ("answer", "kind", "next", "short")}
    raw = {"scores": {"prof": {"verdict": "maybe"}, **passes}}
    assert source._parse_scores(raw, source_rubric, 0).scores["prof"].verdict == "maybe"
    assert not source._parse_scores(raw, source_rubric, 0).has_abstain
    tightened = parse_scores(raw, aeos_rubric)
    assert tightened.scores["prof"].verdict == "ABSTAIN"
    assert tightened.has_abstain

    # A malformed entry raises upstream; AEOS records it as an abstention instead.
    malformed = {"scores": {"prof": "PASS", **passes}}
    with pytest.raises(AttributeError):
        source._parse_scores(malformed, source_rubric, 0)
    assert parse_scores(malformed, aeos_rubric).scores["prof"].verdict == "ABSTAIN"


def test_source_field_hook_contract_and_fail_closed_divergence() -> None:
    require_pinned_source()
    from claude_coord.wlg.pipeline import validator_hooks as source

    registry = FieldHookRegistry()
    for field_name, hooks in source.PRE_COMMIT_CHECKS.items():
        for hook in hooks:
            registry.register(field_name, hook)
    assert registry.fields() == tuple(source.PRE_COMMIT_CHECKS)

    samples = (
        ("definition", "This is a shape that handles things.", {"shape_kind": "Screen"}),
        ("definition", "Renders the medication list a caregiver prints.", {"shape_kind": "Screen"}),
        ("description", "Placeholder description to be filled in later.", {}),
        ("short_definition", "Medication list screen", {"shape_id": "screen.medication_list"}),
        ("acceptance_criteria", ["The system works as expected."], {}),
        ("unregistered", "anything", {}),
    )
    for field_name, value, context in samples:
        assert registry.run(field_name, value, context) == source.run_field_hooks(
            field_name, value, context
        ), (field_name, value)

    def explodes(_value: Any, _context: Mapping[str, Any]) -> list[str] | None:
        raise RuntimeError("boom")

    source.PRE_COMMIT_CHECKS.setdefault("aeos_probe", []).append(explodes)
    try:
        assert source.run_field_hooks("aeos_probe", "x") == []  # upstream swallows the error
    finally:
        source.PRE_COMMIT_CHECKS.pop("aeos_probe", None)
    strict = FieldHookRegistry()
    strict.register("aeos_probe", explodes)
    assert strict.run("aeos_probe", "x") == ["hook explodes raised RuntimeError: boom"]

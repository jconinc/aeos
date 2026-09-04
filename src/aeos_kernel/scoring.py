"""Rubric scoring: the reviewer prompt and the verdict parser, without a provider.

Extracted from MultiAgentCommunication ``claude_coord/wlg/pipeline/t2_scorer.py`` at
d99002a1903a56b5601d7ec3455e5dfa43028935. Upstream ``score_artifact`` binds the prompt to WLG
task packets and to one provider client; here the host renders the prompt with
``build_scoring_prompt``, makes the call through its own gateway, and hands the structured
reply to ``parse_scores``. The prompt body, the JSON reply contract and the pass rule (any
blocking FAIL fails; the non-blocking pass rate must reach ``min_pass_rate``; a missing or
malformed verdict is ABSTAIN) are preserved exactly. Upstream ``repair_artifact`` is retired
there (it fails closed unconditionally) and is not extracted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aeos_kernel.rubric import Rubric

SCORING_SYSTEM_PROMPT = "You are a quality reviewer. Return only valid JSON."

SCORING_PROMPT = """\
You are a quality reviewer. Score the following output against each criterion.
For each criterion, respond with PASS, FAIL, or ABSTAIN plus one sentence of evidence.

## Context
{context}

## Output to evaluate
{output}
{sibling_context}
## Criteria
{subcriteria}

Respond in this exact JSON format:
{{
  "scores": {{
    "<criterion_id>": {{
      "verdict": "PASS" | "FAIL" | "ABSTAIN",
      "evidence": "one sentence"
    }}
  }},
  "composite_pass": true | false,
  "confidence": "high" | "medium" | "low"
}}
"""

VERDICTS = frozenset({"PASS", "FAIL", "ABSTAIN"})


@dataclass(frozen=True, slots=True)
class CriterionScore:
    criterion_id: str
    verdict: str  # PASS | FAIL | ABSTAIN
    evidence: str = ""
    cited_input_field: str | None = None
    requirement_id: str | None = None
    parent_id: str | None = None
    sibling_id: str | None = None


@dataclass(frozen=True, slots=True)
class T2ScoreResult:
    passed: bool
    scores: dict[str, CriterionScore] = field(default_factory=dict)
    composite_pass: bool = False
    confidence: str = "medium"
    blocking_failures: tuple[str, ...] = ()
    has_abstain: bool = False
    tokens_used: int = 0
    raw_response: dict[str, Any] | None = None


def _format_sibling_context(sibling_outputs: Mapping[str, Any] | None) -> str:
    if not sibling_outputs:
        return ""
    lines = ["\n## Sibling Outputs (for distinctness evaluation)"]
    for sid, output in list(sibling_outputs.items())[:5]:
        lines.append(f"- {sid}: {json.dumps(output)[:200]}")
    return "\n".join(lines) + "\n"


def build_scoring_prompt(
    output: Any,
    context: Mapping[str, str],
    rubric: Rubric,
    sibling_outputs: Mapping[str, Any] | None = None,
) -> str:
    """Render the reviewer prompt. ``context`` lines are the host's labels and values."""
    context_block = "\n".join(f"{label}: {value}" for label, value in context.items())
    return SCORING_PROMPT.format(
        context=context_block,
        output=json.dumps(output, indent=2),
        sibling_context=_format_sibling_context(sibling_outputs),
        subcriteria=rubric.subcriteria_to_prompt(),
    )


def parse_scores(raw: Mapping[str, Any], rubric: Rubric, tokens_used: int = 0) -> T2ScoreResult:
    """Parse the reviewer's JSON reply into a result; unknown or missing verdicts abstain."""
    scores_raw = raw.get("scores", {})
    if not isinstance(scores_raw, Mapping):
        scores_raw = {}
    scores: dict[str, CriterionScore] = {}
    blocking_failures: list[str] = []
    has_abstain = False

    for sc in rubric.subcriteria:
        entry = scores_raw.get(sc.id, {})
        if not isinstance(entry, Mapping):
            entry = {}
        verdict = str(entry.get("verdict", "ABSTAIN"))
        if verdict not in VERDICTS:
            verdict = "ABSTAIN"
        scores[sc.id] = CriterionScore(
            criterion_id=sc.id,
            verdict=verdict,
            evidence=str(entry.get("evidence", "")),
            cited_input_field=entry.get("cited_input_field"),
            requirement_id=entry.get("requirement_id"),
            parent_id=entry.get("parent_id"),
            sibling_id=entry.get("sibling_id"),
        )
        if verdict == "FAIL" and sc.blocking:
            blocking_failures.append(sc.id)
        if verdict == "ABSTAIN":
            has_abstain = True

    non_blocking = [sc for sc in rubric.subcriteria if not sc.blocking]
    if non_blocking:
        pass_count = sum(1 for sc in non_blocking if scores[sc.id].verdict == "PASS")
        composite = pass_count / len(non_blocking) >= rubric.escalation_rules.min_pass_rate
    else:
        composite = True

    return T2ScoreResult(
        passed=not blocking_failures and composite,
        scores=scores,
        composite_pass=composite,
        confidence=str(raw.get("confidence", "medium")),
        blocking_failures=tuple(blocking_failures),
        has_abstain=has_abstain,
        tokens_used=tokens_used,
        raw_response=dict(raw),
    )

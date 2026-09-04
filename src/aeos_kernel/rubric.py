"""Rubric contracts for generated text: what "good output" looks like for one field.

Extracted from MultiAgentCommunication ``claude_coord/wlg/pipeline/rubrics.py`` at
d99002a1903a56b5601d7ec3455e5dfa43028935. The WLG pipeline authors a rubric once and lets
cheap models execute against it thousands of times; the status lifecycle, escalation
thresholds and promotion rule are preserved exactly. Adaptations: the dataclasses are frozen
and validated, sequences are tuples, and ``needs_t2_scoring`` takes its global enable flag as a
parameter instead of reading the WLG pipeline configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aeos_kernel.errors import ContractError


class RubricStatus(str, Enum):
    DRAFT = "draft"  # shadow mode: generate and score, discard the output
    CALIBRATING = "calibrating"  # output kept, elevated spot-check (20%)
    FROZEN = "frozen"  # trusted, spot-check at baseline (5%)
    DEGRADED = "degraded"  # auto-paused, every artifact routes to T1
    RETIRED = "retired"  # replaced by a newer version


class GenerationMode(str, Enum):
    ARTIFACT_LOCAL = "artifact_local"  # one subject, one prompt, one output
    GROUP = "group"  # all siblings under one parent, one prompt, N outputs


class ExecutionProfile(str, Enum):
    BACKFILL = "backfill"  # T0 → T3 → generate → ratchet → sample T1
    CALIBRATION = "calibration"  # T0 → T3 → generate → T2 score → repair → ratchet → T1
    JUDGMENT = "judgment"  # route to T1


@dataclass(frozen=True, slots=True)
class Subcriterion:
    id: str
    name: str
    prompt: str  # the exact evaluation prompt the scoring model sees
    pass_condition: str = "YES"
    evidence_required: bool = False
    weight: float = 1.0  # reserved for calibration-driven weighting
    blocking: bool = False  # a failure fails the artifact regardless of the composite

    def __post_init__(self) -> None:
        if not self.id or not self.name or not self.prompt:
            raise ContractError("subcriterion requires id, name and prompt")


@dataclass(frozen=True, slots=True)
class FormatSpec:
    """Deterministic checks that run before any model scoring."""

    min_items: int | None = None
    max_items: int | None = None
    min_chars_per_item: int | None = None
    max_chars_per_item: int | None = None
    min_sentences: int | None = None
    max_sentences: int | None = None
    required_format: str | None = None  # e.g. "GIVEN/WHEN/THEN"
    banned_phrases: tuple[str, ...] = ()
    json_schema: dict[str, Any] | None = None

    def to_prompt(self) -> str:
        """Render the format spec as prompt text for the generator."""
        parts: list[str] = []
        if self.min_items is not None:
            parts.append(f"Minimum {self.min_items} items")
        if self.max_items is not None:
            parts.append(f"Maximum {self.max_items} items")
        if self.min_chars_per_item is not None:
            parts.append(f"Each item >= {self.min_chars_per_item} characters")
        if self.max_chars_per_item is not None:
            parts.append(f"Each item <= {self.max_chars_per_item} characters")
        if self.min_sentences is not None:
            parts.append(f"Minimum {self.min_sentences} sentences")
        if self.max_sentences is not None:
            parts.append(f"Maximum {self.max_sentences} sentences")
        if self.required_format:
            parts.append(f"Format: {self.required_format}")
        if self.banned_phrases:
            parts.append(f"Banned phrases: {', '.join(self.banned_phrases)}")
        return "\n".join(f"- {p}" for p in parts) if parts else "No specific format requirements."


@dataclass(frozen=True, slots=True)
class ScoredExample:
    input_context: dict[str, Any]
    output: Any
    scores: dict[str, bool]  # subcriterion id → pass/fail
    rationale: str
    label: str = "good"  # "good" | "bad" | "borderline"


@dataclass(frozen=True, slots=True)
class EscalationRules:
    min_pass_rate: float = 0.67  # below this on non-blocking criteria → reject
    escalate_on_abstain: bool = True  # the scorer cannot decide → T1
    escalate_on_conflict: bool = True  # scores contradict format checks → T1
    spot_check_pct: float = 0.05  # baseline for frozen rubrics
    spot_check_min: int = 10
    spot_check_max: int = 50
    min_calibration_artifacts_per_family: int = 100
    pause_must_pass_disagreement: float = 0.08
    pause_overall_disagreement: float = 0.15

    def __post_init__(self) -> None:
        for name in ("min_pass_rate", "spot_check_pct"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ContractError(f"{name} must be between zero and one")

    def thresholds_for_status(self, status: RubricStatus) -> dict[str, float]:
        if status == RubricStatus.CALIBRATING:
            return {
                "spot_check_pct": 0.20,
                "spot_check_min": 30,
                "pause_must_pass": self.pause_must_pass_disagreement,
                "pause_overall": self.pause_overall_disagreement,
            }
        if status == RubricStatus.FROZEN:
            return {
                "spot_check_pct": self.spot_check_pct,
                "spot_check_min": self.spot_check_min,
                "pause_must_pass": self.pause_must_pass_disagreement,
                "pause_overall": self.pause_overall_disagreement,
            }
        if status == RubricStatus.DEGRADED:
            return {
                "spot_check_pct": 1.0,
                "spot_check_min": 0,
                "pause_must_pass": 0.0,
                "pause_overall": 0.0,
            }
        # DRAFT and RETIRED: shadow mode
        return {
            "spot_check_pct": 0.20,
            "spot_check_min": 20,
            "pause_must_pass": 1.0,
            "pause_overall": 1.0,
        }


@dataclass(frozen=True, slots=True)
class CalibrationState:
    artifacts_evaluated: int = 0
    artifacts_by_kind: dict[str, int] = field(default_factory=dict)
    t1_agreement_rate: float = 0.0
    t1_must_pass_agreement: float = 0.0
    promotion_ready: bool = False

    def check_promotion(self, rules: EscalationRules) -> bool:
        """May this rubric promote from calibrating to frozen?"""
        for count in self.artifacts_by_kind.values():
            if count < rules.min_calibration_artifacts_per_family:
                return False
        if self.t1_agreement_rate < 0.90:
            return False
        return self.t1_must_pass_agreement >= 0.95


@dataclass(frozen=True, slots=True)
class Rubric:
    id: str
    version: str = "1.0.0"
    status: RubricStatus = RubricStatus.DRAFT
    target_kind: str | tuple[str, ...] = ""
    target_field: str = ""
    subcriteria: tuple[Subcriterion, ...] = ()
    format_spec: FormatSpec = field(default_factory=FormatSpec)
    examples: tuple[ScoredExample, ...] = ()
    escalation_rules: EscalationRules = field(default_factory=EscalationRules)
    calibration: CalibrationState = field(default_factory=CalibrationState)
    generation_mode: GenerationMode = GenerationMode.ARTIFACT_LOCAL

    def __post_init__(self) -> None:
        if not self.id or not self.version:
            raise ContractError("rubric requires id and version")
        ids = [criterion.id for criterion in self.subcriteria]
        if len(set(ids)) != len(ids):
            raise ContractError("rubric subcriterion ids must be unique")

    @property
    def has_blocking_sibling_criteria(self) -> bool:
        """Whether any blocking criterion is about sibling distinctness."""
        return any(sc.blocking and "sibling" in sc.prompt.lower() for sc in self.subcriteria)

    def needs_t2_scoring(self, enabled: bool = True) -> bool:
        """Should model scoring run for this rubric?

        - calibrating: always
        - frozen with blocking sibling-distinct criteria: yes (not checkable deterministically)
        - frozen otherwise: no (the ratchet is sufficient)
        - draft: yes (shadow mode)
        - degraded or retired: no (routes to T1)

        ``enabled`` is the host's global switch (WLG: ``t2_scoring_enabled``).
        """
        if not enabled:
            return False
        if self.status == RubricStatus.CALIBRATING:
            return True
        if self.status == RubricStatus.FROZEN and self.has_blocking_sibling_criteria:
            return True
        return self.status == RubricStatus.DRAFT

    def get_criterion(self, criterion_id: str) -> Subcriterion | None:
        for sc in self.subcriteria:
            if sc.id == criterion_id:
                return sc
        return None

    def subcriteria_to_prompt(self) -> str:
        """Render the subcriteria as prompt text for scoring."""
        lines: list[str] = []
        for sc in self.subcriteria:
            blocking = " [BLOCKING]" if sc.blocking else ""
            evidence = " (cite evidence)" if sc.evidence_required else ""
            lines.append(f"- {sc.id}: {sc.name}{blocking}{evidence}")
            lines.append(f"  Evaluate: {sc.prompt}")
        return "\n".join(lines)

    def examples_to_prompt(self) -> str:
        """Render the scored examples as prompt text for the generator."""
        if not self.examples:
            return "No examples provided."
        parts: list[str] = []
        for ex in self.examples:
            parts.append(f"### {ex.label.upper()} example")
            parts.append(f"Output: {ex.output}")
            parts.append(f"Rationale: {ex.rationale}")
        return "\n\n".join(parts)

    def output_schema(self) -> str:
        """Describe the expected output format."""
        if self.format_spec.json_schema:
            return json.dumps(self.format_spec.json_schema, indent=2)
        return f"A valid {self.target_field} value matching the format requirements above."

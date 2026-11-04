"""Principle packs: expert rules as data, checked before any choice.

Extracted from WLG's standards packs (``decision_engine/standards.py``) and coverage check
(``decision_engine/coverage.py``). A principle can only remove options or name what is missing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate
from aeos_kernel.errors import ContractError, Refusal, RefusalCode
from aeos_kernel.evidence import (
    DecisionPacket,
    DecisionSubject,
    EvidenceItem,
    SourceRef,
    build_evidence_item,
)

PRINCIPLE_SET_KIND = "aeos.principle-set@1"
DECISION_FACTS_KIND = "aeos.decision-facts@1"
PRINCIPLE_SET_EVIDENCE_ID = "aeos-principle-set"
DECISION_FACTS_EVIDENCE_ID = "aeos-decision-facts"

_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_PATH = re.compile(r"^(context|candidate)\.[a-z0-9_]+$")
_COMPARE = frozenset({"eq", "ne", "in", "not_in", "lte", "gte"})
_SET_KEYS = frozenset(
    {"kind", "set_id", "version", "conflict_order", "decision_types", "principles"}
)
_PRINCIPLE_KEYS = frozenset(
    {
        "principle_id", "kind", "rank", "area", "applies_to",
        "statement", "source", "when", "requires",
    }
)
_FACTS_KEYS = frozenset({"kind", "decision_type", "context", "candidates"})


class PrincipleKind(StrEnum):
    GATE = "gate"
    PREFER = "prefer"
    JUDGE = "judge"


@dataclass(frozen=True, slots=True)
class Principle:
    principle_id: str
    kind: PrincipleKind
    rank: int
    area: str
    applies_to: tuple[str, ...]
    statement: str
    source: str
    when: Mapping[str, Any] | None
    requires: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class PrincipleSet:
    set_id: str
    version: str
    conflict_order: tuple[str, ...]
    decision_types: Mapping[str, tuple[str, ...]]
    principles: tuple[Principle, ...]


@dataclass(frozen=True, slots=True)
class PrincipleBrief:
    """A judge principle as the model sees it."""

    principle_id: str
    rank: int
    area: str
    statement: str
    source: str


@dataclass(frozen=True, slots=True)
class PrincipleResult:
    pool: tuple[Candidate, ...]
    ruled_out: Mapping[str, str]
    judge: tuple[PrincipleBrief, ...]
    conflict_order: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    all_principles: tuple[PrincipleBrief, ...] = ()
    rule_results: tuple[tuple[str, str], ...] = ()


class _MissingFact(Exception):
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def load_principle_set(raw: Mapping[str, Any]) -> PrincipleSet:
    """Validate a principle set; raise ContractError on any malformed part."""

    if not isinstance(raw, Mapping) or set(raw) != _SET_KEYS:
        raise ContractError("principle set keys are not exact")
    if raw["kind"] != PRINCIPLE_SET_KIND:
        raise ContractError("principle set kind is not supported")
    set_id = _identifier(raw["set_id"], "set_id")
    version = _text(raw["version"], "version")
    conflict_order = _unique(raw["conflict_order"], "conflict_order")
    types = raw["decision_types"]
    if not isinstance(types, Mapping) or not types:
        raise ContractError("decision_types must be a nonempty object")
    decision_types = {
        _identifier(name, "decision type"): _unique(areas, f"decision type {name!r} areas")
        for name, areas in types.items()
    }
    raw_principles = raw["principles"]
    if not isinstance(raw_principles, list) or not raw_principles:
        raise ContractError("principles must be a nonempty list")
    principles = tuple(
        _principle(item, len(conflict_order), decision_types) for item in raw_principles
    )
    ids = [principle.principle_id for principle in principles]
    if len(set(ids)) != len(ids):
        raise ContractError("principle ids must be unique")
    return PrincipleSet(set_id, version, conflict_order, decision_types, principles)


def principle_set_evidence(
    set_json: Mapping[str, Any], *, subject: DecisionSubject, observed_at: datetime
) -> EvidenceItem:
    """Carry a principle set into a packet as standard-tier evidence the model may cite."""

    loaded = load_principle_set(set_json)
    return build_evidence_item(
        evidence_id=PRINCIPLE_SET_EVIDENCE_ID,
        source_tier="standard",
        vertical_id=subject.vertical_id,
        tenant_id=subject.tenant_id,
        subject_id=subject.subject_id,
        subject_revision=subject.revision,
        payload=dict(set_json),
        source_ref=SourceRef(
            "aeos_principle_set", loaded.set_id, loaded.version, stable_fingerprint(set_json)
        ),
        observed_at=observed_at,
        allowed_uses=subject.allowed_uses,
    )


def decision_facts_evidence(
    *,
    decision_type: str,
    context: Mapping[str, Any],
    candidates: Mapping[str, Mapping[str, Any]],
    subject: DecisionSubject,
    observed_at: datetime,
) -> EvidenceItem:
    """Carry the facts that principles read: one context map and one map per option."""

    payload = {
        "kind": DECISION_FACTS_KIND,
        "decision_type": decision_type,
        "context": dict(context),
        "candidates": {key: dict(value) for key, value in candidates.items()},
    }
    return build_evidence_item(
        evidence_id=DECISION_FACTS_EVIDENCE_ID,
        source_tier="host_state",
        vertical_id=subject.vertical_id,
        tenant_id=subject.tenant_id,
        subject_id=subject.subject_id,
        subject_revision=subject.revision,
        payload=payload,
        source_ref=SourceRef(
            "aeos_decision_facts", decision_type, subject.revision, stable_fingerprint(payload)
        ),
        observed_at=observed_at,
        allowed_uses=subject.allowed_uses,
    )


def apply_principles(
    packet: DecisionPacket, eligible: tuple[Candidate, ...]
) -> PrincipleResult | Refusal:
    """Remove options that fail a gate or a preference; refuse when a rule or fact is missing."""

    sets = [item for item in packet.evidence if item.payload.get("kind") == PRINCIPLE_SET_KIND]
    facts = [item for item in packet.evidence if item.payload.get("kind") == DECISION_FACTS_KIND]
    if not sets and not facts:
        return PrincipleResult(eligible, {}, (), (), ())
    if len(sets) != 1 or len(facts) != 1:
        return Refusal(
            RefusalCode.INVALID_PACKET,
            "a principle set and its decision facts must appear together, once each",
        )
    try:
        return _apply(load_principle_set(sets[0].payload), sets[0], facts[0], eligible)
    except _MissingFact as gap:
        return Refusal(
            RefusalCode.MISSING_FACT,
            "a principle needs a fact the packet does not carry",
            gap.path,
        )
    except ContractError as error:
        return Refusal(RefusalCode.INVALID_PACKET, f"principles cannot be applied: {error}")


def _apply(
    principle_set: PrincipleSet,
    set_item: EvidenceItem,
    facts_item: EvidenceItem,
    eligible: tuple[Candidate, ...],
) -> PrincipleResult | Refusal:
    payload = facts_item.payload
    if set(payload) != _FACTS_KEYS:
        raise ContractError("decision facts keys are not exact")
    decision_type = _identifier(payload["decision_type"], "decision_type")
    context, by_candidate = payload["context"], payload["candidates"]
    if not isinstance(context, Mapping) or not isinstance(by_candidate, Mapping):
        raise ContractError("decision facts context and candidates must be objects")
    for candidate in eligible:
        if not isinstance(by_candidate.get(candidate.candidate_id), Mapping):
            raise ContractError(f"decision facts do not describe {candidate.candidate_id!r}")
    if decision_type not in principle_set.decision_types:
        return Refusal(
            RefusalCode.MISSING_PRINCIPLE,
            "no principle set covers this decision type",
            f"no principle set covers decision type {decision_type!r}",
        )
    ordered = sorted(principle_set.principles, key=lambda item: (item.rank, item.principle_id))
    in_force = [
        principle
        for principle in ordered
        if decision_type in principle.applies_to
        and (principle.when is None or _holds(principle.when, context, {}))
    ]
    uncovered = sorted(
        set(principle_set.decision_types[decision_type]) - {item.area for item in in_force}
    )
    if uncovered:
        return Refusal(
            RefusalCode.MISSING_PRINCIPLE,
            "no principle in force covers a required area",
            f"decision type {decision_type!r} has no principle in force for area(s): "
            + ", ".join(uncovered),
        )
    pool = list(eligible)
    ruled_out: dict[str, str] = {}
    unknown: list[str] = []
    rule_results: list[tuple[str, str]] = []
    for kind in (PrincipleKind.GATE, PrincipleKind.PREFER):
        for principle in (item for item in in_force if item.kind is kind):
            requires = principle.requires
            assert requires is not None  # gates and preferences always have one
            failures: dict[str, str] = {}
            for candidate in pool:
                facts = by_candidate[candidate.candidate_id]
                try:
                    if _holds(requires, context, facts):
                        continue
                    failures[candidate.candidate_id] = (
                        f"fails {principle.principle_id}"
                        if kind is PrincipleKind.GATE
                        else f"not preferred under {principle.principle_id}"
                    )
                except _MissingFact as gap:
                    if gap.path.startswith("context."):
                        raise
                    failures[candidate.candidate_id] = f"{principle.principle_id} needs {gap.path}"
                    unknown.append(f"{candidate.candidate_id}: {gap.path}")
            ignored = kind is PrincipleKind.PREFER and len(failures) == len(pool)
            for candidate in pool:
                result = failures.get(candidate.candidate_id, "passed")
                if ignored:
                    result = "preference did not narrow the pool: " + result
                rule_results.append((f"{principle.principle_id}:{candidate.candidate_id}", result))
            if ignored:
                continue
            ruled_out.update(failures)
            pool = [candidate for candidate in pool if candidate.candidate_id not in failures]
    if not pool:
        if unknown:
            return Refusal(
                RefusalCode.MISSING_FACT,
                "a principle needs a fact the packet does not carry",
                "; ".join(sorted(unknown)),
            )
        return Refusal(
            RefusalCode.NO_ELIGIBLE_CANDIDATE,
            "every option fails a principle: "
            + "; ".join(f"{key}: {value}" for key, value in sorted(ruled_out.items())),
        )
    judge = tuple(
        PrincipleBrief(item.principle_id, item.rank, item.area, item.statement, item.source)
        for item in in_force
        if item.kind is PrincipleKind.JUDGE
    )
    return PrincipleResult(
        tuple(pool),
        ruled_out,
        judge,
        principle_set.conflict_order,
        (set_item.evidence_id, facts_item.evidence_id),
        tuple(PrincipleBrief(p.principle_id, p.rank, p.area, p.statement, p.source)
              for p in in_force),
        tuple(rule_results),
    )


def _principle(
    raw: Any, ranks: int, decision_types: Mapping[str, tuple[str, ...]]
) -> Principle:
    if not isinstance(raw, Mapping) or set(raw) != _PRINCIPLE_KEYS:
        raise ContractError("principle keys are not exact")
    principle_id = _identifier(raw["principle_id"], "principle_id")
    where = f"principle {principle_id!r}"
    try:
        kind = PrincipleKind(raw["kind"])
    except (TypeError, ValueError) as error:
        raise ContractError(f"{where} kind must be gate, prefer or judge") from error
    rank = raw["rank"]
    if not isinstance(rank, int) or isinstance(rank, bool) or not 1 <= rank <= ranks:
        raise ContractError(f"{where} rank must be 1 to {ranks}")
    applies_to = _unique(raw["applies_to"], f"{where} applies_to")
    if not set(applies_to) <= set(decision_types):
        raise ContractError(f"{where} applies to an unknown decision type")
    when = None if raw["when"] is None else _expression(raw["when"], {"context"}, where)
    if kind is PrincipleKind.JUDGE:
        if raw["requires"] is not None:
            raise ContractError(f"{where} is a judge and cannot have requires")
        requires = None
    else:
        requires = _expression(raw["requires"], {"context", "candidate"}, where)
    return Principle(
        principle_id=principle_id,
        kind=kind,
        rank=rank,
        area=_identifier(raw["area"], f"{where} area"),
        applies_to=applies_to,
        statement=_text(raw["statement"], f"{where} statement"),
        source=_text(raw["source"], f"{where} source"),
        when=when,
        requires=requires,
    )


def _expression(raw: Any, scopes: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("op"), str):
        raise ContractError(f"{where} expression must be an object with an op")
    op = raw["op"]
    if op in {"all", "any", "not"}:
        parts = raw.get("of")
        if set(raw) != {"op", "of"} or not isinstance(parts, list) or not parts:
            raise ContractError(f"{where} {op} needs exactly op and a nonempty of list")
        if op == "not" and len(parts) != 1:
            raise ContractError(f"{where} not takes exactly one expression")
        for part in parts:
            _expression(part, scopes, where)
        return raw
    if op not in _COMPARE:
        raise ContractError(f"{where} op {op!r} is not supported")
    if set(raw) == {"fact", "op", "value"}:
        value = raw["value"]
        if op in {"in", "not_in"} and not isinstance(value, list):
            raise ContractError(f"{where} {op} needs a list value")
        if op in {"lte", "gte"} and not _number(value):
            raise ContractError(f"{where} {op} needs a number value")
    elif set(raw) == {"fact", "op", "fact2"}:
        _path(raw["fact2"], scopes, where)
    else:
        raise ContractError(f"{where} comparison keys must be fact, op and value or fact2")
    _path(raw["fact"], scopes, where)
    return raw


def _holds(
    expression: Mapping[str, Any], context: Mapping[str, Any], facts: Mapping[str, Any]
) -> bool:
    op = expression["op"]
    if op == "all":
        return all(_holds(part, context, facts) for part in expression["of"])
    if op == "any":
        return any(_holds(part, context, facts) for part in expression["of"])
    if op == "not":
        return not _holds(expression["of"][0], context, facts)
    left = _lookup(expression["fact"], context, facts)
    right = (
        expression["value"]
        if "value" in expression
        else _lookup(expression["fact2"], context, facts)
    )
    if op == "eq":
        return bool(left == right)
    if op == "ne":
        return bool(left != right)
    if op in {"in", "not_in"}:
        if not isinstance(right, list):
            raise ContractError(f"{expression['fact']} {op} needs a list")
        return bool((left in right) == (op == "in"))
    if not (_number(left) and _number(right)):
        raise ContractError(f"{expression['fact']} {op} needs numbers")
    return bool(left <= right) if op == "lte" else bool(left >= right)


def _lookup(path: str, context: Mapping[str, Any], facts: Mapping[str, Any]) -> Any:
    scope, key = path.split(".", 1)
    source = context if scope == "context" else facts
    if key not in source:
        raise _MissingFact(path)
    return source[key]


def _path(value: Any, scopes: set[str], where: str) -> None:
    if (
        not isinstance(value, str)
        or not _PATH.match(value)
        or value.split(".", 1)[0] not in scopes
    ):
        raise ContractError(f"{where} fact path {value!r} is not allowed here")


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ContractError(f"{name} must match {_ID.pattern}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be nonempty text")
    return value


def _unique(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{name} must be a nonempty list")
    items = tuple(_identifier(item, name) for item in value)
    if len(set(items)) != len(items):
        raise ContractError(f"{name} must be unique")
    return items

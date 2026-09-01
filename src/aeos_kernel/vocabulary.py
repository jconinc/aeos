"""Stable authority, lifecycle, intensity, response, and privacy vocabularies."""

from enum import IntEnum, StrEnum


class AuthorityLevel(StrEnum):
    DETERMINISTIC = "deterministic"
    STANDARD_DEFAULT = "standard_default"
    AGENT_JUDGMENT = "agent_judgment"
    HUMAN_REQUIRED = "human_required"


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    APPLYING = "applying"
    APPLIED = "applied"
    VERIFIED_CLOSED = "verified_closed"
    APPLY_FAILED = "apply_failed"
    VERIFIER_FAILED = "verifier_failed"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REFUSED = "refused"
    HUMAN_REQUIRED = "human_required"


class DecisionIntensity(IntEnum):
    ADVISORY = 0
    INTERNAL_EFFECT = 1
    OUTWARD_OR_IRREVERSIBLE = 2


class HumanResponse(StrEnum):
    USE_THIS = "use_this"
    CHANGE_IT = "change_it"
    NOT_NOW = "not_now"
    SNOOZE = "snooze"


class PrivacyClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"

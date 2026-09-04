"""Wema mailbox-triage interchange mappings.

One inbound business message, already classified by Wema's mailbox registry, becomes a
decision packet whose only evidence is closed values: the mailbox's registry policy, the
message's class and routing facts, and the matched order's state. No subject, body, sender,
name or address ever enters the packet — the projections refuse an ``@`` in any string — and
the model has no seat at this table (``permits_model_choice`` is the host's to set, and Wema
sets it false): the registry's recommended action is the single entailed candidate when its
facts hold, the fallback is entailed when they do not, and "open the mailbox" is always
available and never entailed. Sending a reply and refunding an order are outward effects the
host registers and a person attests; this adapter only names them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aeos_kernel.canonical import stable_fingerprint
from aeos_kernel.decision import Candidate, EffectTemplate, EntailmentProof, Recommendation
from aeos_kernel.evidence import (
    AuthorityPolicy,
    DecisionPacket,
    DecisionSubject,
    SourceRef,
    build_decision_packet,
    build_evidence_item,
)
from aeos_kernel.vocabulary import PrivacyClass

MAIL_ADAPTER_ID = "wema.mail_triage"
MAIL_ADAPTER_VERSION = "1"
MAIL_SOURCE_REF_TYPE = "mail_message"
MAIL_DECISION_KIND = "mail_reply"
SEND_REPLY_OPERATION = "wema.mail.send_reply"
REFUND_OPERATION = "wema.order.refund"
OUTBOUND_MAIL_TAG = "outbound_mail"
PAYMENT_TAG = "payment"

MAIL_ACTIONS = frozenset(
    {
        "refund_and_reply",
        "resend_access_and_reply",
        "reply_only",
        "open_privacy_request_and_reply",
        "open_mailbox",
    }
)
SENDING_ACTIONS = frozenset(MAIL_ACTIONS - {"open_mailbox"})
_OWNERS = frozenset({"founder", "john"})
_ORDER_STATUSES = frozenset({"paid", "fulfilled"})
_HEX = frozenset("0123456789abcdef")
#: The one `@` the packet may carry: a registry version label, never an address.
_VERSION_LABEL = re.compile(r"^[a-z][a-z0-9_]*@\d+$")


def _closed_text(value: str, label: str, limit: int) -> None:
    if not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must contain 1 to {limit} characters")
    if "@" in value or "\n" in value:
        raise ValueError(f"{label} may not carry an address or a line break")


def _digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise ValueError(f"{label} must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class WemaMailboxPolicy:
    """The registry's handling of one mailbox, as this run read it."""

    mailbox_id: str
    purpose: str
    owner: str
    response_promise_hours: int | None
    allowed_actions: tuple[str, ...]
    registry_version: str
    registry_digest: str

    def __post_init__(self) -> None:
        _closed_text(self.mailbox_id, "mailbox id", 32)
        _closed_text(self.purpose, "mailbox purpose", 32)
        if self.owner not in _OWNERS:
            raise ValueError("mailbox owner is not registered")
        if self.response_promise_hours is not None and self.response_promise_hours <= 0:
            raise ValueError("response promise must be positive hours or absent")
        if not self.allowed_actions or set(self.allowed_actions) - MAIL_ACTIONS:
            raise ValueError("mailbox allowed actions must be registered mail actions")
        if not _VERSION_LABEL.fullmatch(self.registry_version):
            raise ValueError("registry version must look like mailboxes@1")
        _digest(self.registry_digest, "registry digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "mailbox_id": self.mailbox_id,
            "purpose": self.purpose,
            "owner": self.owner,
            "response_promise_hours": self.response_promise_hours,
            "allowed_actions": list(self.allowed_actions),
            "registry_version": self.registry_version,
            "registry_digest": self.registry_digest,
        }


@dataclass(frozen=True, slots=True)
class WemaMailMessageProjection:
    """One indexed message: routing facts only, never the message."""

    message_id: str
    mailbox_id: str
    classification: str
    risk_flag: bool
    #: Who answers: the mailbox's owner unless the registry routes the class to John.
    owner: str
    recommended_action: str
    fallback_action: str | None
    requires: tuple[str, ...]
    requires_satisfied: tuple[str, ...]
    template_id: str | None
    safe_summary: str
    received_at: datetime
    deadline_at: datetime | None

    def __post_init__(self) -> None:
        _closed_text(self.message_id, "message id", 64)
        _closed_text(self.mailbox_id, "mailbox id", 32)
        _closed_text(self.classification, "classification", 32)
        if self.owner not in _OWNERS:
            raise ValueError("message owner is not registered")
        if self.recommended_action not in MAIL_ACTIONS:
            raise ValueError("recommended action is not a registered mail action")
        if self.fallback_action is not None and self.fallback_action not in MAIL_ACTIONS:
            raise ValueError("fallback action is not a registered mail action")
        if set(self.requires_satisfied) - set(self.requires):
            raise ValueError("a satisfied requirement must be one the action names")
        if self.template_id is not None:
            _closed_text(self.template_id, "template id", 48)
        _closed_text(self.safe_summary, "safe summary", 280)
        if self.deadline_at is not None and self.deadline_at < self.received_at:
            raise ValueError("a deadline cannot precede receipt")

    @property
    def facts_hold(self) -> bool:
        return set(self.requires) <= set(self.requires_satisfied)

    @property
    def entailed_action(self) -> str:
        """The action the registry entails: the recommendation when its facts hold, else the
        fallback, else reading the mailbox. A risky message is always read by a person."""
        if self.risk_flag:
            return "open_mailbox"
        if self.facts_hold:
            return self.recommended_action
        return self.fallback_action or "open_mailbox"

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "mailbox_id": self.mailbox_id,
            "classification": self.classification,
            "risk_flag": self.risk_flag,
            "owner": self.owner,
            "recommended_action": self.recommended_action,
            "fallback_action": self.fallback_action,
            "requires": list(self.requires),
            "requires_satisfied": list(self.requires_satisfied),
            "template_id": self.template_id,
            "safe_summary": self.safe_summary,
            "received_at": self.received_at.isoformat(),
            "deadline_at": None if self.deadline_at is None else self.deadline_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WemaOrderContext:
    """The matched order's state. No contact, no address, no provider payload."""

    order_id: str
    status: str
    amount_minor: int
    currency: str
    days_since_purchase: int
    refundable: bool

    def __post_init__(self) -> None:
        _closed_text(self.order_id, "order id", 64)
        if self.status not in _ORDER_STATUSES:
            raise ValueError("order status is not one a support reply can act on")
        if self.amount_minor < 0 or self.days_since_purchase < 0:
            raise ValueError("order amount and age must be nonnegative")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("order currency must be an ISO 4217 code")

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "status": self.status,
            "amount_minor": self.amount_minor,
            "currency": self.currency.upper(),
            "days_since_purchase": self.days_since_purchase,
            "refundable": self.refundable,
        }


def build_wema_mail_packet(
    *,
    tenant_id: str,
    mailbox: WemaMailboxPolicy,
    message: WemaMailMessageProjection,
    order: WemaOrderContext | None,
    authority_bundle_digest: str,
    source_head_pins: dict[str, str],
    policy: AuthorityPolicy,
    observed_at: datetime,
) -> DecisionPacket:
    """Build the triage packet. Its content digest is the routing facts, so a re-run over an
    unchanged row converges on the same decision and a changed registry is a new one."""

    if message.mailbox_id != mailbox.mailbox_id:
        raise ValueError("message and mailbox projections disagree about the mailbox")
    revision = stable_fingerprint(
        {
            "message": message.as_dict(),
            "mailbox": mailbox.as_dict(),
            "order": (None if order is None else order.as_dict()),
        }
    )
    source_ref = SourceRef(
        source_type="wema_mail_message",
        source_id=message.message_id,
        revision=revision,
        digest=revision,
    )
    subject = DecisionSubject(
        vertical_id="wema",
        tenant_id=tenant_id,
        subject_id=message.message_id,
        subject_kind="mail_message",
        revision=revision,
        content_digest=revision,
        attributes={
            "mailbox_id": mailbox.mailbox_id,
            "classification": message.classification,
            "risk_flag": message.risk_flag,
            "entailed_action": message.entailed_action,
        },
        source_refs=(source_ref,),
        privacy_classification=PrivacyClass.INTERNAL,
        allowed_uses=("decision",),
    )
    common = {
        "vertical_id": subject.vertical_id,
        "tenant_id": subject.tenant_id,
        "subject_id": subject.subject_id,
        "subject_revision": subject.revision,
        "source_ref": source_ref,
        "observed_at": observed_at,
        "privacy_classification": PrivacyClass.INTERNAL,
        "allowed_uses": ("decision",),
    }
    evidence = [
        build_evidence_item(
            evidence_id="mailbox_policy",
            source_tier="product_policy",
            payload=mailbox.as_dict(),
            **common,
        ),
        build_evidence_item(
            evidence_id="mail_message_projection",
            source_tier="host_state",
            payload=message.as_dict(),
            **common,
        ),
    ]
    if order is not None:
        evidence.append(
            build_evidence_item(
                evidence_id="order_context",
                source_tier="host_state",
                payload=order.as_dict(),
                **common,
            )
        )
    return build_decision_packet(
        packet_id="wema_mail_packet_" + stable_fingerprint({"subject": revision})[:24],
        subject=subject,
        evidence=tuple(evidence),
        authority_bundle_digest=authority_bundle_digest,
        policy=policy,
        allowed_actions=mailbox.allowed_actions,
        source_head_pins=source_head_pins,
        adapter_id=MAIL_ADAPTER_ID,
        adapter_version=MAIL_ADAPTER_VERSION,
        created_at=observed_at,
    )


def _send_effect(message: WemaMailMessageProjection) -> EffectTemplate:
    return EffectTemplate(
        operation=SEND_REPLY_OPERATION,
        operation_version="1",
        parameters={"message_id": message.message_id},
        boundary_tags=(OUTBOUND_MAIL_TAG,),
        expected_postcondition="one_reply_sent_to_original_sender",
        reversible=False,
        fanout_ceiling=1,
    )


def _refund_effect(order: WemaOrderContext) -> EffectTemplate:
    return EffectTemplate(
        operation=REFUND_OPERATION,
        operation_version="1",
        parameters={"order_id": order.order_id},
        boundary_tags=(OUTBOUND_MAIL_TAG, PAYMENT_TAG),
        expected_postcondition="order_refunded_in_full_and_reply_sent",
        reversible=False,
        cost_ceiling_minor_units=order.amount_minor,
        fanout_ceiling=1,
    )


_TITLES = {
    "refund_and_reply": "Refund the order and send the reply",
    "resend_access_and_reply": "Resend access and send the reply",
    "reply_only": "Send the reply",
    "open_privacy_request_and_reply": "Open a privacy request and send the reply",
    "open_mailbox": "Read it in the mailbox",
}


def _candidate(
    action: str,
    *,
    message: WemaMailMessageProjection,
    order: WemaOrderContext | None,
    entailed: bool,
) -> Candidate:
    if action == "refund_and_reply":
        if order is None or not order.refundable:
            raise ValueError("a refund candidate needs a refundable matched order")
        effect: EffectTemplate | None = _refund_effect(order)
        benefit = "The buyer gets the money back and a plain answer in one tap."
        reason = (
            "The registry recommends a refund for this class and the order is inside the window."
        )
    elif action in SENDING_ACTIONS:
        effect = _send_effect(message)
        benefit = "The person gets a plain answer from the mailbox they wrote to."
        reason = f"The registry recommends `{action}` for a `{message.classification}` message."
    else:
        effect = None
        benefit = "A person reads the message before anything is sent."
        reason = "The registry routes this message to a person, or its facts do not hold."
    cited = ("mailbox_policy", "mail_message_projection") + (
        ("order_context",) if order is not None and action == "refund_and_reply" else ()
    )
    return Candidate(
        candidate_id=f"mail-{action.replace('_', '-')}",
        action=action,
        title=_TITLES[action],
        explanation=reason,
        expected_benefit=benefit,
        uncertainty="" if entailed else "Not the registry's entailed choice for this message.",
        proof=EntailmentProof(
            source_tier="product_policy",
            cited_evidence_ids=cited,
            reason=reason,
            claimed_entailed=entailed,
        ),
        effect=effect,
    )


def mail_candidates(
    mailbox: WemaMailboxPolicy,
    message: WemaMailMessageProjection,
    order: WemaOrderContext | None,
) -> tuple[Candidate, ...]:
    """The closed choice set: the entailed action, the other registry action for the class,
    and reading the mailbox. Exactly one is entailed."""

    entailed = message.entailed_action
    if entailed == "refund_and_reply" and (order is None or not order.refundable):
        raise ValueError("the entailed refund has no refundable matched order")
    if entailed not in mailbox.allowed_actions:
        raise ValueError("the entailed action is outside the mailbox's allowed actions")
    actions: list[str] = [entailed]
    for other in (message.recommended_action, message.fallback_action, "open_mailbox"):
        if other is not None and other not in actions and other in mailbox.allowed_actions:
            actions.append(other)
    candidates: list[Candidate] = []
    for action in actions:
        if action == "refund_and_reply" and (order is None or not order.refundable):
            continue
        candidates.append(
            _candidate(action, message=message, order=order, entailed=action == entailed)
        )
    return tuple(candidates)


_BODIES = {
    "refund_and_reply": "Recommended: refund {amount} and send the reply below.",
    "resend_access_and_reply": "Recommended: resend the access link and send the reply below.",
    "reply_only": "Recommended: send the reply below.",
    "open_privacy_request_and_reply": (
        "Recommended: open a privacy request and send the reply below."
    ),
    "open_mailbox": "Recommended: read it in the mailbox; nothing is sent from here.",
}
_IMPACT = {
    "partner_interest": "reputation",
    "press": "reputation",
    "risky": "safety",
}
_MAILBOX_LABELS = {"support": "Support", "hello": "Hello", "privacy": "Privacy"}


def _money(amount_minor: int, currency: str) -> str:
    whole, cents = divmod(amount_minor, 100)
    text = f"{whole}" if cents == 0 else f"{whole}.{cents:02d}"
    return f"${text}" if currency.upper() == "USD" else f"{text} {currency.upper()}"


def to_mail_owned_action_values(
    recommendation: Recommendation,
    *,
    packet: DecisionPacket,
    candidate: Candidate,
    mailbox: WemaMailboxPolicy,
    message: WemaMailMessageProjection,
    order: WemaOrderContext | None,
    rank_class: str,
) -> dict[str, Any]:
    """Project the decision to Wema's existing queue: one card per message, closed words only."""

    label = _MAILBOX_LABELS.get(mailbox.mailbox_id, mailbox.mailbox_id.title())
    first_sentence = message.safe_summary.split(". ")[0].rstrip(".") + "."
    amount = "" if order is None else _money(order.amount_minor, order.currency)
    return {
        "module": "support",
        "title": f"{label}: {first_sentence}"[:200],
        "body": _BODIES[candidate.action].format(amount=amount),
        "evidence": {
            "message_id": message.message_id,
            "mailbox_id": mailbox.mailbox_id,
            "classification": message.classification,
            "risk_flag": message.risk_flag,
            "recommended_action": candidate.action,
            "template_id": message.template_id,
            "order_id": None if order is None else order.order_id,
            "registry_version": mailbox.registry_version,
            "registry_digest": mailbox.registry_digest,
            "aeos_decision_id": recommendation.decision_id,
            "aeos_decision_revision": recommendation.decision_revision,
            "recommendation_digest": recommendation.digest,
            "packet_digest": packet.packet_digest,
            "candidate_set_digest": recommendation.candidate_set_digest,
        },
        "effort": "5min",
        "impact_label": (
            "safety" if message.risk_flag else _IMPACT.get(message.classification, "customer")
        ),
        "rank_class": rank_class,
        "requires_founder_judgment": message.owner == "founder",
        "deadline_at": message.deadline_at,
        "source_ref_type": MAIL_SOURCE_REF_TYPE,
        "source_ref_id": message.message_id,
        "decision_kind": MAIL_DECISION_KIND,
    }

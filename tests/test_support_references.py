"""Native opaque IDs remain references; customer content remains inadmissible (§20.8)."""

from datetime import UTC, datetime, timedelta

import pytest

from aeos_kernel import (
    ContractError,
    DifficultyKind,
    DifficultyObservation,
    SummaryAuthority,
    assert_shareable,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
UUID_TEXT = "01a09fdc-cfd1-78d6-af47-970466994805"
NATIVE_REF = f"mail_message:{UUID_TEXT}"


def observation(
    reference: str, *, summary: str = "", authority: SummaryAuthority = SummaryAuthority.ABSENT
) -> DifficultyObservation:
    return DifficultyObservation(
        cluster_key="fictional-printing",
        product_slug="fictional-product",
        difficulty_kind=DifficultyKind.UNCLEAR_INSTRUCTION,
        surface="printing",
        occurrence_count=3,
        distinct_customer_count=None,
        window_started_at=NOW - timedelta(days=7),
        window_ended_at=NOW,
        support_refs=(reference,),
        operator_summary=summary,
        summary_authority=authority,
        source_digest="f" * 64,
    )


@pytest.mark.parametrize(
    "reference",
    [
        NATIVE_REF,
        "case:11111111-1111-1111-1111-111111111111",
        "record:abcdefab-abcd-abcd-abcd-abcdefabcdef",
        "n" * 64 + ":" + UUID_TEXT,
        "source_2:" + UUID_TEXT,
        "support-ref-1",
        "ticket_1",
        "case.a_2-3",
        "a" * 128,
    ],
)
def test_opaque_references_round_trip_without_normalization(reference: str) -> None:
    captured = observation(reference)
    assert captured.support_refs == (reference,)
    assert captured.as_dict()["support_refs"] == [reference]
    assert captured.as_dict()["source_digest"] == "f" * 64


@pytest.mark.parametrize(
    "reference",
    [
        "mail_message:" + UUID_TEXT.upper(),
        "Mail_message:" + UUID_TEXT,
        "1source:" + UUID_TEXT,
        "n" * 65 + ":" + UUID_TEXT,
        "a" * 129,
        "mail_message:" + UUID_TEXT.replace("01a09fdc", "01g09fdc"),
        "mail_message:" + UUID_TEXT.replace("-", ""),
        "mail_message:" + UUID_TEXT[:-1],
        "mail_message:" + UUID_TEXT + "0",
        "mail_message:",
        "mail_message:not-a-uuid",
        "mail_message:" + UUID_TEXT + ":other",
        "outer:" + NATIVE_REF,
        " " + NATIVE_REF,
        NATIVE_REF + "\n",
        "prefix " + NATIVE_REF,
        NATIVE_REF + " suffix",
        "{" + NATIVE_REF + "}",
        "mail_message%3A" + UUID_TEXT,
        "mail_message\uff1a" + UUID_TEXT,
        "customer words describing their private message",
        ".hidden-ref",
    ],
)
def test_malformed_or_embedded_references_refuse(reference: str) -> None:
    with pytest.raises(ContractError):
        observation(reference)


@pytest.mark.parametrize(
    "sensitive",
    [
        "someone@fictional.example",
        "+1 555 0100 999",
        "123456789",
        'they wrote "I clicked export and my whole afternoon of notes disappeared again"',
    ],
)
def test_sensitive_reference_and_summary_checks_remain_in_force(sensitive: str) -> None:
    with pytest.raises(ContractError):
        observation(sensitive)
    with pytest.raises(ContractError):
        observation(NATIVE_REF, summary=sensitive, authority=SummaryAuthority.AGENT_AUTHORED)
    with pytest.raises(ContractError):
        assert_shareable(sensitive, "operator_summary")


def test_uuid_exception_does_not_apply_to_summary_or_general_text() -> None:
    with pytest.raises(ContractError, match="long digit sequence"):
        assert_shareable(NATIVE_REF, "operator_summary")
    with pytest.raises(ContractError, match="long digit sequence"):
        observation(NATIVE_REF, summary=NATIVE_REF, authority=SummaryAuthority.AGENT_AUTHORED)

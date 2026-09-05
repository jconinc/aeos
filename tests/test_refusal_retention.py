"""AW-04 / §9: refusal preserves validated work without promoting it to a choice."""

from dataclasses import replace

import pytest

from aeos_kernel import DecisionEngine, DecisionStatus, ModelDecision, Recommendation, RefusalCode
from aeos_kernel.ports import ModelChoiceRequest
from tests.factories import AcceptingVerifier, FixedClock, ScriptedModel, candidate, packet, policy


def decide(model: ScriptedModel) -> Recommendation:
    return DecisionEngine(
        verifier=AcceptingVerifier(),
        clock=FixedClock(),
        model_gateway=model,
    ).decide(
        packet(authority_policy=policy(model=True)),
        (
            candidate("candidate-1", entailed=False),
            candidate("candidate-2", action="improve_description", entailed=False),
        ),
    )


def test_disagreement_retains_both_validated_outputs_without_a_selected_candidate() -> None:
    result = decide(ScriptedModel(["candidate-1", "candidate-2"]))
    assert result.status is DecisionStatus.REFUSED
    assert result.refusal is not None and result.refusal.code is RefusalCode.MODEL_DISAGREEMENT
    assert result.selected_candidate_id == ""
    assert [output["candidate_id"] for output in result.model_outputs] == [
        "candidate-1",
        "candidate-2",
    ]
    assert [call.attempt for call in result.model_calls] == [1, 2]


@pytest.mark.parametrize("invalid", ["candidate", "identity", "citations", "budget"])
def test_invalid_second_call_retains_first_but_never_the_unvalidated_output(invalid: str) -> None:
    class InvalidSecond(ScriptedModel):
        def choose(self, request: ModelChoiceRequest) -> ModelDecision:
            result = super().choose(request)
            if request.attempt == 1:
                return result
            result = replace(result, retained_output={"unsafe-fixture": "do not retain me"})
            if invalid == "candidate":
                return replace(result, candidate_id="invented")
            if invalid == "identity":
                return replace(result, identity=replace(result.identity, provider="untrusted"))
            if invalid == "citations":
                return replace(result, citations=("invented",))
            return replace(result, identity=replace(result.identity, cost_minor_units=100))

    result = decide(InvalidSecond(["candidate-1", "candidate-1"]))
    assert result.refusal is not None
    assert result.selected_candidate_id == ""
    assert [call.attempt for call in result.model_calls] == [1]
    assert len(result.model_outputs) == 1
    assert result.model_outputs[0]["candidate_id"] == "candidate-1"
    assert "unsafe-fixture" not in str(result.as_dict())


def test_invalid_first_call_is_not_retained_as_validated_work() -> None:
    result = decide(ScriptedModel(["invented"]))
    assert result.refusal is not None
    assert result.model_calls == result.model_outputs == ()

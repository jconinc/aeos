from aeos_kernel import DependencySnapshot, DriftReason, classify_drift


def snapshot(**changes: str) -> DependencySnapshot:
    values = {
        "subject_digest": "a",
        "evidence_digest": "b",
        "canon_digest": "c",
        "authority_digest": "d",
        "candidate_contract_digest": "e",
        "host_policy_digest": "f",
        "expected_postimage_digest": "g",
        "outcome_window_digest": "h",
    }
    values.update(changes)
    return DependencySnapshot(**values)


def test_irrelevant_external_change_does_not_create_drift() -> None:
    assert classify_drift(snapshot(), snapshot()) == ()


def test_each_material_dependency_has_a_typed_drift_reason() -> None:
    reasons = classify_drift(
        snapshot(),
        snapshot(subject_digest="changed", canon_digest="changed", host_policy_digest="changed"),
    )
    assert reasons == (
        DriftReason.SUBJECT_CHANGED,
        DriftReason.CANON_CHANGED,
        DriftReason.HOST_POLICY_CHANGED,
    )

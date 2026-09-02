from aeos_kernel import DependencySnapshot, DriftReason, classify_drift


def snapshot(**changes: str) -> DependencySnapshot:
    values = {
        "subject_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "canon_digest": "c" * 64,
        "authority_digest": "d" * 64,
        "candidate_contract_digest": "e" * 64,
        "host_policy_digest": "f" * 64,
        "expected_postimage_digest": "1" * 64,
        "outcome_window_digest": "2" * 64,
    }
    values.update(changes)
    return DependencySnapshot(**values)


def test_irrelevant_external_change_does_not_create_drift() -> None:
    assert classify_drift(snapshot(), snapshot()) == ()


def test_each_material_dependency_has_a_typed_drift_reason() -> None:
    reasons = classify_drift(
        snapshot(),
        snapshot(subject_digest="3" * 64, canon_digest="4" * 64, host_policy_digest="5" * 64),
    )
    assert reasons == (
        DriftReason.SUBJECT_CHANGED,
        DriftReason.CANON_CHANGED,
        DriftReason.HOST_POLICY_CHANGED,
    )

import aeos_kernel


def test_public_version_and_exports_are_stable() -> None:
    assert aeos_kernel.__version__ == "0.1.0"
    assert "DecisionEngine" in aeos_kernel.__all__
    assert "authorize_effect" in aeos_kernel.__all__

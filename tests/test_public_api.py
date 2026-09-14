import tomllib
from pathlib import Path
from typing import get_type_hints

import aeos_kernel
from aeos_kernel import ports
from aeos_kernel.engine import DecisionEngine
from aeos_kernel.verification import verify_packet


def test_public_version_and_exports_are_stable() -> None:
    # Package finding: the 0.8.0 wheel previously reported 0.7.2 at runtime.
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert aeos_kernel.__version__ == project["project"]["version"]
    assert "DecisionEngine" in aeos_kernel.__all__
    assert "GraphSnapshot" in aeos_kernel.__all__
    assert "authorize_effect" in aeos_kernel.__all__


def test_every_runtime_protocol_has_a_named_kernel_consumer() -> None:
    protocols = {
        name
        for name, value in vars(ports).items()
        if (
            isinstance(value, type)
            and value.__module__ == ports.__name__
            and getattr(value, "_is_protocol", False)
        )
    }
    assert protocols == {"Clock", "ModelGateway", "TrustVerifier"}

    engine_hints = get_type_hints(DecisionEngine)
    assert engine_hints["clock"] is ports.Clock
    assert "ModelGateway" in str(engine_hints["model_gateway"])
    assert engine_hints["verifier"] is ports.TrustVerifier
    assert get_type_hints(verify_packet)["verifier"] is ports.TrustVerifier

"""Published AEOS JSON Schema resources."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast


def schema_path(name: str, *, version: str = "v2") -> str:
    resource = files("aeos_kernel.schemas").joinpath(version, name)
    if not resource.is_file():
        raise FileNotFoundError(f"unknown AEOS schema {version}/{name}")
    return str(resource)


def load_schema(name: str, *, version: str = "v2") -> dict[str, Any]:
    resource = files("aeos_kernel.schemas").joinpath(version, name)
    return cast(dict[str, Any], json.loads(resource.read_text(encoding="utf-8")))

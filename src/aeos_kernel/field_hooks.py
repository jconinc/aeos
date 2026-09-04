"""Per-field pre-commit hooks: cheap checks a host registers beside the deterministic gate.

Extracted from MultiAgentCommunication ``claude_coord/wlg/pipeline/validator_hooks.py`` at
d99002a1903a56b5601d7ec3455e5dfa43028935. The hook contract is preserved: a hook receives the
already-sanitized value and a context mapping and returns ``None`` to pass or a list of
human-readable findings to fail, on the principle "if you pass pre-commit, you pass the
validator". Adaptations: the registry is instance-owned rather than a mutable module global,
and a hook that raises is a finding rather than a swallowed warning — a broken hook cannot
let a value through.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from aeos_kernel.errors import ContractError

FieldHook = Callable[[Any, Mapping[str, Any]], list[str] | None]


class FieldHookRegistry:
    """Hooks keyed by field name, run in registration order."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[FieldHook]] = {}

    def register(self, field_name: str, hook: FieldHook) -> None:
        if not field_name:
            raise ContractError("field hook requires a field name")
        hooks = self._hooks.setdefault(field_name, [])
        if hook in hooks:
            raise ContractError(f"hook {_hook_name(hook)} is already registered for {field_name}")
        hooks.append(hook)

    def fields(self) -> tuple[str, ...]:
        return tuple(self._hooks)

    def hooks_for(self, field_name: str) -> tuple[FieldHook, ...]:
        return tuple(self._hooks.get(field_name, ()))

    def run(
        self, field_name: str, value: Any, context: Mapping[str, Any] | None = None
    ) -> list[str]:
        """Run every hook registered for ``field_name``; return the flat list of findings."""
        findings: list[str] = []
        ctx: Mapping[str, Any] = context or {}
        for hook in self._hooks.get(field_name, ()):
            try:
                result = hook(value, ctx)
            except Exception as exc:  # a raising hook fails closed
                findings.append(f"hook {_hook_name(hook)} raised {type(exc).__name__}: {exc}")
                continue
            if result:
                findings.extend(result)
        return findings


def _hook_name(hook: FieldHook) -> str:
    return str(getattr(hook, "__name__", repr(hook)))

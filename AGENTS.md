# Repository Guidelines

AEOS is specification-first. Read `docs/aeos-specification.md` and
`docs/provenance-inventory.md` before changing behavior.

## Boundaries

- Keep `aeos_kernel` project-neutral. Product names, database models, HTTP routes,
  graph queries, and UI copy belong in adapters or consuming repositories.
- Extract proven behavior before inventing replacements. Record its source commit,
  source path, adaptation, and covering tests in the provenance inventory.
- Every abstraction must have a named production consumer.
- The kernel recommends and validates; only a host-owned effect executor may mutate
  product state.
- Models never grant themselves authority, expand candidate sets, or execute effects.
- Human, privacy, legal, clinical, spending, outreach, publication, deletion, and
  irreversible boundaries fail closed.
- Persist the useful output of expensive model calls together with its identity and
  receipt, not only a digest.

## Structure

- `src/aeos_kernel/` — stable kernel contracts and orchestration.
- `src/aeos_kernel/adapters/` — compatibility and vertical adapter contracts.
- `src/aeos_kernel/schemas/` — published versioned interchange schemas.
- `tests/` — deterministic, adversarial, compatibility, and vertical contract tests.
- `docs/` — specification, provenance, operations, and evidence.

Use Python 3.12, four-space indentation, complete type annotations, and a 100-character
line target. Use `pytest`, Ruff, and strict mypy. Do not add a network service until a
measured second production vertical requires one.

## Change discipline

Behavior changes update the specification, schema where applicable, provenance row,
and tests in the same change. Do not claim compatibility or end-to-end completion
without running the named evidence command against the pinned source revision.


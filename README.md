# AEOS

AEOS is a project-neutral operating decision engine. It turns versioned evidence,
declared authority, and bounded choices into explainable recommendations, human
decisions, authorized effects, and durable outcome receipts.

AEOS is being extracted from the proven decision machinery in
`/home/john/code/MultiAgentCommunication`. Wema is its first production vertical.
The engine does not replace Wema's Desk, model gateway, analytics, workers, or
domain operations; it connects them through strict contracts, adapters, and the three
runtime ports the decision engine actually consumes.

The governing documents are:

- [`docs/aeos-specification.md`](docs/aeos-specification.md) — normative product and
  technical specification.
- [`docs/provenance-inventory.md`](docs/provenance-inventory.md) — source-by-source
  extraction classification and evidence.
- [`docs/wema-integration.md`](docs/wema-integration.md) — the first vertical's exact
  API/worker/Desk/persistence contract.
- [`docs/multiagent-integration.md`](docs/multiagent-integration.md) — upstream
  compatibility and adoption contract.
- [`docs/operations.md`](docs/operations.md) — package, deployment, migration and rollback.

The first vertical slice is an article decision. Runtime activation remains host-controlled:

```text
Wema evidence -> AEOS recommendation -> Wema Today -> founder decision
     -> authorized Wema operation -> receipt/outcome -> later AEOS decision
```

The repository is intentionally independent. MultiAgentCommunication and Wema
remain source systems and integration consumers, not copied application shells.

The current package line is `0.2.x` with v2 interchange schemas. Historical v1 schema resources
remain readable, but hosts must explicitly map v1 records before using the stricter v2 authorizer;
there are no authority-broadening compatibility defaults.

## Development

Python 3.12 is required.

```bash
python3.12 -m pip install -e '.[dev]'
make verify
make wheel
```

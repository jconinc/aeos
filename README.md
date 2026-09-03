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

The first Wema slices are article revision advice, saved-review follow-up, and one daily growth
route decision. Runtime activation remains host-controlled:

```text
Wema evidence -> AEOS recommendation -> Wema Today -> founder decision
     -> authorized Wema operation -> receipt/outcome -> later AEOS decision
```

The repository is intentionally independent. MultiAgentCommunication and Wema
remain source systems and integration consumers, not copied application shells.

The current package line is `0.4.x` with v2 decision interchange schemas and the v1 immutable
graph-snapshot contract. Historical v1 decision resources remain readable, but hosts must
explicitly map old records before using the stricter v2 authorizer; there are no
authority-broadening compatibility defaults.

AEOS 0.4 uses that private graph foundation for relationships among safe content, questions,
audiences, routes, source states, playbooks and aggregate outcomes. Wema's daily-growth adapter
compares the complete governed route portfolio, retains alternatives, and proposes exactly one
effect-free operator preparation step. It is deliberately a derived read model: the host remains
authoritative and owns every effect. Runtime isolation is one Memgraph endpoint, data directory
and access identity per project, with Wema as the first project.

`infra/aws/` contains the generic one-project-per-stack AWS deployment, SSM bootstrap, private
listener/authentication verification, snapshot backup, and disposable restore rehearsal. It adds
no AEOS public service; consuming workers remain the only graph clients.

`infra/local/` is the active cost-minimizing profile: one loopback-only system service, operating
system user, credential, grow-as-used data directory and backup stream per project. Optional AI
assistance runs through operator-initiated local subscription sessions; the kernel and graph make
no paid model call. The AWS profile stays available for a later measured capacity or revenue
trigger, but is not required for Wema's first use.

## Development

Python 3.12 is required.

```bash
python3.12 -m pip install -e '.[dev]'
make verify
make wheel
```

The live Memgraph integration suite is opt-in and must target a disposable isolated instance:

```bash
AEOS_MEMGRAPH_TEST_PORT=7697 make integration
```

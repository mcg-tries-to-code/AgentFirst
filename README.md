# AgentFirst

AgentFirst is a governed, local-first prototype for multi-user agent operations.

It is exploring a simple thesis: agents should operate against a canonical local store with explicit policy, audit history, user boundaries, and operator-visible workflows, rather than as a pile of disconnected prompts and adapters.

## Current state

This repository is an **early prototype**, not a polished public product.

What exists now:
- canonical local data model and storage layer
- governed policy and audit/event recording
- bounded onboarding, doctor, command, and TUI/operator surfaces
- bounded user-management and inbox inspection flows
- validation scripts for the implemented slices

What does **not** yet exist as a public-ready promise:
- one-command consumer installation
- production-hardened live transport integrations
- broad hosted or remote administration
- complete cross-platform packaging
- final product positioning and release packaging

## Design posture

AgentFirst currently favors:
- **local-first operation**
- **deterministic state and auditability**
- **explicit enrollment and approval boundaries**
- **small, bounded operator surfaces**
- **honest validation claims instead of inflated production language**

This repo should presently be read as a serious working prototype and architecture proving ground.

## Repository structure

- `src/agentfirst_storage/` — implementation code
- `scripts/` — validation and support scripts
- `docs/` — architecture, slice notes, validation notes, and operator guidance
- `tests/` — test assets as they are added

## Running locally

This project is still evolving, but the current shape is standard Python packaging:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
agentfirst --help
```

Validation is currently driven primarily through targeted scripts in `scripts/` and companion notes in `docs/validation/`.

## Publishing note

The initial public snapshot intentionally excludes some local workflow orchestration artifacts and remains conservative about live credentialed integrations.

That is deliberate. The goal is to publish the product core without pretending the surrounding release machinery is further along than it is.

## License

This repository is currently published under the conservative license posture in `LICENSE`.
If you want an open-source release later, choose and replace it explicitly rather than drifting into accidental ambiguity.

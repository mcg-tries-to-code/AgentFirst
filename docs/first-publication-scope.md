# First Publication Scope

This note defines the intended posture for the first public GitHub snapshot of AgentFirst.

## Publish

Publish the following as part of the first snapshot:
- core implementation under `src/`
- validation/support scripts under `scripts/`
- architecture and validation docs that describe the prototype honestly
- project metadata such as `pyproject.toml`, `README.md`, and `LICENSE`

## Do not publish by default

Keep the following out of the first public snapshot unless deliberately reviewed and curated:
- local workflow orchestration artifacts under `toolflow/`
- any future environment-specific runbooks with host-specific assumptions
- any credentials, secret material, local paths, or operator-specific execution traces

## Public framing

The first public release should describe AgentFirst as:
- a governed local-first prototype
- a bounded multi-user agent operations system
- a repo with real implementation and real validation
- not yet a consumer-ready installer or production cloud product

## Explicit caveats worth keeping visible

The repo should continue to say plainly that:
- local/operator validation is stronger than live hosted-production validation
- transport integrations are still bounded and environment-dependent
- onboarding and packaging need additional work before broad public adoption

## Why this scope exists

The point of the first publish is to show the real product core without leaking local operator detail or pretending release polish already exists.

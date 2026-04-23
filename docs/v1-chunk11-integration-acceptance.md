# AgentFirst V1 Chunk 11 Integration Acceptance Sweep

## Scope

V1 Chunk 11 performs the final bounded integration sweep across the implemented V1 surfaces.

The sweep covers:
- multi-user identity and authority boundaries
- enrollment-first Telegram and BlueBubbles/iMessage channel handling
- per-user Google Workspace connection routing
- governed project work, artifacts, commitments, and project policy attachment
- scoped memory and retrieval with provenance
- governed tool invocation
- governed model/provider routing with fallback disclosure
- audit/event reconstruction
- trusted local TUI inspection and approval resolution

It intentionally does not add new product substrate, live OAuth setup, live Telegram or BlueBubbles delivery, remote dashboards, or a broader post-V1 roadmap.

## Integrated Acceptance Decision

Final V1 judgment:

**CONDITIONAL GO for bounded V1 local/operator acceptance. NO-GO for unqualified production launch.**

The implemented V1 surfaces work together under the bounded local validation model. Unknown inbound channel contact is contained, enrolled channel contact can create trusted work, cross-user Google access is denied until explicitly granted, project and memory boundaries are enforced, tool and model decisions are policy/audit-linked, failures are disclosed, and the trusted TUI can inspect state without mutation and resolve a pending approval with an admin audit trail.

This is not a full production green. The current V1 proof still relies on local/stubbed adapters and temporary SQLite validation state. It does not prove live Telegram send/receive operations, live BlueBubbles server operations, Google OAuth refresh behavior, real Gmail/Calendar/Contacts/Drive API calls, or live model-provider execution under real credentials.

A separate post-chunk secrets track now exists in the repo and proves a bounded local secret-broker path, but that track is not part of the Chunk 11 integrated acceptance script. Treat secrets custody as partially integrated hardening, not as something Chunk 11 already closed end to end across every external surface.

## Acceptance Decisions

| Surface | Decision | Evidence |
| --- | --- | --- |
| Unknown inbound containment | Accept | Unknown Telegram first contact creates discovery/enrollment records only and does not create trusted users, threads, messages, channel identities, or commitments. |
| Telegram trusted flow | Accept | Enrolled Telegram contact creates a trusted commitment through normal message routing. |
| BlueBubbles/iMessage trusted flow | Accept with bounded transport caveat | Enrolled direct 1:1 BlueBubbles contact creates a trusted commitment. Live BlueBubbles send execution remains out of scope. |
| Multi-user authority | Accept | Project outsider read and cross-user Google access are denied; explicit supervisory grant permits bounded cross-user calendar action. |
| Google Workspace | Accept with live-OAuth caveat | Per-user connection ownership and correct-account routing are enforced in local model; live Google OAuth/API behavior is not proven. |
| Project work management | Accept | Project participants, artifact linkage, project-owned commitment, and project policy attachment operate together. |
| Memory and retrieval | Accept | Unauthorized private memory retrieval is denied; authorized project retrieval returns provenance-bearing results. |
| Tooling baseline | Accept | Authorized project tool action completes; unauthorized project tool action records authority denial. |
| Model routing | Accept | Preferred provider fallback is selected and disclosed; route exhaustion records an honest failure. |
| Audit and observability | Accept | Integrated audit history includes channel enrollment, authority, Google, project, memory, tool, model, policy, and operator events. |
| Trusted TUI | Accept with bounded-admin caveat | Read-only TUI commands do not mutate audit/event state; approval resolution works as an explicit admin action. |

## Residual Risks and Blockers

Residual risks:
- Validation is local and deterministic. It uses temporary SQLite state and stubbed/prepared external-adapter behavior.
- Live external transport and credential lifecycle are not validated: Telegram Bot API, BlueBubbles server, Google OAuth/API calls, and model-provider calls need environment-specific acceptance.
- Secret-broker migration is only partially complete. Telegram has a brokered path, but Google and broader provider/channel credentials still need migration and live acceptance.
- The trusted TUI is intentionally bounded. Approval resolution is the only consequential admin action implemented in V1.
- Operator procedures still need a real user-side/manual pass against the target deployment state before calling this production-ready.

Blockers for unqualified production launch:
- No live end-to-end external-service acceptance has been run in this repo.
- No deployment-specific secrets, OAuth grants, channel webhooks, or long-running process supervision have been validated by Chunk 11.

## Design Outcome

The V1 implementation is coherent enough for a bounded local release-candidate acceptance pass. The right next step is a manual operator/user acceptance sweep using the user-side test guide, followed by environment-specific live integration checks.

Do not represent V1 as production-ready until those manual and live checks pass.

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk11_integration_acceptance.py
```

The validation creates one integrated temporary store and exercises all major V1 surfaces together.

Expected result:
- JSON output with `"ok": true`
- judgment of conditional go for bounded local/operator acceptance
- explicit residual risks
- true decisions for the integrated acceptance checks

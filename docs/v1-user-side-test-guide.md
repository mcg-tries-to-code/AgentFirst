# AgentFirst V1 User-Side Test Guide

## Purpose

This guide is the operator/user-side manual acceptance sweep for AgentFirst V1.

Use it after the automated validators pass. The guide is written from the perspective of a local operator validating the implemented V1 surfaces, not from a marketing or roadmap perspective.

## Starting Conditions

Before testing:
- initialize a fresh or clearly identified V1 test store
- know the primary administrator user
- have at least two standard users available
- have one test outsider user available
- have test Telegram and BlueBubbles/iMessage identities available if live channel testing is being attempted
- have Google test accounts available if live Google testing is being attempted
- have the trusted local TUI available through the CLI

Local TUI command:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli tui
```

Scripted local validation command:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk11_integration_acceptance.py
```

## Acceptance Legend

Use these outcomes for each test:
- Pass: behavior matches the expected result and audit evidence is present.
- Hold: behavior is correct locally but cannot be accepted because live external setup is absent.
- Fail: behavior violates authority, policy, enrollment, audit, or failure-disclosure expectations.

## 1. Identity and Authority

Test 1.1, primary and standard users:
- Create or identify the primary administrator.
- Create at least two standard users.
- Confirm the users are distinct records and no user is implicitly promoted to primary.

Expected:
- one primary user exists
- each standard user has isolated identity
- user creation is visible in event/audit history

Test 1.2, denied overreach:
- As User B, attempt to read or act on User A-owned private/project state without a grant.

Expected:
- access is denied
- denial is recorded as an authority decision

Test 1.3, explicit supervision:
- Have the primary user create a bounded supervisory grant for User B over User A.
- Retry a permitted action covered by the grant.

Expected:
- the granted action succeeds
- the decision cites the grant
- the grant creation and authority decision are auditable

## 2. Channel Enrollment and Binding

Test 2.1, unknown Telegram inbound:
- Send or simulate a Telegram message from an unknown contact.

Expected:
- the contact is discovered or placed into enrollment-required state
- no trusted canonical user, trusted channel identity, trusted private thread, trusted message, or commitment is created
- containment is auditable

Test 2.2, Telegram enrollment:
- Issue a Telegram enrollment challenge.
- Verify the challenge.
- Approve the enrollment as owner/primary.
- Send a trusted command such as a commitment request from the enrolled contact.

Expected:
- enrollment reaches enrolled state
- enrolled inbound message routes to the correct user context
- trusted work is created only after enrollment
- enrollment and message events are auditable

Test 2.3, Telegram suspension:
- Suspend an enrolled Telegram binding.
- Send another inbound message from that binding.

Expected:
- the binding is treated as not trusted
- inbound is contained or enrollment-required
- no new trusted work is created

Test 2.4, BlueBubbles/iMessage enrollment:
- Issue, verify, and approve a BlueBubbles/iMessage direct 1:1 enrollment.
- Send or simulate a direct 1:1 inbound message.

Expected:
- enrolled direct message routes to the correct user context
- trusted work can be created after enrollment
- unsupported or unenrolled inbound does not bypass enrollment

Live caveat:
- If no live BlueBubbles server is configured, mark live send/receive as Hold, not Pass.

## 3. Google Workspace

Test 3.1, per-user connections:
- Connect or model a Google Workspace account for User A.
- Connect or model a separate Google Workspace account for User B.

Expected:
- connection records are owned by the correct user
- account email, services, scopes, and credential refs are retained
- connection creation is auditable

Test 3.2, own-account action:
- As User A, perform a Gmail, Calendar, Contacts, or Drive action against User A's connection.

Expected:
- action uses User A's connection
- provenance records the connection owner and account email
- tool/policy/audit linkage is present

Test 3.3, blocked cross-user action:
- As User B, attempt to use User A's connection without authority.

Expected:
- action is denied
- denied action is recorded
- no wrong-account routing occurs

Test 3.4, granted cross-user action:
- Create an explicit supervisory grant.
- Retry an action covered by the grant.

Expected:
- action succeeds only within the grant boundary
- provenance still points to User A's connection
- authority decision cites the grant

Live caveat:
- If OAuth and live Google API calls are not configured, mark live API execution as Hold.

## 4. Projects and Work

Test 4.1, project creation:
- Create a user-owned project with at least one participant, one milestone, and one policy ref.

Expected:
- owner, participants, milestones, goals, and policies are retained
- project creation is auditable

Test 4.2, artifact linkage:
- Create an artifact.
- Link it to the project.

Expected:
- artifact includes the project ref
- provenance records the project linkage
- project artifact linkage is auditable

Test 4.3, project commitment:
- Create a project-owned commitment.

Expected:
- commitment owner scope is the project
- commitment includes project id
- project policy refs are inherited or attached

Test 4.4, project access boundary:
- Have a participant read the project work bundle.
- Have an outsider attempt the same read.

Expected:
- participant read succeeds
- outsider read is denied and audited

## 5. Memory and Retrieval

Test 5.1, private memory:
- Store a private user-scoped memory for User A.
- Have an unauthorized user attempt retrieval from User A's scope.

Expected:
- retrieval is denied
- denied scope is recorded
- no private result leaks

Test 5.2, project memory:
- Store a project-scoped memory.
- Have a project participant retrieve it with an explicit project scope.

Expected:
- retrieval returns only authorized scoped results
- result includes memory id, content ref, source refs, scope, canonicality, and provenance

## 6. Tools

Test 6.1, baseline inventory:
- Ensure V1 baseline tool capabilities are present.

Expected:
- local artifact/progress tools, research tool, channel send tools, and Google service tools are registered
- tool registration is auditable

Test 6.2, authorized consequential tool:
- As a project participant with intervention authority, invoke a project-scoped local artifact write.

Expected:
- invocation completes
- input/output refs and policy decision refs are recorded
- audit trail links the action to user, scope, and tool capability

Test 6.3, unauthorized tool:
- As an outsider, invoke the same project-scoped tool.

Expected:
- invocation does not execute
- status is authority denied
- denial appears in failure/operator review surfaces

## 7. Model Routing

Test 7.1, preferred route:
- Create a model preference for a user or agent.
- Route a normal request.

Expected:
- selected provider/model follows preference
- policy decision and model route decision are recorded

Test 7.2, fallback disclosure:
- Mark the preferred provider unavailable and route again.

Expected:
- fallback provider/model is selected if configured
- disclosure explicitly states fallback use and reason

Test 7.3, exhausted route:
- Mark preferred and fallback providers unavailable.

Expected:
- route decision records failed status
- failure is auditable and visible to operator review

## 8. Audit, Failures, and Trusted TUI

Test 8.1, read-only inspection:
- Run TUI commands for status, approvals, audit, users, tasks, and failures.

Expected:
- read-only commands report read-only mode
- audit/event counts do not change because of inspection
- blocked work and denied/failed actions are visible

Test 8.2, approval resolution:
- Create or identify a pending approval.
- Resolve it through the TUI admin approval command with the required actor and confirmation token.

Expected:
- approval status updates
- admin action reports admin mode
- operator approval resolution is recorded in audit and event history

Test 8.3, reconstruction:
- Starting from audit/event history, reconstruct a representative path:
  unknown contact containment, enrollment approval, trusted inbound, authority decision, policy decision, tool/model decision, and operator approval.

Expected:
- each consequential step has enough audit metadata to understand actor, object, decision, and outcome

## 9. Final Manual Judgment

Mark V1 as Pass for bounded local/operator acceptance only if:
- all local automated validators pass
- all manual local checks above pass
- every Hold is explicitly tied to missing live external setup rather than a code or model defect
- no authority, enrollment, exfiltration, or audit failure is observed

Mark V1 as No-Go for production launch if any of these remain true:
- live Telegram, BlueBubbles, Google OAuth/API, or model-provider paths have not been validated in the target environment
- unknown inbound contact can create trusted state
- cross-user access succeeds without explicit ownership, membership, or grant
- private/project memory leaks across scopes
- consequential tool or model actions lack policy/audit linkage
- failures are silent or absent from operator review
- TUI admin actions mutate state without confirmation and audit trail

Current Chunk 11 automated judgment:

**CONDITIONAL GO for bounded V1 local/operator acceptance. NO-GO for unqualified production launch.**

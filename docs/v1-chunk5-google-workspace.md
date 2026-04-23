# AgentFirst V1 Chunk 5 Google Workspace Per-User Model

## Scope

V1 Chunk 5 adds a bounded Google Workspace connection and action model for:
- Gmail
- Calendar
- Contacts
- Drive

The implementation intentionally does not add live OAuth UX or call Google APIs. It models the trust boundary that live credentials must obey: every Google action resolves through a specific active connection owned by a canonical user.

## Connection Model

Google account bindings live in `google_connections`.

Each connection records:
- `user_id`
- `google_account_email`
- enabled `services_json`
- granted or expected `scopes_json`
- legacy opaque `credential_ref`
- preferred V1 secret-broker binding via `credential_secret_id`
- policy refs and metadata
- lifecycle status

There is no global ambient Google account. A Google Workspace action must name a `target_user_id`, and if more than one active matching connection exists for that user/service, it must also name `google_connection_id`.

Chunk 5 itself remains intentionally transport-free. The connection model is compatible with both placeholder opaque refs and the later secret-broker migration path, but it still does not execute live OAuth or Google API calls.

## Cross-Channel Trust Rule

Google Workspace reinforces the broader AgentFirst trust doctrine that should be reused across newly onboarded channels where possible:
- provider-native trust, login state, or tenant membership is an input, not automatic sufficiency
- the default posture is provider gate plus AgentFirst gate
- trusted execution still requires an AgentFirst-owned binding, explicit ownership, authority evaluation, and auditable policy linkage

That same rule is the recommended starting point for Google Chat: do not let Google account presence alone become a bypass around AgentFirst trust promotion.

## Authority Model

Google connections are user-owned authority objects.

`AuthorityEngine` resolves:
- `google_connection` to the owning `user_id`
- `google_workspace_action` to the connection owner, or the target user for denied pre-connection cases

The bounded access rule is:
- a user may use their own active Google connection
- another user may use it only when an active `authority_grants` row grants a matching permission over the owner user scope
- otherwise the action is denied before tool policy or simulated execution

## Action and Provenance Model

Google actions are recorded in `google_workspace_actions`.

Allowed actions also create a normal `tool_invocations` row through `PolicyEngine.record_tool_invocation`.

Every Google action stores provenance including:
- `google_connection_id`
- `google_connection_user_id`
- `google_account_email`
- authority policy decision id
- tool invocation id when policy evaluation was reached
- service and operation

Denied authority checks are also recorded as `google_workspace_actions` with `status = authority_denied`, so blocked cross-user attempts are reviewable.

## Bounded Behavior

The V1 service layer supports the four core surfaces as governed action categories:
- `google.gmail`
- `google.calendar`
- `google.contacts`
- `google.drive`

Execution is intentionally represented as a completed bounded action record, not a live Google API call. This keeps Chunk 5 focused on ownership, authority, ambiguity prevention, and provenance.

## Non-Goals

This chunk does not implement:
- OAuth consent screens or token refresh
- Google API client calls
- Docs, Sheets, Maps, or provider routing
- rich connection management UI
- broad policy UX for service-specific scopes

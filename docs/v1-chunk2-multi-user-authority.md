# AgentFirst V1 Chunk 2 Multi-User Authority Foundation

## Scope

V1 Chunk 2 adds a bounded multi-user authority layer over the existing canonical storage model.

The implementation covers:
- cardinality-neutral user creation validated with ten users
- explicit supervisory authority grants
- user-owned memory and channel isolation
- shared-context membership visibility
- audit and policy-decision records for authority checks

It intentionally does not implement Google, BlueBubbles, broad memory retrieval, rich dashboards, or production Telegram changes.

## Authority Model

Authority is resolved by `AuthorityEngine` from explicit object scope:
- user-owned objects are visible to the owning user
- shared-context-owned objects are visible only to active members of that context
- agent-owned objects resolve through the agent owner user or shared context
- supervisory visibility requires an active `authority_grants` row

The bounded V1 actions are:
- `read`
- `monitor`
- `intervene`
- `approve`
- `manage_membership`

The grant table remains the explicit authority edge:
- `grantor_user_id`
- `grantee_user_id`
- `scope_type`
- `scope_ref`
- `permissions_json`
- `constraints_json`
- `effective_at`
- `expires_at`
- `status`

Primary users are not treated as silent readers of all private data. They can administer shared-context membership and create explicit supervision grants where policy allows, but cross-user private visibility still resolves through ownership, membership, or a grant.

## Shared Context Visibility

Shared-context membership is now validated against real user or agent rows before insertion.

For Chunk 2, `shared_contexts.visibility_model = shared-members` means active members may read objects whose owner scope is that shared context. Non-members receive an authority denial, and the denial is recorded.

## Audit Behavior

Every recorded authority evaluation creates:
- a `policy_decisions` row with `action_type = authority:<action>`
- an `audit_events` row with `event_type = authority_evaluated`
- an `event_log` row linking the decision

This keeps allowed supervision and denied overreach reconstructible without adding a UI surface.

## Non-Goals

This chunk does not implement:
- production channel routing changes
- live Telegram supervision semantics
- Google account authority
- model/provider routing
- broad retrieval filtering
- rich supervisory summaries

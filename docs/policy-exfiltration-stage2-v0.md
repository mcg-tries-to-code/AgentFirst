# AgentFirst Stage 2 Policy and Exfiltration Enforcement v0

## Scope

Stage 2 adds a narrow structural enforcement path on top of the Stage 1 store.

Implemented governed action classes:

- `share_external` for outbound message sends
- `query_model` for external model/provider calls
- `export` for export actions
- `invoke_tool` for tool invocations with outbound implications

The implementation lives in `agentfirst_storage.policy` and persists every evaluation as a `policy_decisions` row with linked `audit_events` and `event_log` entries.

## Policy Resolution

`PolicyEngine.evaluate_and_record()` evaluates a `GovernedAction` by:

1. resolving the destination trust tier from `destination_trust_tiers`
2. collecting active `global`/`system`, `primary-user`, and sponsoring-user `per-user` policies
3. collecting classification rules for the action classification, including origin-bound `external_confidential` rules
4. evaluating default classification posture plus matching policy and classification rules
5. selecting the most restrictive applicable outcome, with `deny` dominant
6. writing a `policy_decisions` record
7. writing an `approval_records` row when approval is required
8. writing a linked `audit_events` row and append-only `event_log` row

Layer behavior is intentionally conservative:

- system/global policy is collected first and can always tighten or deny
- primary-user policy applies as the deployment governance layer
- per-user policy applies only for the sponsoring user and can further restrict
- lower layers cannot loosen a stricter higher-layer result because the resolver chooses the most restrictive outcome

Supported outcomes:

- `allow`
- `allow_with_logging`
- `allow_with_redaction`
- `require_primary_user_approval`
- `require_owner_approval`
- `deny`

## Destination Trust Tiers

Destinations are read from `destination_trust_tiers`.

- tier 0: local trusted boundary
- tier 1: approved external trusted service
- tier 2: semi-trusted external provider
- tier 3: untrusted or unknown destination

Unknown destinations resolve to tier 3 and are restrained by default for non-public data.

## External Confidential Handling

`external_confidential` actions must carry `origin_entity_ref`.

Entity-bound classification rules support:

- `origin_entity_ref`
- allowed destinations
- blocked destinations
- approval requirements
- provider/model override rules
- heightened logging requirements as persisted rule metadata

The Stage 2 validation demonstrates ACME NDA data:

- requiring primary-user approval when sent to an approved partner channel
- being denied when queried through a general external model provider

## Approval Records

Stage 2 adds the `approval_records` table. Approval-gated decisions create a requested approval record linked to the policy decision. The record captures requester, approver, approval type, scoped action metadata, justification, status, and timestamps.

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_stage2.py
```

The validation creates a temporary database and proves:

- public outbound message to trusted channel: `allow`
- external confidential outbound message to approved partner channel: `require_primary_user_approval`
- external confidential model provider query to blocked provider: `deny`
- private export constrained by per-user policy: `require_owner_approval`
- outbound-implicated tool invocation: persisted policy decision and tool invocation linkage
- every policy decision has a linked audit event and linked append-only event


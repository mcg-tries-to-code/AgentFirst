# AgentFirst V1 Feature 6 User Management UX Validation Plan

## Status
Implemented validation artifact for the bounded local Feature 6 slice.

## Purpose
Define the bounded local validation contract for the first real user-management UX slice.

## Validation posture
This feature should validate **governed user administration**, not a broad identity platform.

The tests should prove:
- user-management actions route through canonical state
- consequential actions are explicit and auditable
- unauthorized or incomplete actions fail clearly

## Required scenarios

### Scenario 1. User creation
Create a fresh local store with a primary operator, then create one additional active user.

Assert:
- the user record exists canonically
- the UX reflects the new user in list/detail views
- creation does not silently assign elevated authority beyond the requested bounded default

### Scenario 2. User detail with bindings
Attach channel identities and enrollments to a user.

Assert:
- detail view shows user status, identities, and enrollment states coherently
- degraded bindings remain visible instead of disappearing

### Scenario 3. Suspend user
Suspend an active non-primary user.

Assert:
- status changes visibly
- audit/event evidence is emitted
- operator-facing UX reflects the new degraded state

### Scenario 4. Reactivate user
Reactivate the suspended user.

Assert:
- status returns to active
- audit/event evidence is emitted
- the reactivated state is visible in both list and detail views

### Scenario 5. Rejected action paths
Attempt one or more invalid operations, such as:
- missing confirmation token
- nonexistent target user
- unauthorized actor

Assert:
- failures are explicit
- no silent mutation occurs

### Scenario 6. Read-only versus consequential integrity
Compare read-only inspection commands against consequential user-management commands.

Assert:
- inspection remains non-mutating
- create/suspend/reactivate actions produce auditable mutations

## Validation command
Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature6_user_management_ux.py
```

The script prints JSON with:
- `ok`
- `created_user_id`
- `suspended_user_id`
- `reactivated_user_id`
- `audit_events_written`
- `event_log_entries_written`
- `rejected_actions`
- identity/enrollment counts and badges seen
- `read_only_audit_preserved`
- `enrollment_policy_bypassed`

## Implemented command coverage

Read-only user inspection:

```bash
agentfirst tui --command users
agentfirst tui --command "user <user_id>"
agentfirst tui --command "users detail <user_id>"
```

Consequential user administration:

```bash
agentfirst tui --command 'admin user create --actor <primary_user_id> --display-name "Name" --confirm CREATE_USER'
agentfirst tui --command "admin user suspend <user_id> --actor <primary_user_id> --confirm SUSPEND_USER"
agentfirst tui --command "admin user reactivate <user_id> --actor <primary_user_id> --confirm REACTIVATE_USER"
```

The validation asserts read-only commands do not mutate `audit_events` or `event_log`. It also asserts admin create/suspend/reactivate commands produce matching `audit_events` and `event_log` rows.

## Failure conditions
The feature fails validation if it:
- silently mutates user authority or status
- bypasses confirmation on consequential actions
- hides degraded identity/enrollment state
- cannot distinguish read-only inspection from admin mutation
- changes enrollment states while creating, suspending, or reactivating a user

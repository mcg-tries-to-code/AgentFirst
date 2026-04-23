# AgentFirst V1 Feature 6 User Management UX

## Status
Implemented bounded local slice after the Feature 5 inbox implementation.

This is a bounded local-administration UX contract, not a claim of remote multi-operator user management completeness.

## Purpose
Turn the existing read-only user/channel/enrollment inspection surface into a truthful and auditable user-management UX.

## Core judgment
User management must remain:
- local and explicit
- confirmation-based for consequential actions
- audit-linked
- subordinate to the canonical authority and enrollment model already in the repo

It must **not** become a convenience layer that silently bypasses policy, approvals, or trust promotion.

## Implemented bounded UX shape

The trusted local TUI now exposes read-only user-management inspection:

```bash
agentfirst tui --command users
agentfirst tui --command "user <user_id>"
agentfirst tui --command "users detail <user_id>"
```

It also exposes explicit consequential administration:

```bash
agentfirst tui --command 'admin user create --actor <primary_user_id> --display-name "Name" --confirm CREATE_USER'
agentfirst tui --command "admin user suspend <user_id> --actor <primary_user_id> --confirm SUSPEND_USER"
agentfirst tui --command "admin user reactivate <user_id> --actor <primary_user_id> --confirm REACTIVATE_USER"
```

Inspection commands return `READ-ONLY` and do not write audit or event rows. User mutation commands return `ADMIN`, require an active primary actor, require exact confirmation tokens, and write audit/event evidence.

### 1. User list
Shows:
- display name and user id
- status
- authority tier
- primary-user flag
- linked identities/enrollment counts
- active authority grant counts
- degraded or approval-needed badges where applicable

### 2. User detail
Shows:
- profile/status metadata
- authority grants or effective authority summary
- channel identities
- enrollments and their states
- recent audit-relevant actions tied to that user in bounded form
- degraded binding reasons, including suspended users and enrollment approval-needed state

### 3. Consequential administrative actions
Implemented bounded actions:
- create user
- suspend user
- reactivate user

Every consequential action should:
- require explicit confirmation
- say who is acting
- require an active primary local operator
- emit audit/event evidence

Creation is intentionally bounded to non-primary users and does not silently grant administrator authority. Suspension/reactivation changes the canonical `users.status` only; it does not promote, revoke, approve, or repair enrollments.

### 4. Explicit non-actions
This UX should not silently:
- promote channel enrollments
- override approvals
- change primary-user authority casually
- invent grants or bindings to repair broken state
- suspend the primary user through this bounded command
- create administrator users through this bounded command

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature6_user_management_ux.py
```

The validation covers:
1. create a non-primary active user through the canonical path
2. inspect a user with identities and enrollments
3. suspend a user and verify visible degraded state
4. reactivate a suspended user
5. reject incomplete or unauthorized admin actions explicitly
6. confirm audit/event linkage for consequential user-management actions

## Implementation expectations
- keep user-management commands thin over canonical store/service logic
- preserve the distinction between users, grants, identities, and enrollments
- prefer bounded local UX over premature remote administration

## Delivered implementation artifacts
- `OperatorSurface.user_detail`
- `OperatorSurface.create_user_admin`
- `OperatorSurface.suspend_user_admin`
- `OperatorSurface.reactivate_user_admin`
- `TrustedOperatorTUI` read-only user list/detail commands
- `TrustedOperatorTUI` explicit `admin user` commands
- `scripts/validate_v1_feature6_user_management_ux.py`
- updated validation documentation

## Sequencing note
Feature 6 should follow Feature 5 because inbox threads become far more intelligible once the operator can inspect and manage the underlying users and bindings coherently from the same local surface.

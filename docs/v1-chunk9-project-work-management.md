# AgentFirst V1 Chunk 9 Project and Work-Management Expansion

## Scope

V1 Chunk 9 turns projects from lightweight linkage objects into bounded operational work containers.

The implementation covers:
- project participants with explicit roles, permissions, status, and policy refs
- project milestones with artifact and commitment refs
- artifact linkage with provenance on the artifact row
- project-owned commitments through the existing commitment engine
- project policy attachment that participates in policy evaluation for linked artifacts and commitments
- authority and audit records for project-centered reads and mutations

It intentionally does not implement dashboards, portfolio analytics, scheduling heuristics, or broad reporting surfaces.

## Project Container Model

Projects continue to use the canonical `projects` table instead of adding a dashboard-specific model.

The bounded V1 shape is:
- `owner_scope_type` / `owner_scope_ref`: user, agent, or shared-context ownership
- `participants_json`: active project participants with subject, role, status, permissions, and policy refs
- `milestones_json`: milestone objects with status, due date, artifact refs, commitment refs, and policy refs
- `policy_refs_json`: project-attached policies
- `goals_json` and `description_ref`: project intent and durable description

Artifacts remain canonical `artifacts` rows. Linkage is recorded through `project_refs_json` and provenance, so a project can gather artifacts without duplicating document metadata.

Commitments remain canonical `commitments` rows. Project work commitments are created with:
- `owner_scope_type = project`
- `owner_scope_ref = project_id`
- `project_id = project_id`
- inherited project policy refs

## Authority Behavior

`AuthorityEngine` now resolves `object_type = project` to the project itself, not only the project owner scope. That lets project participant permissions govern project reads and work actions.

Project access is allowed when:
- the actor owns the project owner scope
- the actor is a member of the owning shared context
- the actor owns or can use the owning agent context
- the actor is an active project participant with the matching permission
- an explicit authority grant matches

The supported participant permissions intentionally map to the existing bounded authority actions:
- `read`
- `monitor`
- `intervene`
- `approve`
- `manage_membership`

`manage_project` is accepted as a compact permission that expands to all bounded authority actions.

## Policy Behavior

`PolicyEngine` now includes object-attached policies when evaluating governed actions for:
- projects
- commitments
- artifacts
- knowledge corpora

For artifact and commitment actions, policy refs attached to linked projects are included in the policy decision. This makes project policy attachment operational instead of decorative.

## Audit Behavior

Project work mutations record first-class audit and event-log entries:
- `project_created`
- `project_participant_added`
- `project_policy_attached`
- `project_artifact_linked`
- `project_commitment_created`
- `project_milestone_added`

Authority checks continue to write `authority_evaluated` audit events and policy decisions. Policy-gated exports or other governed actions continue to write `policy_evaluated` audit events and policy decisions.

## Non-Goals

This chunk does not implement:
- portfolio views
- dashboard UI
- critical-path scheduling
- project analytics
- recurring task templates
- advanced role inheritance beyond bounded participant permissions

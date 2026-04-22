# AgentFirst Stage 1 Schema and Storage v0

## Storage Shape

Stage 1 uses a hybrid substrate:

- SQLite relational canonical store for first-class v0 objects and indexed queries.
- Append-only `event_log` for consequential object creation and state-transition lineage.
- `audit_events` and `policy_decisions` as first-class queryable records, linked into the event log where appropriate.
- Filesystem artifact layer addressed by durable `file://` storage refs from canonical rows.

The implementation is intentionally dependency-light and migration-friendly. SQLite is the initial concrete store because it is portable, inspectable, and easy to evolve toward Postgres-compatible relational shapes later.

## Canonical Tables

Identity and governance:

- `users`: human principals, including authority tier, primary administrator flag, linked accounts, policy bindings, and contact identities.
- `agents`: AI actors owned by exactly one user or shared context.
- `shared_contexts`: group spaces for team/family/project scopes.
- `shared_context_members`: user/agent membership in shared contexts.
- `authority_grants`: scoped permissions from grantor users to grantee users or agents.
- `policies`: global, primary-user, per-user, project, plugin, skill, and contextual policy documents.
- `data_classification_rules`: classification and exfiltration rules, including `external_confidential` with `origin_entity_ref`.
- `destination_trust_tiers`: local/trusted/semi-trusted/untrusted destination registry.

Interaction and channel:

- `channel_identities`: user or agent identities on transports such as Telegram, BlueBubbles, email, or voice.
- `threads`: durable communication contexts with ownership scope, participants, and project/commitment links.
- `messages`: inbound, outbound, or internal message events with content refs, classification, provenance, and policy refs.

Commitment-first work:

- `commitments`: durable obligations with owner scope, origin, project link, status, next action, due/review dates, and completion criteria.
- `progress_updates`: meaningful updates attached to commitments or projects.
- `task_attention_records`: ownership queue and scheduled review state.
- `waiting_conditions`: explicit waiting dependencies with review/timeout metadata.
- `blocker_records`: real impediments with evidence and resolution options.
- `completion_proofs`: criteria snapshots and evidence for proof-gated completion.
- `projects`: lightweight project scope objects that link work, memory, threads, artifacts, and policy.

Tooling, delegation, and research:

- `tool_capabilities`: registered callable capabilities with provider, schemas, risk class, and audit requirements.
- `tool_invocations`: concrete executions with invoker, sponsoring user, input/output refs, policy decision refs, and status.
- `sub_agent_runs`: delegated execution records with scope and authority boundaries.
- `memory_records`: canonical, mirror, derived, speculative, or scratch memories with owner scope and source refs.
- `knowledge_corpora`: bounded retrieval spaces with source definitions, indexes, and policy refs.
- `search_runs`: search query/result-set records with provider and freshness metadata.
- `research_runs`: bounded research efforts linked to users, agents, sources, searches, outputs, and citations.
- `artifacts`: documents and durable deliverables with filesystem storage refs, owner scope, classification, and provenance.

Audit and policy:

- `policy_decisions`: applicable policies, decision, rationale, action type, destination, trust tier, actor, and sponsoring user.
- `audit_events`: consequential action audit records linked to actor, object, outcome, and optional policy decision.
- `event_log`: append-only event stream with aggregate type/id, actor, payload, and optional audit event link.

## Relationship Strategy

Strict foreign keys are used where the v0 ownership edge is unambiguous and stable, for example:

- `agents.owner_user_id -> users.user_id`
- `agents.shared_context_id -> shared_contexts.shared_context_id`
- `authority_grants.grantor_user_id -> users.user_id`
- `authority_grants.grantee_user_id -> users.user_id`
- `authority_grants.grantee_agent_id -> agents.agent_id`
- `channel_identities.user_id -> users.user_id`
- `channel_identities.agent_id -> agents.agent_id`
- `threads` to commitments/projects through JSON link arrays for v0 lightweight many-to-many linkage
- `messages.thread_id -> threads.thread_id`
- `commitments.project_id -> projects.project_id`
- `task_attention_records.commitment_id -> commitments.commitment_id`
- `waiting_conditions.commitment_id -> commitments.commitment_id`
- `blocker_records.commitment_id -> commitments.commitment_id`
- `completion_proofs.commitment_id -> commitments.commitment_id`
- `tool_invocations.tool_capability_id -> tool_capabilities.tool_capability_id`
- `tool_invocations.sponsoring_user_id -> users.user_id`
- `tool_invocations.invoker_agent_id -> agents.agent_id`
- `sub_agent_runs.parent_agent_id -> agents.agent_id`
- `sub_agent_runs.sponsor_user_id -> users.user_id`
- `policy_decisions.sponsoring_user_id -> users.user_id`
- `audit_events.policy_decision_id -> policy_decisions.policy_decision_id`
- `event_log.audit_event_id -> audit_events.audit_event_id`

Polymorphic owner and object references use explicit `*_type` plus `*_ref` pairs. This keeps the schema project-light and avoids prematurely introducing a universal object table while preserving readable authority and provenance semantics.

## Event and Audit Representation

`event_log` is append-only by convention and contains:

- monotonic `event_id`
- `event_type`
- `aggregate_type`
- `aggregate_id`
- `actor_type`
- `actor_ref`
- structured `payload_json`
- optional `audit_event_id`
- `created_at`

`audit_events` remain queryable first-class canonical records for consequential actions. `policy_decisions` are also first-class and can be referenced by audit events, message events, and tool invocations. This supports later policy/task/channel stages without requiring full event sourcing in Stage 1.

## Artifact Reference Strategy

Artifacts are not stored as blobs in the canonical database. The storage layer writes files under an artifact root and stores durable `file://` refs in canonical rows:

- message content uses `messages.content_ref`
- generated documents use `artifacts.storage_ref`
- tool inputs/outputs use `tool_invocations.input_ref` and `tool_invocations.output_ref`
- memory and research outputs use `content_ref`, `working_notes_ref`, and `output_ref`

Canonical rows carry ownership, classification, provenance, source refs, and project refs so files do not become scattered canonical state.

## Required Indexes

Likely v0 query paths are covered by indexes:

- user and agent lookup by status/owner
- policies by type, priority, owner, and status
- classification by class and origin entity
- channel identity by channel/address and owner
- thread lookup by ownership context and channel
- commitment queues by owner/status, project, review time, and due time
- attention and waiting review queues by `next_review_at`/`review_at`
- messages by thread/time and classification
- progress by parent/time
- audit by actor/object/policy decision
- policy decisions by actor, object, decision, and time
- event log by aggregate, actor, and event type
- memory/corpora by owner and status
- tool capability uniqueness by provider/name
- tool invocations by capability/sponsor/status
- research/search by requestor/provider/status

## Bootstrap and User Creation

The administrator bootstrap path creates exactly one primary user via `AgentFirstStore.bootstrap_admin`. It also creates a default primary-user policy and emits audit/event records.

Additional users use `AgentFirstStore.create_user`, the same generic path for the first extra user and any later user. No user-count cap is represented in schema or code.

CLI examples:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli --db var/agentfirst-v0.sqlite3 bootstrap-admin --display-name "Admin" --timezone America/New_York
PYTHONPATH=src python3 -m agentfirst_storage.cli --db var/agentfirst-v0.sqlite3 create-user --display-name "Collaborator"
```

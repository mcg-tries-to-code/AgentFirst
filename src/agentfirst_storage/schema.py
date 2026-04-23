"""SQLite schema for the AgentFirst v0 canonical and audit stores."""

SCHEMA_VERSION = 2

DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    authority_tier TEXT NOT NULL,
    primary_user_flag INTEGER NOT NULL DEFAULT 0 CHECK (primary_user_flag IN (0, 1)),
    default_timezone TEXT NOT NULL DEFAULT 'UTC',
    contact_identities_json TEXT NOT NULL DEFAULT '[]',
    linked_accounts_json TEXT NOT NULL DEFAULT '[]',
    policy_bindings_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_single_primary
ON users(primary_user_flag)
WHERE primary_user_flag = 1;
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_authority_tier ON users(authority_tier);

CREATE TABLE IF NOT EXISTS google_connections (
    google_connection_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    google_account_email TEXT NOT NULL,
    services_json TEXT NOT NULL DEFAULT '[]',
    scopes_json TEXT NOT NULL DEFAULT '[]',
    credential_ref TEXT,
    credential_secret_id TEXT REFERENCES secret_records(secret_id),
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
    connected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_google_connections_user_email
ON google_connections(user_id, google_account_email);
CREATE INDEX IF NOT EXISTS idx_google_connections_user_status
ON google_connections(user_id, status);

CREATE TABLE IF NOT EXISTS shared_contexts (
    shared_context_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    context_type TEXT NOT NULL,
    visibility_model TEXT NOT NULL DEFAULT 'private',
    governance_policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS shared_context_members (
    shared_context_id TEXT NOT NULL REFERENCES shared_contexts(shared_context_id),
    member_type TEXT NOT NULL CHECK (member_type IN ('user', 'agent')),
    member_ref TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (shared_context_id, member_type, member_ref)
);

CREATE INDEX IF NOT EXISTS idx_shared_context_members_member
ON shared_context_members(member_type, member_ref, status);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(user_id),
    shared_context_id TEXT REFERENCES shared_contexts(shared_context_id),
    persona_profile_json TEXT NOT NULL DEFAULT '{}',
    capability_profile_json TEXT NOT NULL DEFAULT '{}',
    tool_policy_bindings_json TEXT NOT NULL DEFAULT '[]',
    memory_bindings_json TEXT NOT NULL DEFAULT '[]',
    model_routing_policy_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((owner_user_id IS NOT NULL) <> (shared_context_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_agents_owner_user ON agents(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_agents_shared_context ON agents(shared_context_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS authority_grants (
    grant_id TEXT PRIMARY KEY,
    grantor_user_id TEXT NOT NULL REFERENCES users(user_id),
    grantee_user_id TEXT REFERENCES users(user_id),
    grantee_agent_id TEXT REFERENCES agents(agent_id),
    scope_type TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '[]',
    effective_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    CHECK ((grantee_user_id IS NOT NULL) <> (grantee_agent_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_authority_grants_grantee_user ON authority_grants(grantee_user_id, status);
CREATE INDEX IF NOT EXISTS idx_authority_grants_grantee_agent ON authority_grants(grantee_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_authority_grants_scope ON authority_grants(scope_type, scope_ref);

CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    policy_type TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(user_id),
    priority INTEGER NOT NULL DEFAULT 100,
    rules_json TEXT NOT NULL DEFAULT '[]',
    exceptions_json TEXT NOT NULL DEFAULT '[]',
    targets_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_policies_type_priority ON policies(policy_type, priority);
CREATE INDEX IF NOT EXISTS idx_policies_owner ON policies(owner_user_id, status);

CREATE TABLE IF NOT EXISTS data_classification_rules (
    rule_id TEXT PRIMARY KEY,
    classification TEXT NOT NULL CHECK (classification IN ('public', 'internal', 'private', 'sensitive', 'external_confidential', 'proprietary', 'restricted')),
    origin_entity_ref TEXT,
    content_selectors_json TEXT NOT NULL DEFAULT '[]',
    allowed_destinations_json TEXT NOT NULL DEFAULT '[]',
    blocked_destinations_json TEXT NOT NULL DEFAULT '[]',
    approval_requirements_json TEXT NOT NULL DEFAULT '{}',
    logging_requirements_json TEXT NOT NULL DEFAULT '{}',
    override_rules_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_classification_rules_class ON data_classification_rules(classification, status);
CREATE INDEX IF NOT EXISTS idx_classification_rules_origin ON data_classification_rules(origin_entity_ref);

CREATE TABLE IF NOT EXISTS destination_trust_tiers (
    destination_id TEXT PRIMARY KEY,
    destination_type TEXT NOT NULL,
    destination_identity TEXT NOT NULL,
    trust_tier INTEGER NOT NULL CHECK (trust_tier BETWEEN 0 AND 3),
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_destination_identity ON destination_trust_tiers(destination_type, destination_identity);

CREATE TABLE IF NOT EXISTS external_channel_discoveries (
    discovery_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,
    address TEXT NOT NULL,
    display_name TEXT,
    first_seen_metadata_json TEXT NOT NULL DEFAULT '{}',
    last_seen_metadata_json TEXT NOT NULL DEFAULT '{}',
    enrollment_id TEXT,
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'pairing_requested', 'enrollment_started', 'promoted', 'ignored', 'revoked')),
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_discovery_address ON external_channel_discoveries(channel_type, address);
CREATE INDEX IF NOT EXISTS idx_external_discovery_status ON external_channel_discoveries(status, last_seen_at);

CREATE TABLE IF NOT EXISTS channel_enrollments (
    enrollment_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,
    address TEXT NOT NULL,
    discovery_id TEXT REFERENCES external_channel_discoveries(discovery_id),
    user_id TEXT REFERENCES users(user_id),
    channel_identity_id TEXT REFERENCES channel_identities(channel_identity_id),
    state TEXT NOT NULL CHECK (state IN (
        'discovered',
        'pairing_requested',
        'challenge_issued',
        'challenge_verified',
        'awaiting_owner_approval',
        'enrolled',
        'suspended',
        'rebinding_required',
        'recovery_requested',
        'revoked',
        'denied',
        'expired'
    )),
    challenge_ref TEXT,
    challenge_status TEXT NOT NULL DEFAULT 'not_issued' CHECK (challenge_status IN ('not_issued', 'issued', 'verified', 'expired', 'revoked')),
    owner_approval_status TEXT NOT NULL DEFAULT 'not_requested' CHECK (owner_approval_status IN ('not_requested', 'requested', 'approved', 'denied', 'revoked')),
    approved_by_user_id TEXT REFERENCES users(user_id),
    binding_generation INTEGER NOT NULL DEFAULT 1,
    replaces_channel_identity_id TEXT REFERENCES channel_identities(channel_identity_id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'suspended', 'revoked', 'denied', 'expired')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_enrollment_active_address
ON channel_enrollments(channel_type, address)
WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_channel_enrollment_user ON channel_enrollments(user_id, state);
CREATE INDEX IF NOT EXISTS idx_channel_enrollment_state ON channel_enrollments(state, status);

CREATE TABLE IF NOT EXISTS channel_identities (
    channel_identity_id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(user_id),
    agent_id TEXT REFERENCES agents(agent_id),
    channel_type TEXT NOT NULL,
    address TEXT NOT NULL,
    enrollment_id TEXT REFERENCES channel_enrollments(enrollment_id),
    enrollment_state TEXT NOT NULL DEFAULT 'legacy_active' CHECK (enrollment_state IN ('legacy_active', 'enrolled', 'suspended', 'rebinding_required', 'revoked')),
    binding_generation INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    routing_policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((user_id IS NOT NULL) <> (agent_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_identity_address ON channel_identities(channel_type, address);
CREATE INDEX IF NOT EXISTS idx_channel_identity_user ON channel_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_channel_identity_agent ON channel_identities(agent_id);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description_ref TEXT,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context')),
    owner_scope_ref TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    goals_json TEXT NOT NULL DEFAULT '[]',
    milestones_json TEXT NOT NULL DEFAULT '[]',
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_scope_type, owner_scope_ref);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    channel_type TEXT NOT NULL,
    ownership_context_type TEXT NOT NULL CHECK (ownership_context_type IN ('user', 'agent', 'shared_context', 'project')),
    ownership_context_ref TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    visibility_model TEXT NOT NULL DEFAULT 'private',
    linked_project_ids_json TEXT NOT NULL DEFAULT '[]',
    linked_commitment_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_threads_context ON threads(ownership_context_type, ownership_context_ref);
CREATE INDEX IF NOT EXISTS idx_threads_channel ON threads(channel_type, status);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    storage_ref TEXT NOT NULL,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project')),
    owner_scope_ref TEXT NOT NULL,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    project_refs_json TEXT NOT NULL DEFAULT '[]',
    classification TEXT NOT NULL DEFAULT 'internal',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_artifacts_owner ON artifacts(owner_scope_type, owner_scope_ref);
CREATE INDEX IF NOT EXISTS idx_artifacts_classification ON artifacts(classification);

CREATE TABLE IF NOT EXISTS commitments (
    commitment_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    commitment_type TEXT NOT NULL,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project', 'sub_agent_run')),
    owner_scope_ref TEXT NOT NULL,
    origin_ref_type TEXT,
    origin_ref TEXT,
    project_id TEXT REFERENCES projects(project_id),
    status TEXT NOT NULL CHECK (status IN ('captured', 'active', 'waiting', 'blocked', 'delegated', 'completed', 'failed', 'canceled')),
    priority INTEGER NOT NULL DEFAULT 3,
    next_action TEXT,
    due_at TEXT,
    review_at TEXT,
    waiting_on_json TEXT NOT NULL DEFAULT '[]',
    completion_criteria_json TEXT NOT NULL DEFAULT '{}',
    blocker_state_json TEXT NOT NULL DEFAULT '{}',
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_commitments_owner_status ON commitments(owner_scope_type, owner_scope_ref, status);
CREATE INDEX IF NOT EXISTS idx_commitments_project ON commitments(project_id);
CREATE INDEX IF NOT EXISTS idx_commitments_review ON commitments(review_at, status);
CREATE INDEX IF NOT EXISTS idx_commitments_due ON commitments(due_at, status);

CREATE TABLE IF NOT EXISTS messages (
    message_event_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound', 'internal')),
    sender_identity_json TEXT NOT NULL,
    recipient_identities_json TEXT NOT NULL DEFAULT '[]',
    content_ref TEXT NOT NULL,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    classification TEXT NOT NULL DEFAULT 'internal',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    policy_decision_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'stored',
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_time ON messages(thread_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_classification ON messages(classification);

CREATE TABLE IF NOT EXISTS conversation_lanes (
    lane_id TEXT PRIMARY KEY,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project')),
    owner_scope_ref TEXT NOT NULL,
    lane_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'general',
    behavior_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(owner_scope_type, owner_scope_ref, lane_key)
);

CREATE INDEX IF NOT EXISTS idx_conversation_lanes_owner
ON conversation_lanes(owner_scope_type, owner_scope_ref, status);

CREATE TABLE IF NOT EXISTS lane_active_contexts (
    active_context_id TEXT PRIMARY KEY,
    lane_id TEXT NOT NULL REFERENCES conversation_lanes(lane_id),
    session_generation INTEGER NOT NULL DEFAULT 1,
    context_json TEXT NOT NULL DEFAULT '{}',
    runtime_state_json TEXT NOT NULL DEFAULT '{}',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cleared', 'reinitialized')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_lane_active_contexts_lane
ON lane_active_contexts(lane_id, status, session_generation);

CREATE TABLE IF NOT EXISTS lane_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    lane_id TEXT NOT NULL REFERENCES conversation_lanes(lane_id),
    active_context_id TEXT REFERENCES lane_active_contexts(active_context_id),
    reset_command TEXT NOT NULL CHECK (reset_command IN ('/new', '/restart')),
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project')),
    owner_scope_ref TEXT NOT NULL,
    lifecycle_layer TEXT NOT NULL DEFAULT 'mid_term_checkpoint',
    summary_ref TEXT NOT NULL,
    checkpoint_payload_json TEXT NOT NULL DEFAULT '{}',
    preserved_refs_json TEXT NOT NULL DEFAULT '[]',
    dropped_ephemeral_json TEXT NOT NULL DEFAULT '[]',
    memory_record_id TEXT REFERENCES memory_records(memory_id),
    wiki_candidate_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'captured' CHECK (status IN ('captured', 'empty')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_lane_checkpoints_lane
ON lane_checkpoints(lane_id, created_at);
CREATE INDEX IF NOT EXISTS idx_lane_checkpoints_owner
ON lane_checkpoints(owner_scope_type, owner_scope_ref, created_at);

CREATE TABLE IF NOT EXISTS progress_updates (
    progress_update_id TEXT PRIMARY KEY,
    parent_type TEXT NOT NULL CHECK (parent_type IN ('commitment', 'project')),
    parent_ref TEXT NOT NULL,
    author_user_id TEXT REFERENCES users(user_id),
    author_agent_id TEXT REFERENCES agents(agent_id),
    summary TEXT NOT NULL,
    detail_ref TEXT,
    state_change_json TEXT NOT NULL DEFAULT '{}',
    visibility_policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'posted',
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((author_user_id IS NOT NULL) <> (author_agent_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_progress_parent ON progress_updates(parent_type, parent_ref, timestamp);

CREATE TABLE IF NOT EXISTS task_attention_records (
    attention_record_id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL REFERENCES commitments(commitment_id),
    current_owner_type TEXT NOT NULL CHECK (current_owner_type IN ('user', 'agent', 'shared_context', 'project', 'sub_agent_run')),
    current_owner_ref TEXT NOT NULL,
    attention_state TEXT NOT NULL,
    next_review_at TEXT,
    last_meaningful_activity_at TEXT,
    urgency_score REAL NOT NULL DEFAULT 0,
    staleness_score REAL NOT NULL DEFAULT 0,
    escalation_state TEXT NOT NULL DEFAULT 'none',
    heartbeat_policy_ref TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_attention_commitment ON task_attention_records(commitment_id);
CREATE INDEX IF NOT EXISTS idx_attention_review ON task_attention_records(next_review_at, status);

CREATE TABLE IF NOT EXISTS waiting_conditions (
    waiting_condition_id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL REFERENCES commitments(commitment_id),
    waiting_on_type TEXT NOT NULL,
    waiting_on_ref TEXT,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expected_resolution_at TEXT,
    review_at TEXT,
    timeout_policy_ref TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_waiting_commitment ON waiting_conditions(commitment_id, status);
CREATE INDEX IF NOT EXISTS idx_waiting_review ON waiting_conditions(review_at, status);

CREATE TABLE IF NOT EXISTS blocker_records (
    blocker_id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL REFERENCES commitments(commitment_id),
    blocker_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    resolution_options_json TEXT NOT NULL DEFAULT '[]',
    requires_human_decision INTEGER NOT NULL DEFAULT 0 CHECK (requires_human_decision IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'active',
    opened_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_blockers_commitment ON blocker_records(commitment_id, status);

CREATE TABLE IF NOT EXISTS completion_proofs (
    completion_proof_id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL REFERENCES commitments(commitment_id),
    completion_criteria_snapshot_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    verified_by_type TEXT CHECK (verified_by_type IN ('user', 'agent', 'system')),
    verified_by_ref TEXT,
    verified_at TEXT,
    status TEXT NOT NULL DEFAULT 'drafted',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_completion_proofs_commitment ON completion_proofs(commitment_id, status);

CREATE TABLE IF NOT EXISTS tool_capabilities (
    tool_capability_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_schema_ref TEXT,
    output_schema_ref TEXT,
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    availability_status TEXT NOT NULL DEFAULT 'enabled',
    risk_class TEXT NOT NULL DEFAULT 'low',
    audit_requirements_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_capabilities_name_provider ON tool_capabilities(name, provider);

CREATE TABLE IF NOT EXISTS policy_decisions (
    policy_decision_id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'sub_agent_run', 'system')),
    actor_ref TEXT NOT NULL,
    sponsoring_user_id TEXT REFERENCES users(user_id),
    action_type TEXT NOT NULL,
    object_type TEXT,
    object_ref TEXT,
    destination_type TEXT,
    destination_identity TEXT,
    destination_trust_tier INTEGER CHECK (destination_trust_tier BETWEEN 0 AND 3),
    content_classification TEXT,
    applicable_policy_refs_json TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'allow_with_logging', 'allow_with_redaction', 'require_primary_user_approval', 'require_owner_approval', 'deny')),
    rationale_summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_actor ON policy_decisions(actor_type, actor_ref, created_at);
CREATE INDEX IF NOT EXISTS idx_policy_decisions_object ON policy_decisions(object_type, object_ref);
CREATE INDEX IF NOT EXISTS idx_policy_decisions_decision ON policy_decisions(decision, created_at);

CREATE TABLE IF NOT EXISTS approval_records (
    approval_record_id TEXT PRIMARY KEY,
    policy_decision_id TEXT NOT NULL REFERENCES policy_decisions(policy_decision_id),
    requested_by_type TEXT NOT NULL CHECK (requested_by_type IN ('user', 'agent', 'sub_agent_run', 'system')),
    requested_by_ref TEXT NOT NULL,
    approver_user_id TEXT REFERENCES users(user_id),
    approval_type TEXT NOT NULL CHECK (approval_type IN ('primary_user', 'owner')),
    scope_json TEXT NOT NULL DEFAULT '{}',
    justification_summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'denied', 'expired', 'canceled')),
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_records_decision ON approval_records(policy_decision_id);
CREATE INDEX IF NOT EXISTS idx_approval_records_approver ON approval_records(approver_user_id, status);

CREATE TABLE IF NOT EXISTS tool_invocations (
    tool_invocation_id TEXT PRIMARY KEY,
    tool_capability_id TEXT NOT NULL REFERENCES tool_capabilities(tool_capability_id),
    invoker_agent_id TEXT REFERENCES agents(agent_id),
    sponsoring_user_id TEXT NOT NULL REFERENCES users(user_id),
    authority_policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id),
    operation TEXT,
    scope_json TEXT NOT NULL DEFAULT '{}',
    input_ref TEXT,
    output_ref TEXT,
    policy_decision_refs_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    outcome_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'requested',
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_tool_invocations_capability ON tool_invocations(tool_capability_id, status);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_sponsor ON tool_invocations(sponsoring_user_id, created_at);

CREATE TABLE IF NOT EXISTS google_workspace_actions (
    google_workspace_action_id TEXT PRIMARY KEY,
    service TEXT NOT NULL CHECK (service IN ('gmail', 'calendar', 'contacts', 'drive')),
    operation TEXT NOT NULL,
    actor_user_id TEXT NOT NULL REFERENCES users(user_id),
    target_user_id TEXT NOT NULL REFERENCES users(user_id),
    google_connection_id TEXT REFERENCES google_connections(google_connection_id),
    google_connection_user_id TEXT REFERENCES users(user_id),
    google_account_email TEXT,
    tool_invocation_id TEXT REFERENCES tool_invocations(tool_invocation_id),
    authority_policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id),
    status TEXT NOT NULL CHECK (status IN (
        'authority_denied',
        'policy_denied',
        'awaiting_approval',
        'policy_allowed',
        'completed',
        'failed'
    )),
    input_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_google_workspace_actions_connection
ON google_workspace_actions(google_connection_id, created_at);
CREATE INDEX IF NOT EXISTS idx_google_workspace_actions_actor
ON google_workspace_actions(actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_google_workspace_actions_target
ON google_workspace_actions(target_user_id, created_at);

CREATE TABLE IF NOT EXISTS sub_agent_runs (
    sub_agent_run_id TEXT PRIMARY KEY,
    parent_agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    sponsor_user_id TEXT NOT NULL REFERENCES users(user_id),
    goal TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    authority_scope_json TEXT NOT NULL DEFAULT '{}',
    input_artifacts_json TEXT NOT NULL DEFAULT '[]',
    deliverable_expectation_json TEXT NOT NULL DEFAULT '{}',
    provenance_refs_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT,
    status TEXT NOT NULL DEFAULT 'requested',
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sub_agent_runs_parent ON sub_agent_runs(parent_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_sub_agent_runs_sponsor ON sub_agent_runs(sponsor_user_id, status);

CREATE TABLE IF NOT EXISTS memory_records (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project')),
    owner_scope_ref TEXT NOT NULL,
    visibility_policy_refs_json TEXT NOT NULL DEFAULT '[]',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    content_ref TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    canonicality TEXT NOT NULL CHECK (canonicality IN ('canonical', 'mirror', 'derived', 'speculative', 'scratch')),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_owner ON memory_records(owner_scope_type, owner_scope_ref, canonicality);
CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_records(status);

CREATE TABLE IF NOT EXISTS memory_retrievals (
    retrieval_id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL REFERENCES users(user_id),
    sponsoring_user_id TEXT NOT NULL REFERENCES users(user_id),
    query TEXT NOT NULL,
    requested_scopes_json TEXT NOT NULL DEFAULT '[]',
    allowed_scopes_json TEXT NOT NULL DEFAULT '[]',
    denied_scopes_json TEXT NOT NULL DEFAULT '[]',
    authority_policy_decision_refs_json TEXT NOT NULL DEFAULT '[]',
    result_refs_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('returned', 'denied', 'empty')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_retrievals_actor
ON memory_retrievals(actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_retrievals_sponsor
ON memory_retrievals(sponsoring_user_id, created_at);

CREATE TABLE IF NOT EXISTS knowledge_corpora (
    corpus_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_scope_type TEXT NOT NULL CHECK (owner_scope_type IN ('user', 'agent', 'shared_context', 'project')),
    owner_scope_ref TEXT NOT NULL,
    corpus_type TEXT NOT NULL,
    source_definitions_json TEXT NOT NULL DEFAULT '[]',
    index_refs_json TEXT NOT NULL DEFAULT '[]',
    policy_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'defined',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_corpora_owner ON knowledge_corpora(owner_scope_type, owner_scope_ref);
CREATE INDEX IF NOT EXISTS idx_corpora_status ON knowledge_corpora(status);

CREATE TABLE IF NOT EXISTS search_runs (
    search_run_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    provider TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    request_context_json TEXT NOT NULL DEFAULT '{}',
    results_ref TEXT NOT NULL,
    freshness_metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'returned',
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_search_runs_provider_time ON search_runs(provider, timestamp);
CREATE INDEX IF NOT EXISTS idx_search_runs_status ON search_runs(status);

CREATE TABLE IF NOT EXISTS research_runs (
    research_run_id TEXT PRIMARY KEY,
    requestor_user_id TEXT NOT NULL REFERENCES users(user_id),
    sponsoring_agent_id TEXT REFERENCES agents(agent_id),
    question TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    search_refs_json TEXT NOT NULL DEFAULT '[]',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    working_notes_ref TEXT,
    output_ref TEXT,
    citation_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'requested',
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_research_runs_requestor ON research_runs(requestor_user_id, status);
CREATE INDEX IF NOT EXISTS idx_research_runs_agent ON research_runs(sponsoring_agent_id, status);

CREATE TABLE IF NOT EXISTS model_provider_preferences (
    model_preference_id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('user', 'agent', 'task')),
    scope_ref TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'general',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    fallback_routes_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    rationale_summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
    created_by_type TEXT NOT NULL CHECK (created_by_type IN ('user', 'agent', 'system')),
    created_by_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_model_preferences_scope
ON model_provider_preferences(scope_type, scope_ref, purpose, status, priority);
CREATE INDEX IF NOT EXISTS idx_model_preferences_provider
ON model_provider_preferences(provider, model, status);

CREATE TABLE IF NOT EXISTS model_route_decisions (
    model_route_decision_id TEXT PRIMARY KEY,
    model_preference_id TEXT REFERENCES model_provider_preferences(model_preference_id),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'system')),
    actor_ref TEXT NOT NULL,
    sponsoring_user_id TEXT NOT NULL REFERENCES users(user_id),
    requesting_agent_id TEXT REFERENCES agents(agent_id),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('user', 'agent', 'task')),
    scope_ref TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'general',
    preferred_provider TEXT,
    preferred_model TEXT,
    selected_provider TEXT,
    selected_model TEXT,
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK (fallback_used IN (0, 1)),
    fallback_reason TEXT,
    disclosure_summary TEXT NOT NULL,
    policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id),
    approval_record_id TEXT REFERENCES approval_records(approval_record_id),
    provenance_json TEXT NOT NULL DEFAULT '{}',
    outcome_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('selected', 'awaiting_approval', 'denied', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_model_route_decisions_sponsor
ON model_route_decisions(sponsoring_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_model_route_decisions_scope
ON model_route_decisions(scope_type, scope_ref, purpose, created_at);
CREATE INDEX IF NOT EXISTS idx_model_route_decisions_policy
ON model_route_decisions(policy_decision_id);

CREATE TABLE IF NOT EXISTS model_executions (
    model_execution_id TEXT PRIMARY KEY,
    model_route_decision_id TEXT NOT NULL REFERENCES model_route_decisions(model_route_decision_id),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'system')),
    actor_ref TEXT NOT NULL,
    sponsoring_user_id TEXT NOT NULL REFERENCES users(user_id),
    requesting_agent_id TEXT REFERENCES agents(agent_id),
    provider TEXT,
    model TEXT,
    lane TEXT,
    transport TEXT,
    prompt_sha256 TEXT NOT NULL,
    prompt_preview TEXT NOT NULL,
    disclosure_summary TEXT NOT NULL,
    real_execution INTEGER NOT NULL DEFAULT 0 CHECK (real_execution IN (0, 1)),
    outcome_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('executed', 'unavailable', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_model_executions_route
ON model_executions(model_route_decision_id);
CREATE INDEX IF NOT EXISTS idx_model_executions_sponsor
ON model_executions(sponsoring_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_model_executions_provider
ON model_executions(provider, model, lane, created_at);

CREATE TABLE IF NOT EXISTS secret_records (
    secret_id TEXT PRIMARY KEY,
    handle_uri TEXT NOT NULL UNIQUE,
    owner_type TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    scope_type TEXT,
    scope_ref TEXT,
    integration_type TEXT NOT NULL,
    secret_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked', 'destroyed')),
    current_version INTEGER NOT NULL DEFAULT 1,
    fingerprint TEXT NOT NULL,
    display_hint TEXT,
    vault_backend TEXT NOT NULL,
    vault_ref TEXT,
    root_key_provider TEXT NOT NULL,
    expires_at TEXT,
    rotated_at TEXT,
    revoked_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_secret_records_owner ON secret_records(owner_type, owner_ref, status);
CREATE INDEX IF NOT EXISTS idx_secret_records_integration ON secret_records(integration_type, secret_kind, status);

CREATE TABLE IF NOT EXISTS secret_access_events (
    secret_access_event_id TEXT PRIMARY KEY,
    secret_id TEXT NOT NULL REFERENCES secret_records(secret_id),
    handle_uri TEXT NOT NULL,
    secret_version INTEGER NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'sub_agent_run', 'system')),
    actor_ref TEXT NOT NULL,
    operation TEXT NOT NULL,
    purpose TEXT NOT NULL,
    integration_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_secret_access_events_secret ON secret_access_events(secret_id, created_at);
CREATE INDEX IF NOT EXISTS idx_secret_access_events_actor ON secret_access_events(actor_type, actor_ref, created_at);

CREATE TABLE IF NOT EXISTS onboarding_bootstraps (
    onboarding_bootstrap_id TEXT PRIMARY KEY,
    primary_operator_user_id TEXT NOT NULL REFERENCES users(user_id),
    custody_mode TEXT NOT NULL CHECK (custody_mode IN ('operator_passphrase', 'macos_keychain')),
    custody_json TEXT NOT NULL DEFAULT '{}',
    model_preference_id TEXT REFERENCES model_provider_preferences(model_preference_id),
    provider TEXT,
    model TEXT,
    channels_json TEXT NOT NULL DEFAULT '[]',
    secrets_json TEXT NOT NULL DEFAULT '[]',
    readiness_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('ready', 'incomplete')),
    created_by_type TEXT NOT NULL CHECK (created_by_type IN ('user', 'agent', 'system')),
    created_by_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_onboarding_bootstraps_operator
ON onboarding_bootstraps(primary_operator_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_onboarding_bootstraps_status
ON onboarding_bootstraps(status, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'sub_agent_run', 'system')),
    actor_ref TEXT NOT NULL,
    object_type TEXT,
    object_ref TEXT,
    action_summary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_type, actor_ref, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_object ON audit_events(object_type, object_ref, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_policy_decision ON audit_events(policy_decision_id);

CREATE TABLE IF NOT EXISTS event_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'sub_agent_run', 'system')),
    actor_ref TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    audit_event_id TEXT REFERENCES audit_events(audit_event_id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_event_log_aggregate ON event_log(aggregate_type, aggregate_id, event_id);
CREATE INDEX IF NOT EXISTS idx_event_log_actor ON event_log(actor_type, actor_ref, event_id);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type, event_id);
"""

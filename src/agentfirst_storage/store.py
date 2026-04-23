"""Repository helpers for AgentFirst v0 Stage 1 storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schema import DDL, SCHEMA_VERSION


JSON_COLUMNS = {
    "audit_requirements_json",
    "metadata_json",
    "services_json",
    "scopes_json",
    "contact_identities_json",
    "linked_accounts_json",
    "policy_bindings_json",
    "governance_policy_refs_json",
    "persona_profile_json",
    "capability_profile_json",
    "tool_policy_bindings_json",
    "memory_bindings_json",
    "model_routing_policy_json",
    "permissions_json",
    "constraints_json",
    "rules_json",
    "exceptions_json",
    "targets_json",
    "content_selectors_json",
    "allowed_destinations_json",
    "blocked_destinations_json",
    "approval_requirements_json",
    "logging_requirements_json",
    "override_rules_json",
    "routing_policy_refs_json",
    "first_seen_metadata_json",
    "last_seen_metadata_json",
    "participants_json",
    "goals_json",
    "milestones_json",
    "policy_refs_json",
    "linked_project_ids_json",
    "linked_commitment_ids_json",
    "source_refs_json",
    "requested_scopes_json",
    "allowed_scopes_json",
    "denied_scopes_json",
    "authority_policy_decision_refs_json",
    "result_refs_json",
    "project_refs_json",
    "provenance_json",
    "waiting_on_json",
    "completion_criteria_json",
    "blocker_state_json",
    "sender_identity_json",
    "recipient_identities_json",
    "attachments_json",
    "policy_decision_refs_json",
    "behavior_json",
    "context_json",
    "runtime_state_json",
    "checkpoint_payload_json",
    "preserved_refs_json",
    "dropped_ephemeral_json",
    "wiki_candidate_refs_json",
    "state_change_json",
    "visibility_policy_refs_json",
    "completion_criteria_snapshot_json",
    "evidence_refs_json",
    "applicable_policy_refs_json",
    "scope_json",
    "authority_scope_json",
    "input_artifacts_json",
    "deliverable_expectation_json",
    "provenance_refs_json",
    "source_definitions_json",
    "index_refs_json",
    "filters_json",
    "request_context_json",
    "freshness_metadata_json",
    "search_refs_json",
    "citation_refs_json",
    "payload_json",
    "resolution_options_json",
    "input_json",
    "result_json",
    "outcome_json",
    "fallback_routes_json",
    "provider_metadata_json",
    "custody_json",
    "channels_json",
    "secrets_json",
    "readiness_json",
}


PRIMARY_KEYS = {
    "users": "user_id",
    "google_connections": "google_connection_id",
    "shared_contexts": "shared_context_id",
    "agents": "agent_id",
    "authority_grants": "grant_id",
    "policies": "policy_id",
    "data_classification_rules": "rule_id",
    "destination_trust_tiers": "destination_id",
    "external_channel_discoveries": "discovery_id",
    "channel_enrollments": "enrollment_id",
    "channel_identities": "channel_identity_id",
    "projects": "project_id",
    "threads": "thread_id",
    "artifacts": "artifact_id",
    "commitments": "commitment_id",
    "messages": "message_event_id",
    "conversation_lanes": "lane_id",
    "lane_active_contexts": "active_context_id",
    "lane_checkpoints": "checkpoint_id",
    "progress_updates": "progress_update_id",
    "task_attention_records": "attention_record_id",
    "waiting_conditions": "waiting_condition_id",
    "blocker_records": "blocker_id",
    "completion_proofs": "completion_proof_id",
    "tool_capabilities": "tool_capability_id",
    "policy_decisions": "policy_decision_id",
    "approval_records": "approval_record_id",
    "tool_invocations": "tool_invocation_id",
    "google_workspace_actions": "google_workspace_action_id",
    "sub_agent_runs": "sub_agent_run_id",
    "memory_records": "memory_id",
    "memory_retrievals": "retrieval_id",
    "knowledge_corpora": "corpus_id",
    "search_runs": "search_run_id",
    "research_runs": "research_run_id",
    "model_provider_preferences": "model_preference_id",
    "model_route_decisions": "model_route_decision_id",
    "model_executions": "model_execution_id",
    "secret_records": "secret_id",
    "secret_access_events": "secret_access_event_id",
    "onboarding_bootstraps": "onboarding_bootstrap_id",
    "audit_events": "audit_event_id",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class AgentFirstStore:
    """Small repository over the canonical SQLite store and artifact root."""

    def __init__(self, db_path: str | Path, artifact_root: str | Path | None = None):
        self.db_path = Path(db_path)
        self.artifact_root = Path(artifact_root) if artifact_root else self.db_path.with_suffix(".artifacts")

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(DDL)
            self._apply_lightweight_migrations(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def bootstrap_admin(self, display_name: str, timezone: str = "UTC") -> dict[str, Any]:
        """Create or return the single primary administrator user."""
        self.initialize()
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM users WHERE primary_user_flag = 1").fetchone()
            if existing:
                return self._decode_row(existing)

            admin = self.create_user(
                display_name=display_name,
                authority_tier="administrator",
                primary_user=True,
                default_timezone=timezone,
                actor_type="system",
                actor_ref="bootstrap",
                conn=conn,
            )
            policy_id = new_id("pol")
            self.insert(
                "policies",
                {
                    "policy_id": policy_id,
                    "policy_type": "primary-user",
                    "owner_user_id": admin["user_id"],
                    "priority": 10,
                    "rules_json": [
                        {
                            "action": "share_external",
                            "default": "require_primary_user_approval",
                            "classification_floor": "private",
                        }
                    ],
                    "targets_json": ["user", "agent", "tool_invocation", "message"],
                    "status": "active",
                },
                conn=conn,
                emit_event=False,
            )
            self.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "administrator_bootstrap",
                    "actor_type": "system",
                    "actor_ref": "bootstrap",
                    "object_type": "user",
                    "object_ref": admin["user_id"],
                    "action_summary": "Administrator user bootstrapped",
                    "outcome": "created",
                    "metadata_json": {"policy_id": policy_id},
                },
                conn=conn,
                emit_event=False,
            )
            self.append_event(
                "administrator_bootstrapped",
                "user",
                admin["user_id"],
                "system",
                "bootstrap",
                {"policy_id": policy_id},
                conn=conn,
            )
            return admin

    def create_user(
        self,
        display_name: str,
        authority_tier: str = "standard",
        primary_user: bool = False,
        default_timezone: str = "UTC",
        contact_identities: list[dict[str, Any]] | None = None,
        linked_accounts: list[dict[str, Any]] | None = None,
        policy_bindings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_ref: str = "user_creation",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Generic cardinality-agnostic user creation path."""
        user = {
            "user_id": new_id("usr"),
            "display_name": display_name,
            "status": "active",
            "authority_tier": authority_tier,
            "primary_user_flag": 1 if primary_user else 0,
            "default_timezone": default_timezone,
            "contact_identities_json": contact_identities or [],
            "linked_accounts_json": linked_accounts or [],
            "policy_bindings_json": policy_bindings or [],
            "metadata_json": metadata or {},
        }

        owns_connection = conn is None
        if owns_connection:
            self.initialize()
            conn = self.connect()
        assert conn is not None
        try:
            created = self.insert("users", user, conn=conn, emit_event=False)
            self.append_event(
                "user_created",
                "user",
                created["user_id"],
                actor_type,
                actor_ref,
                {
                    "display_name": display_name,
                    "authority_tier": authority_tier,
                    "primary_user": primary_user,
                },
                conn=conn,
            )
            self.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "user_created",
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "object_type": "user",
                    "object_ref": created["user_id"],
                    "action_summary": f"Created user {display_name}",
                    "outcome": "created",
                    "metadata_json": {"authority_tier": authority_tier, "primary_user": primary_user},
                },
                conn=conn,
                emit_event=False,
            )
            if owns_connection:
                conn.commit()
            return created
        finally:
            if owns_connection:
                conn.close()

    def add_shared_context_member(
        self,
        shared_context_id: str,
        member_type: str,
        member_ref: str,
        role: str = "member",
        status: str = "active",
        *,
        actor_type: str = "system",
        actor_ref: str = "storage",
    ) -> dict[str, Any]:
        if member_type not in {"user", "agent"}:
            raise ValueError("member_type must be 'user' or 'agent'")
        self.initialize()
        with self.connect() as conn:
            context = self.get_by_id("shared_contexts", shared_context_id, conn=conn)
            if context is None:
                raise ValueError(f"Shared context not found: {shared_context_id}")
            if member_type == "user":
                member = self.get_by_id("users", member_ref, conn=conn)
            else:
                member = self.get_by_id("agents", member_ref, conn=conn)
            if member is None:
                raise ValueError(f"{member_type} member not found: {member_ref}")
            conn.execute(
                """
                INSERT INTO shared_context_members (
                    shared_context_id, member_type, member_ref, role, status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (shared_context_id, member_type, member_ref, role, status),
            )
            self.append_event(
                "shared_context_member_added",
                "shared_context",
                shared_context_id,
                actor_type,
                actor_ref,
                {"member_type": member_type, "member_ref": member_ref, "role": role},
                conn=conn,
            )
            row = conn.execute(
                """
                SELECT * FROM shared_context_members
                WHERE shared_context_id = ? AND member_type = ? AND member_ref = ?
                """,
                (shared_context_id, member_type, member_ref),
            ).fetchone()
            assert row is not None
            return self._decode_row(row)

    def list_shared_context_members(self, shared_context_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shared_context_members
                WHERE shared_context_id = ?
                ORDER BY created_at, member_type, member_ref
                """,
                (shared_context_id,),
            ).fetchall()
            return [self._decode_row(row) for row in rows]

    def insert(
        self,
        table: str,
        values: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
        emit_event: bool = True,
        actor_type: str = "system",
        actor_ref: str = "storage",
    ) -> dict[str, Any]:
        if table not in PRIMARY_KEYS:
            raise ValueError(f"Unsupported table: {table}")

        row = dict(values)
        pk = PRIMARY_KEYS[table]
        row.setdefault(pk, new_id(pk.removesuffix("_id")))
        encoded = {key: self._encode_value(key, value) for key, value in row.items()}

        owns_connection = conn is None
        if owns_connection:
            self.initialize()
            conn = self.connect()
        assert conn is not None
        try:
            columns = list(encoded)
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(columns)
            conn.execute(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                tuple(encoded[column] for column in columns),
            )
            created = self.get_by_id(table, row[pk], conn=conn)
            if emit_event:
                self.append_event(
                    f"{table.rstrip('s')}_created",
                    table,
                    row[pk],
                    actor_type,
                    actor_ref,
                    {"record_id": row[pk]},
                    conn=conn,
                )
            if owns_connection:
                conn.commit()
            assert created is not None
            return created
        finally:
            if owns_connection:
                conn.close()

    def update(
        self,
        table: str,
        record_id: str,
        values: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
        emit_event: bool = True,
        actor_type: str = "system",
        actor_ref: str = "storage",
        event_type: str | None = None,
    ) -> dict[str, Any]:
        if table not in PRIMARY_KEYS:
            raise ValueError(f"Unsupported table: {table}")
        if not values:
            existing = self.get_by_id(table, record_id, conn=conn)
            if existing is None:
                raise ValueError(f"{table} row not found: {record_id}")
            return existing

        pk = PRIMARY_KEYS[table]
        encoded = {key: self._encode_value(key, value) for key, value in values.items()}
        owns_connection = conn is None
        if owns_connection:
            self.initialize()
            conn = self.connect()
        assert conn is not None
        try:
            assignments = ", ".join(f"{column} = ?" for column in encoded)
            cursor = conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {pk} = ?",
                (*encoded.values(), record_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"{table} row not found: {record_id}")
            updated = self.get_by_id(table, record_id, conn=conn)
            if emit_event:
                self.append_event(
                    event_type or f"{table.rstrip('s')}_updated",
                    table,
                    record_id,
                    actor_type,
                    actor_ref,
                    {"record_id": record_id, "updated_fields": sorted(values)},
                    conn=conn,
                )
            if owns_connection:
                conn.commit()
            assert updated is not None
            return updated
        finally:
            if owns_connection:
                conn.close()

    def get_by_id(
        self,
        table: str,
        record_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if table not in PRIMARY_KEYS:
            raise ValueError(f"Unsupported table: {table}")
        pk = PRIMARY_KEYS[table]
        owns_connection = conn is None
        if owns_connection:
            conn = self.connect()
        assert conn is not None
        try:
            row = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (record_id,)).fetchone()
            return self._decode_row(row) if row else None
        finally:
            if owns_connection:
                conn.close()

    def list_records(self, table: str, limit: int = 100) -> list[dict[str, Any]]:
        if table not in PRIMARY_KEYS and table != "event_log":
            raise ValueError(f"Unsupported table: {table}")
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
            return [self._decode_row(row) for row in rows]

    def write_artifact(self, relative_path: str, content: str | bytes) -> str:
        """Write bytes under the artifact root and return a durable storage ref."""
        target = (self.artifact_root / relative_path).resolve()
        root = self.artifact_root.resolve()
        if not str(target).startswith(str(root)):
            raise ValueError("Artifact path must stay under artifact root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        return f"file://{target}"

    def append_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        actor_type: str,
        actor_ref: str,
        payload: dict[str, Any] | None = None,
        *,
        audit_event_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        owns_connection = conn is None
        if owns_connection:
            self.initialize()
            conn = self.connect()
        assert conn is not None
        try:
            cursor = conn.execute(
                """
                INSERT INTO event_log (
                    event_type, aggregate_type, aggregate_id, actor_type, actor_ref,
                    payload_json, audit_event_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    actor_type,
                    actor_ref,
                    json.dumps(payload or {}, sort_keys=True),
                    audit_event_id,
                ),
            )
            if owns_connection:
                conn.commit()
            return int(cursor.lastrowid)
        finally:
            if owns_connection:
                conn.close()

    def _apply_lightweight_migrations(self, conn: sqlite3.Connection) -> None:
        """Keep pre-existing local v0 databases usable as V1 columns are added."""
        channel_existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(channel_identities)").fetchall()
        }
        channel_additions = [
            ("enrollment_id", "TEXT REFERENCES channel_enrollments(enrollment_id)"),
            ("enrollment_state", "TEXT NOT NULL DEFAULT 'legacy_active'"),
            ("binding_generation", "INTEGER NOT NULL DEFAULT 1"),
        ]
        for column, definition in channel_additions:
            if column not in channel_existing:
                conn.execute(f"ALTER TABLE channel_identities ADD COLUMN {column} {definition}")

        invocation_existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tool_invocations)").fetchall()
        }
        invocation_additions = [
            ("authority_policy_decision_id", "TEXT REFERENCES policy_decisions(policy_decision_id)"),
            ("operation", "TEXT"),
            ("scope_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("provenance_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("outcome_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]
        for column, definition in invocation_additions:
            if column not in invocation_existing:
                conn.execute(f"ALTER TABLE tool_invocations ADD COLUMN {column} {definition}")

        google_existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(google_connections)").fetchall()
        }
        google_additions = [
            ("credential_secret_id", "TEXT REFERENCES secret_records(secret_id)"),
        ]
        for column, definition in google_additions:
            if column not in google_existing:
                conn.execute(f"ALTER TABLE google_connections ADD COLUMN {column} {definition}")

        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_retrievals_actor
            ON memory_retrievals(actor_user_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_retrievals_sponsor
            ON memory_retrievals(sponsoring_user_id, created_at)
            """
        )
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_lanes_owner
            ON conversation_lanes(owner_scope_type, owner_scope_ref, status)
            """
        )
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lane_active_contexts_lane
            ON lane_active_contexts(lane_id, status, session_generation)
            """
        )
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lane_checkpoints_lane
            ON lane_checkpoints(lane_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lane_checkpoints_owner
            ON lane_checkpoints(owner_scope_type, owner_scope_ref, created_at)
            """
        )

        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_secret_records_owner
            ON secret_records(owner_type, owner_ref, status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_secret_records_integration
            ON secret_records(integration_type, secret_kind, status)
            """
        )
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_secret_access_events_secret
            ON secret_access_events(secret_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_secret_access_events_actor
            ON secret_access_events(actor_type, actor_ref, created_at)
            """
        )
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_onboarding_bootstraps_operator
            ON onboarding_bootstraps(primary_operator_user_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_onboarding_bootstraps_status
            ON onboarding_bootstraps(status, created_at)
            """
        )

    def _encode_value(self, key: str, value: Any) -> Any:
        if key.endswith("_json") or key in JSON_COLUMNS:
            return json.dumps(value, sort_keys=True)
        if isinstance(value, bool):
            return 1 if value else 0
        return value

    def _decode_row(self, row: sqlite3.Row) -> dict[str, Any]:
        decoded = dict(row)
        for key, value in list(decoded.items()):
            if value is not None and (key.endswith("_json") or key in JSON_COLUMNS):
                decoded[key] = json.loads(value)
        return decoded

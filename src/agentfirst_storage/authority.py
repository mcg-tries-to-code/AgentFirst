"""Multi-user authority and visibility enforcement for AgentFirst V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .store import AgentFirstStore, new_id


AUTHORITY_ACTIONS = {
    "read",
    "monitor",
    "intervene",
    "approve",
    "manage_membership",
}

ACTION_PERMISSIONS = {
    "read": {"read", "read_private", "read_context", "supervise"},
    "monitor": {"monitor", "supervise"},
    "intervene": {"intervene", "supervise"},
    "approve": {"approve", "supervise"},
    "manage_membership": {"manage_membership", "administer_context"},
}


@dataclass(frozen=True)
class AuthorityRequest:
    """A user authority check against a canonical object."""

    actor_user_id: str
    action: str
    object_type: str
    object_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuthorityEngine:
    """Bounded V1 authority resolver for users, supervision, and shared contexts."""

    def __init__(self, store: AgentFirstStore):
        self.store = store

    def create_supervisory_grant(
        self,
        *,
        grantor_user_id: str,
        grantee_user_id: str,
        target_user_id: str,
        permissions: list[str],
        constraints: list[dict[str, Any]] | None = None,
        effective_at: str | None = None,
        expires_at: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create an explicit supervisory edge over one target user."""
        if not permissions:
            raise ValueError("A supervisory grant requires at least one permission")
        unknown = set(permissions) - set().union(*ACTION_PERMISSIONS.values())
        if unknown:
            raise ValueError(f"Unsupported supervisory permission(s): {sorted(unknown)}")

        self.store.initialize()
        with self.store.connect() as conn:
            grantor = self._require_active_user(conn, grantor_user_id)
            self._require_active_user(conn, grantee_user_id)
            self._require_active_user(conn, target_user_id)
            if grantor_user_id != target_user_id and not grantor["primary_user_flag"]:
                raise PermissionError("Only the target user or primary user may grant user supervision")

            grant = self.store.insert(
                "authority_grants",
                {
                    "grant_id": new_id("grant"),
                    "grantor_user_id": grantor_user_id,
                    "grantee_user_id": grantee_user_id,
                    "scope_type": "user",
                    "scope_ref": target_user_id,
                    "permissions_json": permissions,
                    "constraints_json": constraints or [],
                    "effective_at": effective_at or self._now(),
                    "expires_at": expires_at,
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=grantor_user_id,
            )
            audit = self._audit(
                conn,
                "authority_grant_created",
                grantor_user_id,
                "authority_grant",
                grant["grant_id"],
                "Created explicit supervisory authority grant",
                "created",
                {
                    "grantee_user_id": grantee_user_id,
                    "target_user_id": target_user_id,
                    "permissions": permissions,
                },
            )
            self.store.append_event(
                "authority_grant_created",
                "authority_grant",
                grant["grant_id"],
                "user",
                grantor_user_id,
                {"audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return grant

    def add_shared_context_member(
        self,
        *,
        shared_context_id: str,
        member_user_id: str,
        role: str = "member",
        actor_user_id: str,
    ) -> dict[str, Any]:
        """Add a user member when the actor has context administration authority."""
        self.store.initialize()
        with self.store.connect() as conn:
            self._require_shared_context(conn, shared_context_id)
            self._require_active_user(conn, member_user_id)
            decision = self._evaluate(
                conn,
                AuthorityRequest(actor_user_id, "manage_membership", "shared_context", shared_context_id),
                record=False,
            )
            if not decision["allowed"]:
                self._record_decision(conn, decision)
                raise PermissionError(decision["rationale"])
            member = self._insert_shared_context_member(
                conn,
                shared_context_id,
                "user",
                member_user_id,
                role,
                actor_user_id,
            )
            self._record_decision(conn, decision)
            return member

    def evaluate(self, request: AuthorityRequest) -> dict[str, Any]:
        """Evaluate and record a user authority decision."""
        self.store.initialize()
        with self.store.connect() as conn:
            decision = self._evaluate(conn, request, record=False)
            return self._record_decision(conn, decision)

    def can_read(self, actor_user_id: str, object_type: str, object_ref: str) -> bool:
        return bool(
            self.evaluate(
                AuthorityRequest(
                    actor_user_id=actor_user_id,
                    action="read",
                    object_type=object_type,
                    object_ref=object_ref,
                )
            )["allowed"]
        )

    def _evaluate(self, conn: Any, request: AuthorityRequest, *, record: bool) -> dict[str, Any]:
        if request.action not in AUTHORITY_ACTIONS:
            raise ValueError(f"Unsupported authority action: {request.action}")

        actor = self._require_active_user(conn, request.actor_user_id)
        target = self._resolve_object_scope(conn, request.object_type, request.object_ref)
        allowed = False
        reason = "No matching ownership, membership, or authority grant"
        matched_grants: list[str] = []

        if target["scope_type"] == "user" and target["scope_ref"] == request.actor_user_id:
            allowed = True
            reason = "User owns the target scope"
        elif target["scope_type"] == "shared_context":
            context_id = target["scope_ref"]
            if self._active_context_member(conn, context_id, request.actor_user_id):
                allowed = True
                reason = "Actor is an active shared-context member"
            elif request.action == "manage_membership" and actor["primary_user_flag"]:
                allowed = True
                reason = "Primary user may administer shared-context membership"
        elif target["scope_type"] == "agent":
            owner = self._agent_owner_scope(conn, target["scope_ref"])
            if owner["scope_type"] == "user" and owner["scope_ref"] == request.actor_user_id:
                allowed = True
                reason = "Actor owns the agent"
            elif owner["scope_type"] == "shared_context" and self._active_context_member(
                conn, owner["scope_ref"], request.actor_user_id
            ):
                allowed = True
                reason = "Actor is an active member of the agent shared context"
        elif target["scope_type"] == "project":
            owner = self._project_owner_scope(conn, target["scope_ref"])
            if owner["scope_type"] == "user" and owner["scope_ref"] == request.actor_user_id:
                allowed = True
                reason = "Actor owns the project"
            elif owner["scope_type"] == "shared_context" and self._active_context_member(
                conn, owner["scope_ref"], request.actor_user_id
            ):
                allowed = True
                reason = "Actor is an active member of the project shared context"
            elif owner["scope_type"] == "agent":
                agent_owner = self._agent_owner_scope(conn, owner["scope_ref"])
                if agent_owner["scope_type"] == "user" and agent_owner["scope_ref"] == request.actor_user_id:
                    allowed = True
                    reason = "Actor owns the project owner agent"
                elif agent_owner["scope_type"] == "shared_context" and self._active_context_member(
                    conn, agent_owner["scope_ref"], request.actor_user_id
                ):
                    allowed = True
                    reason = "Actor is an active member of the project owner agent context"
            if not allowed and self._active_project_participant_allowed(
                conn, target["scope_ref"], request.actor_user_id, request.action
            ):
                allowed = True
                reason = "Actor is an active project participant with matching permission"

        if not allowed:
            grants = self._matching_grants(conn, request, target)
            if grants:
                allowed = True
                matched_grants = [grant["grant_id"] for grant in grants]
                reason = "Explicit authority grant matched"

        decision = {
            "allowed": allowed,
            "decision": "allow" if allowed else "deny",
            "actor_user_id": request.actor_user_id,
            "action": request.action,
            "object_type": request.object_type,
            "object_ref": request.object_ref,
            "target_scope_type": target["scope_type"],
            "target_scope_ref": target["scope_ref"],
            "rationale": reason,
            "matched_grant_ids": matched_grants,
            "metadata": request.metadata,
        }
        return self._record_decision(conn, decision) if record else decision

    def _matching_grants(self, conn: Any, request: AuthorityRequest, target: dict[str, Any]) -> list[dict[str, Any]]:
        permissions = ACTION_PERMISSIONS[request.action]
        now = self._now()
        scope_candidates = [(target["scope_type"], target["scope_ref"])]
        if target["scope_type"] == "agent":
            owner = self._agent_owner_scope(conn, target["scope_ref"])
            scope_candidates.append((owner["scope_type"], owner["scope_ref"]))
        if target["scope_type"] == "project":
            owner = self._project_owner_scope(conn, target["scope_ref"])
            scope_candidates.append((owner["scope_type"], owner["scope_ref"]))
        matched: list[dict[str, Any]] = []
        for scope_type, scope_ref in scope_candidates:
            rows = conn.execute(
                """
                SELECT * FROM authority_grants
                WHERE grantee_user_id = ?
                  AND scope_type = ?
                  AND scope_ref = ?
                  AND status = 'active'
                  AND effective_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY effective_at DESC, grant_id
                """,
                (request.actor_user_id, scope_type, scope_ref, now, now),
            ).fetchall()
            for row in rows:
                grant = self.store._decode_row(row)
                if permissions.intersection(set(grant.get("permissions_json", []))):
                    matched.append(grant)
        return matched

    def _resolve_object_scope(self, conn: Any, object_type: str, object_ref: str) -> dict[str, str]:
        if object_type == "user":
            self._require_active_user(conn, object_ref)
            return {"scope_type": "user", "scope_ref": object_ref}
        if object_type == "shared_context":
            self._require_shared_context(conn, object_ref)
            return {"scope_type": "shared_context", "scope_ref": object_ref}
        if object_type == "agent":
            row = self.store.get_by_id("agents", object_ref, conn=conn)
            if row is None:
                raise ValueError(f"Agent not found: {object_ref}")
            return {"scope_type": "agent", "scope_ref": object_ref}
        if object_type == "channel_identity":
            row = self.store.get_by_id("channel_identities", object_ref, conn=conn)
            if row is None:
                raise ValueError(f"Channel identity not found: {object_ref}")
            if row.get("user_id"):
                return {"scope_type": "user", "scope_ref": row["user_id"]}
            return {"scope_type": "agent", "scope_ref": row["agent_id"]}
        if object_type == "google_connection":
            row = self.store.get_by_id("google_connections", object_ref, conn=conn)
            if row is None:
                raise ValueError(f"Google connection not found: {object_ref}")
            return {"scope_type": "user", "scope_ref": row["user_id"]}
        if object_type == "google_workspace_action":
            row = self.store.get_by_id("google_workspace_actions", object_ref, conn=conn)
            if row is None:
                raise ValueError(f"Google Workspace action not found: {object_ref}")
            return {"scope_type": "user", "scope_ref": row["google_connection_user_id"] or row["target_user_id"]}
        if object_type == "thread":
            row = self.store.get_by_id("threads", object_ref, conn=conn)
            if row is None:
                raise ValueError(f"Thread not found: {object_ref}")
            return {"scope_type": row["ownership_context_type"], "scope_ref": row["ownership_context_ref"]}
        if object_type in {"artifact", "commitment", "memory_record", "knowledge_corpus"}:
            table = {
                "artifact": "artifacts",
                "commitment": "commitments",
                "memory_record": "memory_records",
                "knowledge_corpus": "knowledge_corpora",
            }[object_type]
            row = self.store.get_by_id(table, object_ref, conn=conn)
            if row is None:
                raise ValueError(f"{object_type} not found: {object_ref}")
            return {"scope_type": row["owner_scope_type"], "scope_ref": row["owner_scope_ref"]}
        if object_type == "project":
            project = self.store.get_by_id("projects", object_ref, conn=conn)
            if project is None:
                raise ValueError(f"Project not found: {object_ref}")
            return {"scope_type": "project", "scope_ref": object_ref}
        raise ValueError(f"Unsupported authority object_type: {object_type}")

    def _agent_owner_scope(self, conn: Any, agent_id: str) -> dict[str, str]:
        agent = self.store.get_by_id("agents", agent_id, conn=conn)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        if agent.get("owner_user_id"):
            return {"scope_type": "user", "scope_ref": agent["owner_user_id"]}
        return {"scope_type": "shared_context", "scope_ref": agent["shared_context_id"]}

    def _project_owner_scope(self, conn: Any, project_id: str) -> dict[str, str]:
        project = self.store.get_by_id("projects", project_id, conn=conn)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")
        return {"scope_type": project["owner_scope_type"], "scope_ref": project["owner_scope_ref"]}

    def _active_project_participant_allowed(
        self, conn: Any, project_id: str, actor_user_id: str, action: str
    ) -> bool:
        project = self.store.get_by_id("projects", project_id, conn=conn)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")
        for participant in project.get("participants_json", []):
            if participant.get("status", "active") != "active":
                continue
            permissions = set(participant.get("permissions", []))
            if not permissions and participant.get("user_id") == actor_user_id:
                permissions = {"read"}
            if "manage_project" in permissions:
                permissions.update(AUTHORITY_ACTIONS)
            if action not in permissions:
                continue
            subject_type = participant.get("subject_type")
            subject_ref = participant.get("subject_ref")
            if participant.get("user_id"):
                subject_type = "user"
                subject_ref = participant["user_id"]
            elif participant.get("agent_id"):
                subject_type = "agent"
                subject_ref = participant["agent_id"]
            if subject_type == "user" and subject_ref == actor_user_id:
                return True
            if subject_type == "agent" and subject_ref:
                owner = self._agent_owner_scope(conn, subject_ref)
                if owner["scope_type"] == "user" and owner["scope_ref"] == actor_user_id:
                    return True
                if owner["scope_type"] == "shared_context" and self._active_context_member(
                    conn, owner["scope_ref"], actor_user_id
                ):
                    return True
        return False

    def _active_context_member(self, conn: Any, shared_context_id: str, user_id: str) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM shared_context_members
            WHERE shared_context_id = ?
              AND member_type = 'user'
              AND member_ref = ?
              AND status = 'active'
            """,
            (shared_context_id, user_id),
        ).fetchone()
        return row is not None

    def _insert_shared_context_member(
        self,
        conn: Any,
        shared_context_id: str,
        member_type: str,
        member_ref: str,
        role: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO shared_context_members (
                shared_context_id, member_type, member_ref, role, status
            )
            VALUES (?, ?, ?, ?, 'active')
            """,
            (shared_context_id, member_type, member_ref, role),
        )
        self.store.append_event(
            "shared_context_member_added",
            "shared_context",
            shared_context_id,
            "user",
            actor_user_id,
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
        return self.store._decode_row(row)

    def _record_decision(self, conn: Any, decision: dict[str, Any]) -> dict[str, Any]:
        policy_decision = self.store.insert(
            "policy_decisions",
            {
                "policy_decision_id": new_id("pdec"),
                "actor_type": "user",
                "actor_ref": decision["actor_user_id"],
                "sponsoring_user_id": decision["actor_user_id"],
                "action_type": f"authority:{decision['action']}",
                "object_type": decision["object_type"],
                "object_ref": decision["object_ref"],
                "destination_type": decision["target_scope_type"],
                "destination_identity": decision["target_scope_ref"],
                "destination_trust_tier": 0,
                "content_classification": "private",
                "applicable_policy_refs_json": decision["matched_grant_ids"],
                "decision": decision["decision"],
                "rationale_summary": decision["rationale"],
            },
            conn=conn,
            emit_event=False,
        )
        audit = self._audit(
            conn,
            "authority_evaluated",
            decision["actor_user_id"],
            decision["object_type"],
            decision["object_ref"],
            f"Authority evaluated {decision['action']} as {decision['decision']}",
            decision["decision"],
            {
                "target_scope_type": decision["target_scope_type"],
                "target_scope_ref": decision["target_scope_ref"],
                "matched_grant_ids": decision["matched_grant_ids"],
                "metadata": decision["metadata"],
            },
            policy_decision_id=policy_decision["policy_decision_id"],
        )
        event_id = self.store.append_event(
            "authority_decision_recorded",
            "policy_decision",
            policy_decision["policy_decision_id"],
            "user",
            decision["actor_user_id"],
            {"decision": decision["decision"], "audit_event_id": audit["audit_event_id"]},
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )
        return {**decision, "policy_decision": policy_decision, "audit_event": audit, "event_id": event_id}

    def _require_active_user(self, conn: Any, user_id: str) -> dict[str, Any]:
        user = self.store.get_by_id("users", user_id, conn=conn)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        if user["status"] != "active":
            raise PermissionError(f"User is not active: {user_id}")
        return user

    def _require_shared_context(self, conn: Any, shared_context_id: str) -> dict[str, Any]:
        context = self.store.get_by_id("shared_contexts", shared_context_id, conn=conn)
        if context is None:
            raise ValueError(f"Shared context not found: {shared_context_id}")
        if context["status"] != "active":
            raise PermissionError(f"Shared context is not active: {shared_context_id}")
        return context

    def _audit(
        self,
        conn: Any,
        event_type: str,
        actor_user_id: str,
        object_type: str,
        object_ref: str,
        summary: str,
        outcome: str,
        metadata: dict[str, Any],
        *,
        policy_decision_id: str | None = None,
    ) -> dict[str, Any]:
        return self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": event_type,
                "actor_type": "user",
                "actor_ref": actor_user_id,
                "object_type": object_type,
                "object_ref": object_ref,
                "action_summary": summary,
                "outcome": outcome,
                "policy_decision_id": policy_decision_id,
                "metadata_json": metadata,
            },
            conn=conn,
            emit_event=False,
        )

    def _now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

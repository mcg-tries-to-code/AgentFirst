"""Bounded V1 project work-management behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .authority import AUTHORITY_ACTIONS, AuthorityEngine, AuthorityRequest
from .store import AgentFirstStore, new_id
from .task_engine import TaskEngine


PARTICIPANT_ROLES = {"owner", "coordinator", "contributor", "observer", "agent"}
PARTICIPANT_STATUSES = {"active", "invited", "removed"}
MILESTONE_STATUSES = {"planned", "active", "completed", "blocked", "canceled"}


class ProjectWorkService:
    """Operational project container layer over canonical V1 records."""

    def __init__(self, store: AgentFirstStore, authority: AuthorityEngine | None = None):
        self.store = store
        self.authority = authority or AuthorityEngine(store)
        self.tasks = TaskEngine(store)

    def create_project(
        self,
        *,
        name: str,
        owner_scope_type: str,
        owner_scope_ref: str,
        actor_user_id: str,
        description_ref: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        goals: list[str] | None = None,
        milestones: list[dict[str, Any]] | None = None,
        policy_refs: list[str] | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            self._validate_project_owner(conn, owner_scope_type, owner_scope_ref)
            self._require_owner_authority(conn, actor_user_id, owner_scope_type, owner_scope_ref)
            normalized_participants = [
                self._normalize_participant(conn, item, actor_user_id) for item in (participants or [])
            ]
            if owner_scope_type == "user" and not any(
                item["subject_type"] == "user" and item["subject_ref"] == owner_scope_ref
                for item in normalized_participants
            ):
                normalized_participants.insert(
                    0,
                    self._normalize_participant(
                        conn,
                        {
                            "subject_type": "user",
                            "subject_ref": owner_scope_ref,
                            "role": "owner",
                            "permissions": ["read", "monitor", "intervene", "approve", "manage_membership"],
                        },
                        actor_user_id,
                    ),
                )
            normalized_milestones = [
                self._normalize_milestone(item, actor_user_id) for item in (milestones or [])
            ]
            self._require_policies(conn, policy_refs or [])
            project = self.store.insert(
                "projects",
                {
                    "project_id": new_id("proj"),
                    "name": name,
                    "description_ref": description_ref,
                    "owner_scope_type": owner_scope_type,
                    "owner_scope_ref": owner_scope_ref,
                    "participants_json": normalized_participants,
                    "goals_json": goals or [],
                    "milestones_json": normalized_milestones,
                    "policy_refs_json": policy_refs or [],
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self._audit(
                conn,
                "project_created",
                actor_user_id,
                project["project_id"],
                "Created bounded V1 project container",
                "created",
                {
                    "owner_scope_type": owner_scope_type,
                    "owner_scope_ref": owner_scope_ref,
                    "participant_count": len(normalized_participants),
                    "milestone_count": len(normalized_milestones),
                    "policy_refs": policy_refs or [],
                },
            )
            self.store.append_event(
                "project_work_container_created",
                "project",
                project["project_id"],
                "user",
                actor_user_id,
                {"audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return project

    def add_participant(
        self,
        project_id: str,
        *,
        participant: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            self._require_project_permission(project_id, actor_user_id, "manage_membership")
            project = self._require_project(conn, project_id)
            normalized = self._normalize_participant(conn, participant, actor_user_id)
            participants = [
                item
                for item in project.get("participants_json", [])
                if not (
                    item.get("subject_type") == normalized["subject_type"]
                    and item.get("subject_ref") == normalized["subject_ref"]
                )
            ]
            participants.append(normalized)
            updated = self.store.update(
                "projects",
                project_id,
                {"participants_json": participants},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self._audit(
                conn,
                "project_participant_added",
                actor_user_id,
                project_id,
                "Added project participant",
                "updated",
                normalized,
            )
            self.store.append_event(
                "project_participant_added",
                "project",
                project_id,
                "user",
                actor_user_id,
                {"participant": normalized},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return updated

    def add_milestone(
        self,
        project_id: str,
        *,
        title: str,
        actor_user_id: str,
        due_at: str | None = None,
        owner_participant_ref: str | None = None,
        artifact_refs: list[str] | None = None,
        commitment_refs: list[str] | None = None,
        policy_refs: list[str] | None = None,
        status: str = "planned",
    ) -> dict[str, Any]:
        if status not in MILESTONE_STATUSES:
            raise ValueError(f"Unsupported milestone status: {status}")
        with self.store.connect() as conn:
            self._require_project_permission(project_id, actor_user_id, "intervene")
            project = self._require_project(conn, project_id)
            self._require_policies(conn, policy_refs or [])
            milestone = {
                "milestone_id": new_id("mile"),
                "title": title,
                "status": status,
                "due_at": due_at,
                "owner_participant_ref": owner_participant_ref,
                "artifact_refs": artifact_refs or [],
                "commitment_refs": commitment_refs or [],
                "policy_refs": policy_refs or [],
                "created_by_user_id": actor_user_id,
                "created_at": self._now(),
            }
            milestones = list(project.get("milestones_json", []))
            milestones.append(milestone)
            self.store.update(
                "projects",
                project_id,
                {"milestones_json": milestones},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            progress = self.store.insert(
                "progress_updates",
                {
                    "progress_update_id": new_id("prog"),
                    "parent_type": "project",
                    "parent_ref": project_id,
                    "author_user_id": actor_user_id,
                    "summary": f"Milestone added: {title}",
                    "state_change_json": {"milestone": milestone},
                    "visibility_policy_refs_json": policy_refs or [],
                    "status": "posted",
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self._audit(
                conn,
                "project_milestone_added",
                actor_user_id,
                project_id,
                "Added project milestone",
                "updated",
                {"milestone_id": milestone["milestone_id"], "progress_update_id": progress["progress_update_id"]},
            )
            self.store.append_event(
                "project_milestone_added",
                "project",
                project_id,
                "user",
                actor_user_id,
                {"milestone_id": milestone["milestone_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return milestone

    def link_artifact(
        self,
        project_id: str,
        artifact_id: str,
        *,
        actor_user_id: str,
        link_reason: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            self._require_project_permission(project_id, actor_user_id, "intervene")
            artifact_decision = self.authority.evaluate(
                AuthorityRequest(actor_user_id, "read", "artifact", artifact_id, {"project_id": project_id})
            )
            if not artifact_decision["allowed"]:
                raise PermissionError(artifact_decision["rationale"])
            artifact = self._require_artifact(conn, artifact_id)
            project_refs = list(artifact.get("project_refs_json", []))
            if project_id not in project_refs:
                project_refs.append(project_id)
            provenance = dict(artifact.get("provenance_json", {}))
            provenance.setdefault("project_links", []).append(
                {"project_id": project_id, "linked_by_user_id": actor_user_id, "reason": link_reason}
            )
            updated = self.store.update(
                "artifacts",
                artifact_id,
                {"project_refs_json": project_refs, "provenance_json": provenance},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self._audit(
                conn,
                "project_artifact_linked",
                actor_user_id,
                project_id,
                "Linked artifact to project",
                "updated",
                {"artifact_id": artifact_id, "link_reason": link_reason},
            )
            self.store.append_event(
                "project_artifact_linked",
                "project",
                project_id,
                "user",
                actor_user_id,
                {"artifact_id": artifact_id, "audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return updated

    def create_project_commitment(
        self,
        project_id: str,
        *,
        title: str,
        commitment_type: str,
        actor_user_id: str,
        next_action: str | None = None,
        due_at: str | None = None,
        review_at: str | None = None,
        completion_criteria: dict[str, Any] | None = None,
        policy_refs: list[str] | None = None,
        priority: int = 3,
    ) -> dict[str, Any]:
        self._require_project_permission(project_id, actor_user_id, "intervene")
        with self.store.connect() as conn:
            project = self._require_project(conn, project_id)
            self._require_policies(conn, policy_refs or [])
            merged_policy_refs = list(dict.fromkeys(project.get("policy_refs_json", []) + (policy_refs or [])))
        commitment = self.tasks.create_commitment(
            title=title,
            commitment_type=commitment_type,
            owner_scope_type="project",
            owner_scope_ref=project_id,
            project_id=project_id,
            priority=priority,
            next_action=next_action,
            due_at=due_at,
            review_at=review_at,
            completion_criteria=completion_criteria,
            policy_refs=merged_policy_refs,
            actor_type="user",
            actor_ref=actor_user_id,
        )
        with self.store.connect() as conn:
            audit = self._audit(
                conn,
                "project_commitment_created",
                actor_user_id,
                project_id,
                "Created project-owned commitment",
                "created",
                {"commitment_id": commitment["commitment_id"], "policy_refs": merged_policy_refs},
            )
            self.store.append_event(
                "project_commitment_created",
                "project",
                project_id,
                "user",
                actor_user_id,
                {"commitment_id": commitment["commitment_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
        return commitment

    def attach_policy(self, project_id: str, policy_id: str, *, actor_user_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            self._require_project_permission(project_id, actor_user_id, "approve")
            self._require_policies(conn, [policy_id])
            project = self._require_project(conn, project_id)
            refs = list(project.get("policy_refs_json", []))
            if policy_id not in refs:
                refs.append(policy_id)
            updated = self.store.update(
                "projects",
                project_id,
                {"policy_refs_json": refs},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self._audit(
                conn,
                "project_policy_attached",
                actor_user_id,
                project_id,
                "Attached policy to project",
                "updated",
                {"policy_id": policy_id},
            )
            self.store.append_event(
                "project_policy_attached",
                "project",
                project_id,
                "user",
                actor_user_id,
                {"policy_id": policy_id},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return updated

    def get_project_work_bundle(self, project_id: str, *, actor_user_id: str) -> dict[str, Any]:
        decision = self.authority.evaluate(AuthorityRequest(actor_user_id, "read", "project", project_id))
        if not decision["allowed"]:
            raise PermissionError(decision["rationale"])
        with self.store.connect() as conn:
            project = self._require_project(conn, project_id)
            artifacts = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM artifacts
                    WHERE owner_scope_type = 'project'
                       OR project_refs_json LIKE ?
                    ORDER BY created_at, artifact_id
                    """,
                    (f"%{project_id}%",),
                ).fetchall()
                if row["owner_scope_ref"] == project_id or project_id in self.store._decode_row(row)["project_refs_json"]
            ]
            commitments = [
                self.store._decode_row(row)
                for row in conn.execute(
                    "SELECT * FROM commitments WHERE project_id = ? ORDER BY created_at, commitment_id",
                    (project_id,),
                ).fetchall()
            ]
            progress = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM progress_updates
                    WHERE parent_type = 'project' AND parent_ref = ?
                    ORDER BY timestamp, progress_update_id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            return {
                "project": project,
                "participants": project.get("participants_json", []),
                "milestones": project.get("milestones_json", []),
                "artifacts": artifacts,
                "commitments": commitments,
                "progress_updates": progress,
                "authority_policy_decision_id": decision["policy_decision"]["policy_decision_id"],
            }

    def _require_project_permission(self, project_id: str, actor_user_id: str, action: str) -> None:
        decision = self.authority.evaluate(AuthorityRequest(actor_user_id, action, "project", project_id))
        if not decision["allowed"]:
            raise PermissionError(decision["rationale"])

    def _normalize_participant(
        self, conn: Any, participant: dict[str, Any], actor_user_id: str
    ) -> dict[str, Any]:
        subject_type = participant.get("subject_type")
        subject_ref = participant.get("subject_ref")
        if participant.get("user_id"):
            subject_type = "user"
            subject_ref = participant["user_id"]
        elif participant.get("agent_id"):
            subject_type = "agent"
            subject_ref = participant["agent_id"]
        if subject_type not in {"user", "agent"} or not subject_ref:
            raise ValueError("Project participant requires subject_type/subject_ref or user_id/agent_id")
        if subject_type == "user":
            user = self.store.get_by_id("users", subject_ref, conn=conn)
            if user is None or user["status"] != "active":
                raise ValueError(f"Active participant user not found: {subject_ref}")
        if subject_type == "agent":
            agent = self.store.get_by_id("agents", subject_ref, conn=conn)
            if agent is None or agent["status"] != "active":
                raise ValueError(f"Active participant agent not found: {subject_ref}")
        role = participant.get("role", "contributor")
        if role not in PARTICIPANT_ROLES:
            raise ValueError(f"Unsupported project participant role: {role}")
        status = participant.get("status", "active")
        if status not in PARTICIPANT_STATUSES:
            raise ValueError(f"Unsupported project participant status: {status}")
        permissions = participant.get("permissions")
        if permissions is None:
            permissions = {
                "owner": ["read", "monitor", "intervene", "approve", "manage_membership"],
                "coordinator": ["read", "monitor", "intervene", "approve"],
                "contributor": ["read", "monitor", "intervene"],
                "observer": ["read"],
                "agent": ["read", "monitor", "intervene"],
            }[role]
        unknown = set(permissions) - (AUTHORITY_ACTIONS | {"manage_project"})
        if unknown:
            raise ValueError(f"Unsupported project participant permission(s): {sorted(unknown)}")
        normalized = {
            "participant_id": participant.get("participant_id", new_id("part")),
            "subject_type": subject_type,
            "subject_ref": subject_ref,
            "role": role,
            "permissions": list(dict.fromkeys(permissions)),
            "status": status,
            "policy_refs": participant.get("policy_refs", []),
            "added_by_user_id": participant.get("added_by_user_id", actor_user_id),
            "added_at": participant.get("added_at", self._now()),
        }
        self._require_policies(conn, normalized["policy_refs"])
        return normalized

    def _normalize_milestone(self, milestone: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        status = milestone.get("status", "planned")
        if status not in MILESTONE_STATUSES:
            raise ValueError(f"Unsupported milestone status: {status}")
        if not milestone.get("title"):
            raise ValueError("Project milestone requires a title")
        return {
            "milestone_id": milestone.get("milestone_id", new_id("mile")),
            "title": milestone["title"],
            "status": status,
            "due_at": milestone.get("due_at"),
            "owner_participant_ref": milestone.get("owner_participant_ref"),
            "artifact_refs": milestone.get("artifact_refs", []),
            "commitment_refs": milestone.get("commitment_refs", []),
            "policy_refs": milestone.get("policy_refs", []),
            "created_by_user_id": milestone.get("created_by_user_id", actor_user_id),
            "created_at": milestone.get("created_at", self._now()),
        }

    def _require_owner_authority(
        self, conn: Any, actor_user_id: str, owner_scope_type: str, owner_scope_ref: str
    ) -> None:
        if owner_scope_type == "user" and owner_scope_ref == actor_user_id:
            return
        object_type = {"user": "user", "shared_context": "shared_context", "agent": "agent"}[owner_scope_type]
        action = "manage_membership" if owner_scope_type == "shared_context" else "intervene"
        decision = self.authority.evaluate(AuthorityRequest(actor_user_id, action, object_type, owner_scope_ref))
        if not decision["allowed"]:
            raise PermissionError(decision["rationale"])

    def _validate_project_owner(self, conn: Any, owner_scope_type: str, owner_scope_ref: str) -> None:
        table = {"user": "users", "agent": "agents", "shared_context": "shared_contexts"}.get(owner_scope_type)
        if table is None:
            raise ValueError("Project owner_scope_type must be user, agent, or shared_context")
        row = self.store.get_by_id(table, owner_scope_ref, conn=conn)
        if row is None:
            raise ValueError(f"Project owner not found: {owner_scope_type}:{owner_scope_ref}")
        if row.get("status") != "active":
            raise ValueError(f"Project owner is not active: {owner_scope_type}:{owner_scope_ref}")

    def _require_project(self, conn: Any, project_id: str) -> dict[str, Any]:
        project = self.store.get_by_id("projects", project_id, conn=conn)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")
        return project

    def _require_artifact(self, conn: Any, artifact_id: str) -> dict[str, Any]:
        artifact = self.store.get_by_id("artifacts", artifact_id, conn=conn)
        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")
        return artifact

    def _require_policies(self, conn: Any, policy_refs: list[str]) -> None:
        for policy_id in policy_refs:
            policy = self.store.get_by_id("policies", policy_id, conn=conn)
            if policy is None or policy["status"] != "active":
                raise ValueError(f"Active policy not found: {policy_id}")

    def _audit(
        self,
        conn: Any,
        event_type: str,
        actor_user_id: str,
        project_id: str,
        summary: str,
        outcome: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": event_type,
                "actor_type": "user",
                "actor_ref": actor_user_id,
                "object_type": "project",
                "object_ref": project_id,
                "action_summary": summary,
                "outcome": outcome,
                "metadata_json": metadata,
            },
            conn=conn,
            emit_event=False,
        )

    def _now(self) -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

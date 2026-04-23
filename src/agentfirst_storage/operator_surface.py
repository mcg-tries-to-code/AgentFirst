"""Trusted local operator surface for bounded V1 administration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .store import AgentFirstStore, new_id


READ_ONLY_VIEWS = {"status", "approvals", "audit", "users", "user.detail", "tasks", "failures", "inbox"}
ADMIN_ACTIONS = {"approval.resolve", "user.create", "user.suspend", "user.reactivate"}
FAILURE_OUTCOMES = {"deny", "denied", "failed", "policy_denied", "authority_denied"}
FAILURE_STATUSES = {
    "failed",
    "blocked",
    "authority_denied",
    "policy_denied",
    "denied",
    "revoked",
    "suspended",
    "rebinding_required",
}


@dataclass(frozen=True)
class OperatorCommandResult:
    """Rendered TUI command result."""

    mode: str
    title: str
    text: str
    data: dict[str, Any]


class OperatorSurface:
    """Read-only inspection and explicit admin actions over trusted local state."""

    def __init__(self, store: AgentFirstStore):
        self.store = store

    def status_overview(self) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            counts = {
                table: self._count(conn, table)
                for table in [
                    "users",
                    "channel_identities",
                    "channel_enrollments",
                    "approval_records",
                    "audit_events",
                    "event_log",
                    "projects",
                    "commitments",
                    "tool_invocations",
                    "google_workspace_actions",
                    "model_route_decisions",
                ]
            }
            open_approvals = self._count_where(conn, "approval_records", "status = 'requested'")
            active_projects = self._count_where(conn, "projects", "status = 'active'")
            active_commitments = self._count_where(conn, "commitments", "status = 'active'")
            waiting_commitments = self._count_where(conn, "commitments", "status = 'waiting'")
            blocked_commitments = self._count_where(conn, "commitments", "status = 'blocked'")
            failure_disclosures = self.failure_disclosures(limit=12)
            return {
                "operator_surface": "bounded_v1_trusted_local_tui",
                "read_only_views": sorted(READ_ONLY_VIEWS),
                "admin_actions": sorted(ADMIN_ACTIONS),
                "counts": counts,
                "work": {
                    "active_projects": active_projects,
                    "active_commitments": active_commitments,
                    "waiting_commitments": waiting_commitments,
                    "blocked_commitments": blocked_commitments,
                },
                "approvals": {"open": open_approvals},
                "failure_disclosure_count": len(failure_disclosures),
                "failure_disclosures": failure_disclosures,
            }

    def approvals(self, limit: int = 25) -> list[dict[str, Any]]:
        self.store.initialize()
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ar.*,
                    pd.action_type,
                    pd.object_type,
                    pd.object_ref,
                    pd.destination_type,
                    pd.destination_identity,
                    pd.content_classification,
                    pd.decision,
                    pd.rationale_summary
                FROM approval_records ar
                JOIN policy_decisions pd ON pd.policy_decision_id = ar.policy_decision_id
                ORDER BY
                    CASE ar.status WHEN 'requested' THEN 0 ELSE 1 END,
                    ar.requested_at DESC,
                    ar.approval_record_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self.store._decode_row(row) for row in rows]

    def audit_events(self, limit: int = 25) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            audit_rows = conn.execute(
                """
                SELECT * FROM audit_events
                ORDER BY created_at DESC, audit_event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            event_rows = conn.execute(
                """
                SELECT * FROM event_log
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return {
                "audit_events": [self.store._decode_row(row) for row in audit_rows],
                "event_log": [self.store._decode_row(row) for row in event_rows],
            }

    def users_channels_enrollments(self, limit: int = 50) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            raw_users = [
                self.store._decode_row(row)
                for row in conn.execute(
                    "SELECT * FROM users ORDER BY primary_user_flag DESC, display_name, user_id LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
            users = [self._user_summary(conn, user) for user in raw_users]
            identities = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT ci.*, u.display_name AS user_display_name
                    FROM channel_identities ci
                    LEFT JOIN users u ON u.user_id = ci.user_id
                    ORDER BY ci.channel_type, ci.address, ci.channel_identity_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            enrollments = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT ce.*, u.display_name AS user_display_name
                    FROM channel_enrollments ce
                    LEFT JOIN users u ON u.user_id = ce.user_id
                    ORDER BY
                        CASE ce.state
                            WHEN 'awaiting_owner_approval' THEN 0
                            WHEN 'pairing_requested' THEN 1
                            WHEN 'challenge_issued' THEN 2
                            WHEN 'enrolled' THEN 3
                            ELSE 4
                        END,
                        ce.updated_at DESC,
                        ce.enrollment_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            degraded_users = [user for user in users if user["badges"]]
            return {
                "users": users,
                "channel_identities": identities,
                "channel_enrollments": enrollments,
                "degraded_users": degraded_users,
            }

    def user_detail(self, user_id: str, audit_limit: int = 10) -> dict[str, Any]:
        """Read one user and related authority/channel state without mutation."""
        self.store.initialize()
        with self.store.connect() as conn:
            user = self.store.get_by_id("users", user_id, conn=conn)
            if user is None:
                raise ValueError(f"User not found: {user_id}")
            summary = self._user_summary(conn, user)
            identities = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM channel_identities
                    WHERE user_id = ?
                    ORDER BY channel_type, address, channel_identity_id
                    """,
                    (user_id,),
                ).fetchall()
            ]
            enrollments = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM channel_enrollments
                    WHERE user_id = ?
                    ORDER BY
                        CASE state
                            WHEN 'awaiting_owner_approval' THEN 0
                            WHEN 'pairing_requested' THEN 1
                            WHEN 'challenge_issued' THEN 2
                            WHEN 'enrolled' THEN 3
                            ELSE 4
                        END,
                        updated_at DESC,
                        enrollment_id
                    """,
                    (user_id,),
                ).fetchall()
            ]
            grants_received = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM authority_grants
                    WHERE grantee_user_id = ?
                    ORDER BY status, effective_at DESC, grant_id
                    """,
                    (user_id,),
                ).fetchall()
            ]
            grants_given = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM authority_grants
                    WHERE grantor_user_id = ?
                    ORDER BY status, effective_at DESC, grant_id
                    """,
                    (user_id,),
                ).fetchall()
            ]
            recent_audit = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM audit_events
                    WHERE object_type = 'user' AND object_ref = ?
                       OR actor_type = 'user' AND actor_ref = ?
                    ORDER BY created_at DESC, audit_event_id DESC
                    LIMIT ?
                    """,
                    (user_id, user_id, audit_limit),
                ).fetchall()
            ]
            degraded_bindings = self._user_degraded_bindings(user, identities, enrollments)
            return {
                "user": summary,
                "profile": user,
                "authority": {
                    "effective_tier": user["authority_tier"],
                    "primary_user": bool(user["primary_user_flag"]),
                    "grants_received": grants_received,
                    "grants_given": grants_given,
                    "active_grants_received": [grant for grant in grants_received if grant["status"] == "active"],
                    "active_grants_given": [grant for grant in grants_given if grant["status"] == "active"],
                },
                "channel_identities": identities,
                "channel_enrollments": enrollments,
                "degraded_bindings": degraded_bindings,
                "recent_audit": recent_audit,
                "read_only": True,
            }

    def tasks_projects(self, limit: int = 50) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            projects = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM projects
                    ORDER BY
                        CASE status WHEN 'active' THEN 0 ELSE 1 END,
                        updated_at DESC,
                        project_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            commitments = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM commitments
                    ORDER BY
                        CASE status
                            WHEN 'blocked' THEN 0
                            WHEN 'waiting' THEN 1
                            WHEN 'active' THEN 2
                            ELSE 3
                        END,
                        COALESCE(review_at, due_at, created_at) ASC,
                        commitment_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            blockers = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM blocker_records
                    ORDER BY
                        CASE status WHEN 'active' THEN 0 ELSE 1 END,
                        opened_at DESC,
                        blocker_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            return {"projects": projects, "commitments": commitments, "blockers": blockers}

    def inbox_threads(self, limit: int = 25) -> dict[str, Any]:
        """Read the bounded local inbox from canonical thread/message state."""
        self.store.initialize()
        with self.store.connect() as conn:
            threads = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM threads
                    ORDER BY updated_at DESC, created_at DESC, thread_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            items = [self._inbox_item(conn, thread) for thread in threads]
        items.sort(key=lambda item: item.get("last_activity_at") or item.get("created_at") or "", reverse=True)
        return {
            "disclosure": self._inbox_disclosure(),
            "threads": items,
            "empty": not items,
            "derived_fields": ["review_needed", "badges", "summary", "sendable"],
        }

    def inbox_thread_detail(self, thread_id: str, limit: int = 50) -> dict[str, Any]:
        """Read one local inbox thread without writing audit or event rows."""
        self.store.initialize()
        with self.store.connect() as conn:
            thread = self.store.get_by_id("threads", thread_id, conn=conn)
            if thread is None:
                raise ValueError(f"Inbox thread not found: {thread_id}")
            item = self._inbox_item(conn, thread)
            messages = [
                self.store._decode_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE thread_id = ?
                    ORDER BY timestamp ASC, message_event_id ASC
                    LIMIT ?
                    """,
                    (thread_id, limit),
                ).fetchall()
            ]
            commitments = self._thread_commitments(conn, thread)
            approvals = self._thread_approvals(conn, thread)
            lanes = self._thread_lanes(conn, thread)
            timeline = [self._message_summary(message) for message in messages]
        return {
            "disclosure": self._inbox_disclosure(),
            "thread": item,
            "messages": timeline,
            "messages_empty": not timeline,
            "commitments": commitments,
            "approvals": approvals,
            "lanes": lanes,
            "drafts": [message for message in timeline if message["local_draft"]],
        }

    def create_user_admin(
        self,
        *,
        actor_user_id: str,
        display_name: str,
        authority_tier: str = "standard",
        default_timezone: str = "UTC",
        confirmation: str,
    ) -> dict[str, Any]:
        """Create a non-primary user through the explicit trusted admin surface."""
        if confirmation != "CREATE_USER":
            raise PermissionError("Consequential admin action requires --confirm CREATE_USER")
        if not display_name.strip():
            raise ValueError("User display name is required")
        if authority_tier == "administrator":
            raise PermissionError("This bounded UX does not create administrator users")
        self.store.initialize()
        with self.store.connect() as conn:
            actor = self._require_primary_operator(conn, actor_user_id)
            created = self.store.create_user(
                display_name=display_name.strip(),
                authority_tier=authority_tier,
                primary_user=False,
                default_timezone=default_timezone,
                metadata={"created_by_surface": "trusted_local_tui"},
                actor_type="user",
                actor_ref=actor["user_id"],
                conn=conn,
            )
            audit = self._operator_user_audit(
                conn,
                "operator_user_created",
                actor["user_id"],
                created["user_id"],
                f"Trusted local operator created user {created['display_name']}",
                "created",
                {
                    "operator_surface": "trusted_local_tui",
                    "confirmation": confirmation,
                    "authority_tier": authority_tier,
                    "primary_user": False,
                },
            )
            event_id = self.store.append_event(
                "operator_user_created",
                "user",
                created["user_id"],
                "user",
                actor["user_id"],
                {"audit_event_id": audit["audit_event_id"], "authority_tier": authority_tier},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return {"user": created, "audit_event": audit, "event_id": event_id}

    def suspend_user_admin(self, user_id: str, *, actor_user_id: str, confirmation: str) -> dict[str, Any]:
        return self._set_user_status_admin(
            user_id,
            actor_user_id=actor_user_id,
            confirmation=confirmation,
            expected_confirmation="SUSPEND_USER",
            new_status="suspended",
            event_type="operator_user_suspended",
            outcome="suspended",
        )

    def reactivate_user_admin(self, user_id: str, *, actor_user_id: str, confirmation: str) -> dict[str, Any]:
        return self._set_user_status_admin(
            user_id,
            actor_user_id=actor_user_id,
            confirmation=confirmation,
            expected_confirmation="REACTIVATE_USER",
            new_status="active",
            event_type="operator_user_reactivated",
            outcome="reactivated",
        )

    def failure_disclosures(self, limit: int = 25) -> list[dict[str, Any]]:
        self.store.initialize()
        disclosures: list[dict[str, Any]] = []
        with self.store.connect() as conn:
            disclosures.extend(self._audit_failures(conn, limit))
            disclosures.extend(self._status_failures(conn, "commitments", "commitment_id", "title", limit))
            disclosures.extend(self._status_failures(conn, "tool_invocations", "tool_invocation_id", "operation", limit))
            disclosures.extend(
                self._status_failures(conn, "google_workspace_actions", "google_workspace_action_id", "operation", limit)
            )
            disclosures.extend(
                self._status_failures(conn, "model_route_decisions", "model_route_decision_id", "purpose", limit)
            )
            disclosures.extend(
                self._status_failures(conn, "channel_identities", "channel_identity_id", "address", limit)
            )
            disclosures.extend(
                self._status_failures(conn, "channel_enrollments", "enrollment_id", "address", limit)
            )
        disclosures.sort(key=lambda item: item.get("observed_at") or "", reverse=True)
        return disclosures[:limit]

    def _inbox_item(self, conn: Any, thread: dict[str, Any]) -> dict[str, Any]:
        latest_row = conn.execute(
            """
            SELECT * FROM messages
            WHERE thread_id = ?
            ORDER BY timestamp DESC, message_event_id DESC
            LIMIT 1
            """,
            (thread["thread_id"],),
        ).fetchone()
        message_count = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE thread_id = ?",
                (thread["thread_id"],),
            ).fetchone()["n"]
        )
        draft_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM messages
                WHERE thread_id = ? AND direction = 'outbound'
                  AND status IN ('drafted', 'draft', 'local_draft', 'awaiting_approval', 'pending_approval')
                """,
                (thread["thread_id"],),
            ).fetchone()["n"]
        )
        latest = self.store._decode_row(latest_row) if latest_row else None
        approvals = self._thread_approvals(conn, thread)
        degraded = self._thread_degraded_bindings(conn, thread)
        commitments = self._thread_commitments(conn, thread)
        sendable = self._thread_sendable(thread, degraded)
        badges = ["LOCAL-MIRROR"]
        if not sendable:
            badges.append("UNSENDABLE")
        if approvals:
            badges.append("APPROVAL-GATED")
        if degraded:
            badges.append("ENROLLMENT-DEGRADED")
        if draft_count:
            badges.append("LOCAL-DRAFT")
        if message_count == 0:
            badges.append("EMPTY")
        label = self._thread_label(thread)
        summary = self._message_preview(latest) if latest else "No stored messages in this local thread."
        return {
            "thread_id": thread["thread_id"],
            "label": label,
            "owner_scope": f"{thread['ownership_context_type']}:{thread['ownership_context_ref']}",
            "channel_type": thread["channel_type"],
            "visibility_model": thread["visibility_model"],
            "status": thread["status"],
            "created_at": thread["created_at"],
            "updated_at": thread["updated_at"],
            "last_activity_at": latest["timestamp"] if latest else thread["updated_at"],
            "message_count": message_count,
            "summary": summary,
            "badges": badges,
            "review_needed": bool(approvals or degraded or draft_count or not sendable),
            "sendable": sendable,
            "local_draft_count": draft_count,
            "approval_count": len(approvals),
            "degraded_binding_count": len(degraded),
            "linked_commitment_count": len(commitments),
            "degraded_bindings": degraded,
        }

    def _thread_label(self, thread: dict[str, Any]) -> str:
        for participant in thread.get("participants_json", []):
            for key in ["destination_identity", "telegram_chat_id", "imessage_chat_guid", "channel_identity_id", "agent_id"]:
                if participant.get(key):
                    return f"{thread['channel_type']}:{participant[key]}"
        return f"{thread['channel_type']}:{thread['thread_id']}"

    def _thread_sendable(self, thread: dict[str, Any], degraded: list[dict[str, Any]]) -> bool:
        if thread.get("status") != "active":
            return False
        if thread.get("visibility_model") == "monitored":
            return False
        if degraded:
            return False
        participants = thread.get("participants_json", [])
        for participant in participants:
            if participant.get("telegram_thread_mode") == "monitored":
                return False
            if participant.get("telegram_thread_behavior") == "monitor_only":
                return False
        return True

    def _thread_degraded_bindings(self, conn: Any, thread: dict[str, Any]) -> list[dict[str, Any]]:
        degraded = []
        seen: set[str] = set()
        for participant in thread.get("participants_json", []):
            identity_id = participant.get("channel_identity_id")
            if not identity_id or identity_id in seen:
                continue
            seen.add(identity_id)
            identity = self.store.get_by_id("channel_identities", identity_id, conn=conn)
            if identity is None:
                degraded.append(
                    {
                        "channel_identity_id": identity_id,
                        "state": "missing_identity",
                        "status": "missing",
                        "reason": "thread participant references a missing channel identity",
                    }
                )
                continue
            enrollment = None
            if identity.get("enrollment_id"):
                enrollment = self.store.get_by_id("channel_enrollments", identity["enrollment_id"], conn=conn)
            reasons = []
            if not identity.get("user_id"):
                reasons.append("user_binding_incomplete")
            if identity.get("status") not in {"active", "legacy_active"}:
                reasons.append(f"identity_status:{identity.get('status')}")
            if identity.get("enrollment_state") not in {"enrolled", "legacy_active"}:
                reasons.append(f"identity_enrollment_state:{identity.get('enrollment_state')}")
            if enrollment is None and identity.get("enrollment_id"):
                reasons.append("missing_enrollment")
            if enrollment:
                if enrollment.get("status") not in {"active"}:
                    reasons.append(f"enrollment_status:{enrollment.get('status')}")
                if enrollment.get("state") not in {"enrolled"}:
                    reasons.append(f"enrollment_state:{enrollment.get('state')}")
            if reasons:
                degraded.append(
                    {
                        "channel_identity_id": identity_id,
                        "channel_type": identity.get("channel_type"),
                        "address": identity.get("address"),
                        "user_id": identity.get("user_id"),
                        "enrollment_id": identity.get("enrollment_id"),
                        "state": identity.get("enrollment_state"),
                        "status": identity.get("status"),
                        "reasons": reasons,
                    }
                )
        return degraded

    def _thread_approvals(self, conn: Any, thread: dict[str, Any]) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                ar.*,
                pd.action_type,
                pd.object_type,
                pd.object_ref,
                pd.destination_type,
                pd.destination_identity,
                pd.decision,
                pd.rationale_summary
            FROM approval_records ar
            JOIN policy_decisions pd ON pd.policy_decision_id = ar.policy_decision_id
            WHERE ar.status = 'requested'
            ORDER BY ar.requested_at DESC, ar.approval_record_id
            """
        ).fetchall()
        approvals = []
        linked_commitments = set(thread.get("linked_commitment_ids_json", []))
        message_ids = {
            row["message_event_id"]
            for row in conn.execute("SELECT message_event_id FROM messages WHERE thread_id = ?", (thread["thread_id"],)).fetchall()
        }
        for row in rows:
            approval = self.store._decode_row(row)
            object_type = approval.get("object_type")
            object_ref = approval.get("object_ref")
            scope = approval.get("scope_json") or {}
            scope_text = json.dumps(scope, sort_keys=True)
            applies = (
                (object_type == "thread" and object_ref == thread["thread_id"])
                or (object_type == "message" and object_ref in message_ids)
                or (object_type == "commitment" and object_ref in linked_commitments)
                or scope.get("thread_id") == thread["thread_id"]
                or thread["thread_id"] in scope_text
            )
            if applies:
                approvals.append(approval)
        return approvals

    def _thread_commitments(self, conn: Any, thread: dict[str, Any]) -> list[dict[str, Any]]:
        linked = list(thread.get("linked_commitment_ids_json", []))
        commitments = []
        for commitment_id in linked:
            commitment = self.store.get_by_id("commitments", commitment_id, conn=conn)
            if commitment is not None:
                commitments.append(commitment)
        rows = conn.execute(
            """
            SELECT DISTINCT c.* FROM commitments c
            JOIN messages m ON m.message_event_id = c.origin_ref
            WHERE m.thread_id = ? AND c.origin_ref_type = 'message'
            ORDER BY c.updated_at DESC, c.commitment_id
            """,
            (thread["thread_id"],),
        ).fetchall()
        seen = {commitment["commitment_id"] for commitment in commitments}
        for row in rows:
            commitment = self.store._decode_row(row)
            if commitment["commitment_id"] not in seen:
                commitments.append(commitment)
        return commitments

    def _thread_lanes(self, conn: Any, thread: dict[str, Any]) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM conversation_lanes
            WHERE owner_scope_type = ? AND owner_scope_ref = ?
            ORDER BY status, updated_at DESC, lane_id
            LIMIT 10
            """,
            (thread["ownership_context_type"], thread["ownership_context_ref"]),
        ).fetchall()
        return [self.store._decode_row(row) for row in rows]

    def _message_summary(self, message: dict[str, Any]) -> dict[str, Any]:
        local_draft = message.get("direction") == "outbound" and message.get("status") in {
            "drafted",
            "draft",
            "local_draft",
            "awaiting_approval",
            "pending_approval",
        }
        return {
            "message_event_id": message["message_event_id"],
            "thread_id": message["thread_id"],
            "direction": message["direction"],
            "role_label": self._message_role_label(message),
            "status": message["status"],
            "timestamp": message["timestamp"],
            "classification": message["classification"],
            "content_ref": message["content_ref"],
            "preview": self._message_preview(message),
            "local_draft": local_draft,
            "delivered": False if local_draft else None,
            "provenance": message.get("provenance_json") or {},
        }

    def _message_role_label(self, message: dict[str, Any]) -> str:
        if message.get("direction") == "inbound":
            return "INBOUND"
        if message.get("direction") == "outbound":
            return "OUTBOUND"
        return "SYSTEM/INTERNAL"

    def _message_preview(self, message: dict[str, Any] | None) -> str:
        if not message:
            return ""
        ref = message.get("content_ref") or ""
        body = self._read_local_content_ref(ref)
        if body:
            try:
                decoded = json.loads(body)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                for key in ["text", "body", "content", "message", "preview"]:
                    if decoded.get(key):
                        return self._short(decoded[key], 120)
            return self._short(body.replace("\n", " "), 120)
        return self._short(ref, 120)

    def _read_local_content_ref(self, content_ref: str) -> str:
        parsed = urlparse(content_ref)
        if parsed.scheme != "file":
            return ""
        path = Path(unquote(parsed.path)).resolve()
        artifact_root = self.store.artifact_root.resolve()
        try:
            path.relative_to(artifact_root)
        except ValueError:
            return ""
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""

    def _short(self, value: Any, limit: int = 48) -> str:
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _inbox_disclosure(self) -> dict[str, Any]:
        return {
            "source": "canonical local SQLite state",
            "live_channel_integration": False,
            "provider_sync_claimed": False,
            "send_enabled": False,
            "read_only": True,
            "notes": [
                "Inbox rows are local mirrored/stored state only.",
                "Badges such as review_needed and sendable are derived and labeled.",
                "Local drafts are unsent and do not imply provider delivery.",
            ],
        }

    def _user_summary(self, conn: Any, user: dict[str, Any]) -> dict[str, Any]:
        identity_count = self._count_where(conn, "channel_identities", f"user_id = '{user['user_id']}'")
        enrollment_count = self._count_where(conn, "channel_enrollments", f"user_id = '{user['user_id']}'")
        active_grants_received = self._count_where(
            conn,
            "authority_grants",
            f"grantee_user_id = '{user['user_id']}' AND status = 'active'",
        )
        active_grants_given = self._count_where(
            conn,
            "authority_grants",
            f"grantor_user_id = '{user['user_id']}' AND status = 'active'",
        )
        pending_enrollments = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM channel_enrollments
                WHERE user_id = ?
                  AND (state IN ('pairing_requested', 'challenge_issued', 'awaiting_owner_approval', 'recovery_requested')
                       OR owner_approval_status = 'requested')
                """,
                (user["user_id"],),
            ).fetchone()["n"]
        )
        degraded_bindings = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM channel_identities
                WHERE user_id = ?
                  AND (status NOT IN ('active', 'legacy_active')
                       OR enrollment_state NOT IN ('enrolled', 'legacy_active'))
                """,
                (user["user_id"],),
            ).fetchone()["n"]
        ) + int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM channel_enrollments
                WHERE user_id = ?
                  AND (status != 'active' OR state NOT IN ('enrolled', 'challenge_verified'))
                """,
                (user["user_id"],),
            ).fetchone()["n"]
        )
        badges = []
        if user["status"] != "active":
            badges.append("USER-SUSPENDED" if user["status"] == "suspended" else f"USER-{str(user['status']).upper()}")
        if pending_enrollments:
            badges.append("APPROVAL-NEEDED")
        if degraded_bindings:
            badges.append("DEGRADED-BINDINGS")
        return {
            **user,
            "identity_count": identity_count,
            "enrollment_count": enrollment_count,
            "active_grants_received": active_grants_received,
            "active_grants_given": active_grants_given,
            "pending_enrollment_count": pending_enrollments,
            "degraded_binding_count": degraded_bindings,
            "badges": badges,
            "read_only": True,
        }

    def _user_degraded_bindings(
        self,
        user: dict[str, Any],
        identities: list[dict[str, Any]],
        enrollments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        degraded = []
        enrollment_by_id = {enrollment["enrollment_id"]: enrollment for enrollment in enrollments}
        for identity in identities:
            reasons = []
            if user["status"] != "active":
                reasons.append(f"user_status:{user['status']}")
            if identity.get("status") not in {"active", "legacy_active"}:
                reasons.append(f"identity_status:{identity.get('status')}")
            if identity.get("enrollment_state") not in {"enrolled", "legacy_active"}:
                reasons.append(f"identity_enrollment_state:{identity.get('enrollment_state')}")
            enrollment = enrollment_by_id.get(identity.get("enrollment_id"))
            if identity.get("enrollment_id") and enrollment is None:
                reasons.append("missing_enrollment")
            if enrollment:
                if enrollment.get("status") != "active":
                    reasons.append(f"enrollment_status:{enrollment.get('status')}")
                if enrollment.get("state") != "enrolled":
                    reasons.append(f"enrollment_state:{enrollment.get('state')}")
                if enrollment.get("owner_approval_status") == "requested":
                    reasons.append("owner_approval_requested")
            if reasons:
                degraded.append(
                    {
                        "channel_identity_id": identity["channel_identity_id"],
                        "channel_type": identity["channel_type"],
                        "address": identity["address"],
                        "enrollment_id": identity.get("enrollment_id"),
                        "status": identity.get("status"),
                        "state": identity.get("enrollment_state"),
                        "reasons": reasons,
                    }
                )
        for enrollment in enrollments:
            if enrollment["state"] == "enrolled" and enrollment["status"] == "active":
                continue
            degraded.append(
                {
                    "enrollment_id": enrollment["enrollment_id"],
                    "channel_type": enrollment["channel_type"],
                    "address": enrollment["address"],
                    "status": enrollment["status"],
                    "state": enrollment["state"],
                    "reasons": [
                        reason
                        for reason in [
                            f"user_status:{user['status']}" if user["status"] != "active" else "",
                            f"enrollment_status:{enrollment['status']}" if enrollment["status"] != "active" else "",
                            f"enrollment_state:{enrollment['state']}" if enrollment["state"] != "enrolled" else "",
                            "owner_approval_requested" if enrollment["owner_approval_status"] == "requested" else "",
                        ]
                        if reason
                    ],
                }
            )
        return degraded

    def _require_primary_operator(self, conn: Any, actor_user_id: str) -> dict[str, Any]:
        actor = self.store.get_by_id("users", actor_user_id, conn=conn)
        if actor is None or actor["status"] != "active":
            raise PermissionError(f"Active operator user not found: {actor_user_id}")
        if not actor["primary_user_flag"]:
            raise PermissionError("Only an active primary user can perform bounded user administration")
        return actor

    def _set_user_status_admin(
        self,
        user_id: str,
        *,
        actor_user_id: str,
        confirmation: str,
        expected_confirmation: str,
        new_status: str,
        event_type: str,
        outcome: str,
    ) -> dict[str, Any]:
        if confirmation != expected_confirmation:
            raise PermissionError(f"Consequential admin action requires --confirm {expected_confirmation}")
        self.store.initialize()
        with self.store.connect() as conn:
            actor = self._require_primary_operator(conn, actor_user_id)
            target = self.store.get_by_id("users", user_id, conn=conn)
            if target is None:
                raise ValueError(f"User not found: {user_id}")
            if target["primary_user_flag"] and new_status != "active":
                raise PermissionError("This bounded UX does not suspend the primary user")
            if target["status"] == new_status:
                raise ValueError(f"User already has status {new_status}: {user_id}")
            updated = self.store.update(
                "users",
                user_id,
                {"status": new_status, "updated_at": self._now_sql(conn)},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor["user_id"],
            )
            audit = self._operator_user_audit(
                conn,
                event_type,
                actor["user_id"],
                user_id,
                f"Trusted local operator set user status to {new_status}",
                outcome,
                {
                    "operator_surface": "trusted_local_tui",
                    "confirmation": confirmation,
                    "previous_status": target["status"],
                    "new_status": new_status,
                    "enrollment_policy_bypassed": False,
                },
            )
            event_id = self.store.append_event(
                event_type,
                "user",
                user_id,
                "user",
                actor["user_id"],
                {
                    "audit_event_id": audit["audit_event_id"],
                    "previous_status": target["status"],
                    "new_status": new_status,
                },
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return {"user": updated, "audit_event": audit, "event_id": event_id}

    def _operator_user_audit(
        self,
        conn: Any,
        event_type: str,
        actor_user_id: str,
        object_ref: str,
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
                "object_type": "user",
                "object_ref": object_ref,
                "action_summary": summary,
                "outcome": outcome,
                "metadata_json": metadata,
            },
            conn=conn,
            emit_event=False,
        )

    def resolve_approval(
        self,
        approval_record_id: str,
        *,
        actor_user_id: str,
        status: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if status not in {"approved", "denied"}:
            raise ValueError("Approval resolution status must be approved or denied")
        expected = status.upper()
        if confirmation != expected:
            raise PermissionError(f"Consequential admin action requires --confirm {expected}")
        self.store.initialize()
        with self.store.connect() as conn:
            actor = self.store.get_by_id("users", actor_user_id, conn=conn)
            if actor is None or actor["status"] != "active":
                raise PermissionError(f"Active operator user not found: {actor_user_id}")
            approval = self.store.get_by_id("approval_records", approval_record_id, conn=conn)
            if approval is None:
                raise ValueError(f"Approval record not found: {approval_record_id}")
            if approval["status"] != "requested":
                raise ValueError(f"Approval is not requested: {approval_record_id}")
            if approval.get("approver_user_id") not in {None, actor_user_id} and not actor["primary_user_flag"]:
                raise PermissionError("Only the assigned approver or primary user can resolve this approval")

            updated = self.store.update(
                "approval_records",
                approval_record_id,
                {"status": status, "resolved_at": self._now_sql(conn)},
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_user_id,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "operator_approval_resolved",
                    "actor_type": "user",
                    "actor_ref": actor_user_id,
                    "object_type": "approval_record",
                    "object_ref": approval_record_id,
                    "action_summary": f"Trusted local operator marked approval {status}",
                    "outcome": status,
                    "policy_decision_id": approval["policy_decision_id"],
                    "metadata_json": {
                        "operator_surface": "trusted_local_tui",
                        "mode": "admin",
                        "previous_status": approval["status"],
                        "confirmation": confirmation,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            event_id = self.store.append_event(
                "operator_approval_resolved",
                "approval_record",
                approval_record_id,
                "user",
                actor_user_id,
                {"status": status, "audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return {"approval_record": updated, "audit_event": audit, "event_id": event_id}

    def _audit_failures(self, conn: Any, limit: int) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in FAILURE_OUTCOMES)
        rows = conn.execute(
            f"""
            SELECT * FROM audit_events
            WHERE outcome IN ({placeholders})
               OR event_type LIKE '%failed%'
               OR event_type LIKE '%denied%'
            ORDER BY created_at DESC, audit_event_id DESC
            LIMIT ?
            """,
            (*sorted(FAILURE_OUTCOMES), limit),
        ).fetchall()
        return [
            {
                "source": "audit_events",
                "record_id": row["audit_event_id"],
                "kind": row["event_type"],
                "object": f"{row['object_type']}:{row['object_ref']}",
                "summary": row["action_summary"],
                "state": row["outcome"],
                "observed_at": row["created_at"],
            }
            for row in rows
        ]

    def _status_failures(
        self,
        conn: Any,
        table: str,
        pk: str,
        label_column: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        observed_expr = "updated_at" if "updated_at" in columns else "created_at"
        status_predicates = ["status IN (" + ", ".join("?" for _ in FAILURE_STATUSES) + ")"]
        params: list[Any] = list(sorted(FAILURE_STATUSES))
        if "state" in columns:
            status_predicates.append("state IN (" + ", ".join("?" for _ in FAILURE_STATUSES) + ")")
            params.extend(sorted(FAILURE_STATUSES))
        rows = conn.execute(
            f"""
            SELECT * FROM {table}
            WHERE {' OR '.join(status_predicates)}
            ORDER BY {observed_expr} DESC, {pk} DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        disclosures = []
        for row in rows:
            label = row[label_column] if label_column in row.keys() else row[pk]
            observed_at = row[observed_expr]
            state = row["status"]
            if "state" in row.keys() and row["state"] in FAILURE_STATUSES:
                state = row["state"]
            disclosures.append(
                {
                    "source": table,
                    "record_id": row[pk],
                    "kind": "status_failure",
                    "object": f"{table}:{row[pk]}",
                    "summary": str(label or row[pk]),
                    "state": state,
                    "observed_at": observed_at,
                }
            )
        return disclosures

    def _count(self, conn: Any, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

    def _count_where(self, conn: Any, table: str, where: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}").fetchone()["n"])

    def _now_sql(self, conn: Any) -> str:
        return str(conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now").fetchone()["now"])


class TrustedOperatorTUI:
    """Small native terminal shell for trusted local operator and chat-mode scaffolding."""

    def __init__(self, store: AgentFirstStore, *, mode: str = "operator", color: bool | None = None):
        self.surface = OperatorSurface(store)
        self.shell_mode = self._normalize_mode(mode)
        self.color = self._color_enabled(color)

    def run_interactive(self) -> None:
        self._run_startup_splash()
        print(self.render_home().text)
        while True:
            try:
                command = input(self._prompt()).strip()
            except EOFError:
                print()
                return
            if command in {"quit", "exit"}:
                return
            if not command:
                continue
            result = self.handle_command(command)
            print(result.text)

    def run_script(self, commands: Iterable[str]) -> list[OperatorCommandResult]:
        results = []
        for command in commands:
            results.append(self.handle_command(command))
        return results

    def handle_command(self, command: str) -> OperatorCommandResult:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return OperatorCommandResult(
                "SHELL",
                "Command Parse Error",
                self._screen("SHELL", "Command Parse Error", [self._guidance(f"Could not parse command: {exc}")]),
                {"error": "parse_error", "command": command},
            )
        if not parts:
            return self.render_home()
        if parts[0] in {"mode", "switch"}:
            return self.render_mode_switch(parts[1:] if len(parts) > 1 else [])
        if parts[0] in {"operator", "ops"}:
            if len(parts) == 1:
                return self.render_mode_switch(["operator"])
            return self._handle_operator_command(parts[1:], raw_command=command)
        if parts[0] == "chat":
            if len(parts) == 1:
                return self.render_mode_switch(["chat"])
            return self._handle_chat_command(parts[1:])
        if self.shell_mode == "chat":
            return self._handle_chat_command(parts)
        return self._handle_operator_command(parts, raw_command=command)

    def _handle_operator_command(self, parts: list[str], *, raw_command: str) -> OperatorCommandResult:
        if not parts or parts[0] in {"home", "help"}:
            return self.render_operator_help()
        if parts[0] == "status":
            return self.render_status()
        if parts[0] == "approvals":
            return self.render_approvals()
        if parts[0] == "audit":
            return self.render_audit()
        if parts[0] in {"users", "channels", "enrollments"}:
            if len(parts) > 2 and parts[1] in {"detail", "show"}:
                return self.render_user_detail(parts[2])
            return self.render_users()
        if parts[0] == "user":
            return self.render_user_detail(parts[1] if len(parts) > 1 else "")
        if parts[0] in {"tasks", "projects"}:
            return self.render_tasks()
        if parts[0] == "inbox":
            return self._handle_inbox_command(parts[1:])
        if parts[0] == "failures":
            return self.render_failures()
        if parts[:2] == ["admin", "approval"]:
            return self._handle_admin_approval(parts)
        if parts[:2] == ["admin", "user"]:
            return self._handle_admin_user(parts)
        return OperatorCommandResult(
            "READ-ONLY",
            "Unknown Command",
            self._screen(
                "READ-ONLY",
                "Unknown Command",
                [self._guidance(f"Unknown operator command: {raw_command}"), self._command_line("help")],
            ),
            {"error": "unknown_command", "command": raw_command},
        )

    def _handle_chat_command(self, parts: list[str]) -> OperatorCommandResult:
        if not parts or parts[0] in {"home", "help"}:
            return self.render_chat_home()
        if parts[0] == "status":
            return self.render_chat_status()
        if parts[0] == "inbox":
            return self._handle_inbox_command(parts[1:], chat_context=True)
        if parts[0] == "thread":
            return self.render_inbox_thread(parts[1] if len(parts) > 1 else "", chat_context=True)
        if parts[0] in {"compose", "draft"}:
            return self.render_chat_compose(parts[1:])
        return OperatorCommandResult(
            "CHAT-SCAFFOLD",
            "Unknown Chat Command",
            self._screen(
                "CHAT-SCAFFOLD",
                "Unknown Chat Command",
                [
                    self._guidance(f"Unknown chat scaffold command: {' '.join(parts)}"),
                    self._command_line("chat help"),
                    self._command_line("mode operator"),
                ],
                accent="chat",
            ),
            {"error": "unknown_chat_command", "command": parts},
        )

    def render_home(self) -> OperatorCommandResult:
        if self.shell_mode == "chat":
            return self.render_chat_home()
        return self.render_operator_help()

    def render_help(self) -> OperatorCommandResult:
        return self.render_home()

    def render_operator_help(self) -> OperatorCommandResult:
        lines = [
            self._section("Operator guidance"),
            self._guidance("Trusted local administration over AgentFirst SQLite state."),
            self._guidance("Read-only views do not write audit or event rows."),
            "",
            self._section("Mode commands"),
            self._command_line("mode operator", "trusted operator shell"),
            self._command_line("mode chat", "future-facing chat scaffold; no live channel integration"),
            "",
            self._section("Read-only inspection"),
            self._command_line("status", "counts, work, approvals, failure disclosure"),
            self._command_line("approvals", "approval queue and policy context"),
            self._command_line("audit", "recent audit events and event log"),
            self._command_line("users", "users, channel identities, enrollments"),
            self._command_line("user <user_id>", "read-only user detail with authority and binding state"),
            self._command_line("tasks", "projects, commitments, blockers"),
            self._command_line("inbox", "read-only local inbox over stored threads and messages"),
            self._command_line("inbox thread <thread_id>", "read-only local thread detail"),
            self._command_line("failures", "explicit degraded-state disclosure"),
            "",
            self._section("Consequential admin"),
            self._command_line("admin approval approve <approval_record_id> --actor <user_id> --confirm APPROVED"),
            self._command_line("admin approval deny <approval_record_id> --actor <user_id> --confirm DENIED"),
            self._command_line('admin user create --actor <primary_user_id> --display-name "Name" --confirm CREATE_USER'),
            self._command_line("admin user suspend <user_id> --actor <primary_user_id> --confirm SUSPEND_USER"),
            self._command_line("admin user reactivate <user_id> --actor <primary_user_id> --confirm REACTIVATE_USER"),
        ]
        return OperatorCommandResult("READ-ONLY", "Operator Home", self._screen("READ-ONLY", "Operator Home", lines), {})

    def render_chat_home(self) -> OperatorCommandResult:
        lines = [
            self._section("Chat scaffold"),
            self._guidance("This mode is a shell for a future conversational surface."),
            self._guidance("No Telegram, BlueBubbles, Google Chat, or other live channel is connected here."),
            self._guidance("It does not read or invent channel history, inbound messages, or assistant replies."),
            "",
            self._section("Useful now"),
            self._command_line("chat status", "show scaffold boundaries and current operator-state summary"),
            self._command_line("chat inbox", "inspect real local stored threads; no live provider sync"),
            self._command_line("chat thread <thread_id>", "inspect one local stored thread"),
            self._command_line("chat compose <text>", "render a local draft panel only; it is not sent"),
            self._command_line("mode operator", "return to trusted administration"),
            "",
            self._section("Future-facing concepts"),
            self._user_input("User input: eventual inbound or operator-authored prompt"),
            self._assistant_reply("Assistant reply: eventual governed response preview"),
            self._system_guidance("System guidance: policy, authority, disclosure, and routing context"),
        ]
        return OperatorCommandResult(
            "CHAT-SCAFFOLD",
            "Chat Home",
            self._screen("CHAT-SCAFFOLD", "Chat Home", lines, accent="chat"),
            {"mode": "chat", "live_channel_integration": False},
        )

    def render_chat_status(self) -> OperatorCommandResult:
        data = self.surface.status_overview()
        lines = [
            self._section("Scaffold boundary"),
            self._badge("NO LIVE CHANNEL", "warn") + " Chat mode is not connected to messaging providers.",
            self._badge("LOCAL INBOX ONLY", "ok") + " chat inbox reads stored local threads, not remote history.",
            self._badge("LOCAL ONLY", "ok") + " Operator facts below come from trusted local storage.",
            "",
            self._section("Operator state available to future chat shell"),
            *self._key_values(
                {
                    "open_approvals": data["approvals"]["open"],
                    "active_projects": data["work"]["active_projects"],
                    "active_commitments": data["work"]["active_commitments"],
                    "waiting_commitments": data["work"]["waiting_commitments"],
                    "blocked_commitments": data["work"]["blocked_commitments"],
                    "failure_disclosures": data["failure_disclosure_count"],
                }
            ),
            "",
            self._section("Next commands"),
            self._command_line("chat inbox"),
            self._command_line("chat compose <text>"),
            self._command_line("mode operator"),
        ]
        return OperatorCommandResult(
            "CHAT-SCAFFOLD",
            "Chat Scaffold Status",
            self._screen("CHAT-SCAFFOLD", "Chat Scaffold Status", lines, accent="chat"),
            {
                "chat": {
                    "live_channel_integration": False,
                    "history_loaded": False,
                    "remote_history_loaded": False,
                },
                "operator_status": data,
            },
        )

    def render_chat_compose(self, words: list[str]) -> OperatorCommandResult:
        draft = " ".join(words).strip()
        lines = [
            self._section("Local draft"),
            self._user_input(draft or "(empty draft)"),
            "",
            self._section("Assistant reply placeholder"),
            self._assistant_reply("No assistant response is generated or sent from this scaffold command."),
            "",
            self._section("System guidance"),
            self._system_guidance("A future live chat path must bind a real channel identity, policy decision, and audit trail."),
        ]
        return OperatorCommandResult(
            "CHAT-SCAFFOLD",
            "Chat Draft Scaffold",
            self._screen("CHAT-SCAFFOLD", "Chat Draft Scaffold", lines, accent="chat"),
            {"draft": draft, "sent": False, "live_channel_integration": False},
        )

    def render_mode_switch(self, args: list[str]) -> OperatorCommandResult:
        if not args or args[0] not in {"operator", "chat"}:
            lines = [
                self._guidance("Expected a mode name."),
                self._command_line("mode operator"),
                self._command_line("mode chat"),
            ]
            return OperatorCommandResult("SHELL", "Mode Selection", self._screen("SHELL", "Mode Selection", lines), {})
        self.shell_mode = args[0]
        if self.shell_mode == "chat":
            return self.render_chat_home()
        return self.render_operator_help()

    def render_status(self) -> OperatorCommandResult:
        data = self.surface.status_overview()
        counts = data["counts"]
        lines = [
            self._section("Operator guidance"),
            self._badge("TRUSTED LOCAL", "ok") + " bounded_v1_trusted_local_tui",
            f"Read-only views: {', '.join(data['read_only_views'])}",
            f"Admin actions: {', '.join(data['admin_actions'])}",
            "",
            self._section("Trusted state counts"),
            *self._key_values(counts),
            "",
            self._section("Work"),
            *self._key_values(data["work"]),
            "",
            self._badge("OPEN APPROVALS", "warn") + f" {data['approvals']['open']}",
            self._badge("FAILURE DISCLOSURE", "warn") + f" {data['failure_disclosure_count']}",
        ]
        lines.extend(self._failure_lines(data["failure_disclosures"]))
        return OperatorCommandResult("READ-ONLY", "Status Overview", self._screen("READ-ONLY", "Status Overview", lines), data)

    def render_approvals(self) -> OperatorCommandResult:
        approvals = self.surface.approvals()
        lines = [
            self._section("Operator guidance"),
            self._guidance("Approvals are read-only in this view. Use explicit admin approval commands for resolution."),
            "",
            self._section("Approvals"),
        ]
        lines.extend(
            self._rows(
                approvals,
                ["approval_record_id", "status", "approval_type", "approver_user_id", "action_type", "decision"],
            )
        )
        return OperatorCommandResult("READ-ONLY", "Approvals", self._screen("READ-ONLY", "Approvals", lines), {"approvals": approvals})

    def render_audit(self) -> OperatorCommandResult:
        data = self.surface.audit_events()
        lines = [self._section("Recent audit events")]
        lines.extend(self._rows(data["audit_events"], ["audit_event_id", "event_type", "outcome", "object_type", "object_ref"]))
        lines.append("")
        lines.append(self._section("Recent event log"))
        lines.extend(self._rows(data["event_log"], ["event_id", "event_type", "aggregate_type", "aggregate_id"]))
        return OperatorCommandResult("READ-ONLY", "Audit And Events", self._screen("READ-ONLY", "Audit And Events", lines), data)

    def render_users(self) -> OperatorCommandResult:
        data = self.surface.users_channels_enrollments()
        lines = [
            self._section("User management boundary"),
            self._badge("READ-ONLY", "ok") + " This view inspects users, authority, identities, and enrollments only.",
            self._badge("ADMIN SEPARATE", "warn") + " Create, suspend, and reactivate require explicit admin user commands.",
            "",
            self._section("Users"),
        ]
        lines.extend(
            self._rows(
                data["users"],
                [
                    "user_id",
                    "display_name",
                    "status",
                    "authority_tier",
                    "primary_user_flag",
                    "identity_count",
                    "enrollment_count",
                    "badges",
                ],
            )
        )
        lines.append("")
        lines.append(self._section("Channel identities"))
        lines.extend(
            self._rows(
                data["channel_identities"],
                ["channel_identity_id", "channel_type", "address", "enrollment_state", "status", "user_display_name"],
            )
        )
        lines.append("")
        lines.append(self._section("Channel enrollments"))
        lines.extend(
            self._rows(
                data["channel_enrollments"],
                ["enrollment_id", "channel_type", "address", "state", "status", "owner_approval_status"],
            )
        )
        lines.append("")
        lines.append(self._section("Next commands"))
        lines.append(self._command_line("user <user_id>"))
        return OperatorCommandResult("READ-ONLY", "Users Channels Enrollments", self._screen("READ-ONLY", "Users Channels Enrollments", lines), data)

    def render_user_detail(self, user_id: str) -> OperatorCommandResult:
        if not user_id:
            return OperatorCommandResult(
                "READ-ONLY",
                "Missing User Id",
                self._screen(
                    "READ-ONLY",
                    "Missing User Id",
                    [self._guidance("Expected a user id."), self._command_line("user <user_id>")],
                ),
                {"error": "missing_user_id"},
            )
        try:
            data = self.surface.user_detail(user_id)
        except ValueError as exc:
            return OperatorCommandResult(
                "READ-ONLY",
                "User Not Found",
                self._screen("READ-ONLY", "User Not Found", [self._guidance(str(exc)), self._command_line("users")]),
                {"error": "user_not_found", "user_id": user_id},
            )
        user = data["user"]
        lines = [
            self._section("User management boundary"),
            self._badge("READ-ONLY", "ok") + " Detail inspection does not mutate audit or event state.",
            self._badge("ADMIN SEPARATE", "warn") + " Consequential user changes require admin user commands.",
            "",
            self._section("Profile"),
            *self._key_values(
                {
                    "user_id": user["user_id"],
                    "display_name": user["display_name"],
                    "status": user["status"],
                    "authority_tier": user["authority_tier"],
                    "primary_user": bool(user["primary_user_flag"]),
                    "default_timezone": user["default_timezone"],
                    "badges": ",".join(user["badges"]) or "none",
                }
            ),
            "",
            self._section("Authority"),
            *self._key_values(
                {
                    "effective_tier": data["authority"]["effective_tier"],
                    "active_grants_received": len(data["authority"]["active_grants_received"]),
                    "active_grants_given": len(data["authority"]["active_grants_given"]),
                }
            ),
            "",
            self._section("Channel identities"),
        ]
        lines.extend(
            self._rows(
                data["channel_identities"],
                ["channel_identity_id", "channel_type", "address", "enrollment_state", "status", "enrollment_id"],
            )
        )
        lines.append("")
        lines.append(self._section("Channel enrollments"))
        lines.extend(
            self._rows(
                data["channel_enrollments"],
                ["enrollment_id", "channel_type", "address", "state", "status", "owner_approval_status"],
            )
        )
        if data["degraded_bindings"]:
            lines.append("")
            lines.append(self._section("Degraded or approval-needed state"))
            for binding in data["degraded_bindings"]:
                lines.append(
                    "  "
                    + " | ".join(
                        [
                            f"identity={binding.get('channel_identity_id', '')}",
                            f"enrollment={binding.get('enrollment_id', '')}",
                            f"address={binding.get('address')}",
                            f"reasons={','.join(binding.get('reasons', []))}",
                        ]
                    )
                )
        lines.append("")
        lines.append(self._section("Recent audit"))
        lines.extend(self._rows(data["recent_audit"], ["audit_event_id", "event_type", "outcome", "object_type", "object_ref"]))
        return OperatorCommandResult("READ-ONLY", "User Detail", self._screen("READ-ONLY", "User Detail", lines), data)

    def render_tasks(self) -> OperatorCommandResult:
        data = self.surface.tasks_projects()
        lines = [self._section("Projects")]
        lines.extend(self._rows(data["projects"], ["project_id", "name", "status", "owner_scope_type", "owner_scope_ref"]))
        lines.append("")
        lines.append(self._section("Commitments"))
        lines.extend(self._rows(data["commitments"], ["commitment_id", "title", "status", "project_id", "next_action"]))
        lines.append("")
        lines.append(self._section("Blockers"))
        lines.extend(self._rows(data["blockers"], ["blocker_id", "commitment_id", "status", "summary"]))
        return OperatorCommandResult("READ-ONLY", "Tasks And Projects", self._screen("READ-ONLY", "Tasks And Projects", lines), data)

    def _handle_inbox_command(self, parts: list[str], *, chat_context: bool = False) -> OperatorCommandResult:
        if not parts:
            return self.render_inbox(chat_context=chat_context)
        if parts[0] in {"thread", "detail", "show"}:
            return self.render_inbox_thread(parts[1] if len(parts) > 1 else "", chat_context=chat_context)
        return OperatorCommandResult(
            "READ-ONLY",
            "Unknown Inbox Command",
            self._screen(
                "READ-ONLY",
                "Unknown Inbox Command",
                [
                    self._guidance(f"Unknown inbox command: {' '.join(parts)}"),
                    self._command_line("inbox"),
                    self._command_line("inbox thread <thread_id>"),
                ],
                accent="chat" if chat_context else "operator",
            ),
            {"error": "unknown_inbox_command", "command": parts},
        )

    def render_inbox(self, *, chat_context: bool = False) -> OperatorCommandResult:
        data = self.surface.inbox_threads()
        lines = [
            self._section("Local inbox boundary"),
            self._badge("READ-ONLY", "ok") + " This command only inspects canonical local state.",
            self._badge("NO LIVE CHANNEL", "warn") + " No provider sync, send, receive, or delivery status is claimed.",
            self._badge("DERIVED BADGES", "warn") + " review_needed, sendable, and summaries are local derivations.",
            "",
            self._section("Threads"),
        ]
        if data["empty"]:
            lines.append("  " + self._badge("EMPTY", "muted") + " No stored local inbox threads were found.")
        else:
            for item in data["threads"]:
                badge_text = ",".join(item["badges"])
                lines.append(
                    "  "
                    + " | ".join(
                        [
                            f"thread_id={item['thread_id']}",
                            f"channel={item['channel_type']}",
                            f"owner={item['owner_scope']}",
                            f"last={self._short(item['last_activity_at'], 28)}",
                            f"messages={item['message_count']}",
                            f"badges={badge_text}",
                        ]
                    )
                )
                lines.append(f"    summary={self._short(item['summary'], 110)}")
        lines.append("")
        lines.append(self._section("Next commands"))
        prefix = "chat " if chat_context else ""
        lines.append(self._command_line(f"{prefix}inbox thread <thread_id>"))
        return OperatorCommandResult(
            "READ-ONLY",
            "Local Inbox",
            self._screen("READ-ONLY", "Local Inbox", lines, accent="chat" if chat_context else "operator"),
            data,
        )

    def render_inbox_thread(self, thread_id: str, *, chat_context: bool = False) -> OperatorCommandResult:
        if not thread_id:
            return OperatorCommandResult(
                "READ-ONLY",
                "Missing Thread Id",
                self._screen(
                    "READ-ONLY",
                    "Missing Thread Id",
                    [self._guidance("Expected a thread id."), self._command_line("inbox thread <thread_id>")],
                    accent="chat" if chat_context else "operator",
                ),
                {"error": "missing_thread_id"},
            )
        try:
            data = self.surface.inbox_thread_detail(thread_id)
        except ValueError as exc:
            return OperatorCommandResult(
                "READ-ONLY",
                "Inbox Thread Not Found",
                self._screen(
                    "READ-ONLY",
                    "Inbox Thread Not Found",
                    [self._guidance(str(exc)), self._command_line("inbox")],
                    accent="chat" if chat_context else "operator",
                ),
                {"error": "thread_not_found", "thread_id": thread_id},
            )
        thread = data["thread"]
        lines = [
            self._section("Local inbox boundary"),
            self._badge("READ-ONLY", "ok") + " Detail inspection does not mutate audit or event state.",
            self._badge("NO LIVE CHANNEL", "warn") + " Stored messages are not proof of current provider state.",
            "",
            self._section("Thread"),
            *self._key_values(
                {
                    "thread_id": thread["thread_id"],
                    "label": thread["label"],
                    "owner_scope": thread["owner_scope"],
                    "channel_type": thread["channel_type"],
                    "visibility_model": thread["visibility_model"],
                    "status": thread["status"],
                    "sendable_derived": thread["sendable"],
                    "badges": ",".join(thread["badges"]),
                }
            ),
            "",
            self._section("Message timeline"),
        ]
        if data["messages_empty"]:
            lines.append("  " + self._badge("EMPTY", "muted") + " This local thread has no stored messages.")
        else:
            for message in data["messages"]:
                draft = " | draft=UNSENT" if message["local_draft"] else ""
                lines.append(
                    "  "
                    + " | ".join(
                        [
                            f"{message['role_label']}",
                            f"id={message['message_event_id']}",
                            f"status={message['status']}",
                            f"at={self._short(message['timestamp'], 28)}",
                        ]
                    )
                    + draft
                )
                lines.append(f"    preview={self._short(message['preview'], 110)}")
        if data["approvals"]:
            lines.append("")
            lines.append(self._section("Approval-gated outbound state"))
            lines.extend(
                self._rows(
                    data["approvals"],
                    ["approval_record_id", "status", "approval_type", "action_type", "object_type", "object_ref"],
                )
            )
        degraded = thread.get("degraded_bindings", [])
        if degraded:
            lines.append("")
            lines.append(self._section("Enrollment degraded state"))
            for binding in degraded:
                lines.append(
                    "  "
                    + " | ".join(
                        [
                            f"identity={binding.get('channel_identity_id')}",
                            f"address={binding.get('address')}",
                            f"status={binding.get('status')}",
                            f"state={binding.get('state')}",
                            f"reasons={','.join(binding.get('reasons', []))}",
                        ]
                    )
                )
        if data["drafts"]:
            lines.append("")
            lines.append(self._section("Local drafts"))
            for draft in data["drafts"]:
                lines.append(
                    f"  {self._badge('UNSENT', 'warn')} message_event_id={draft['message_event_id']} status={draft['status']}"
                )
        if data["lanes"]:
            lines.append("")
            lines.append(self._section("Lane metadata"))
            lines.extend(self._rows(data["lanes"], ["lane_id", "lane_key", "display_name", "role", "status"]))
        if data["commitments"]:
            lines.append("")
            lines.append(self._section("Linked commitments"))
            lines.extend(self._rows(data["commitments"], ["commitment_id", "title", "status", "next_action"]))
        return OperatorCommandResult(
            "READ-ONLY",
            "Local Inbox Thread",
            self._screen("READ-ONLY", "Local Inbox Thread", lines, accent="chat" if chat_context else "operator"),
            data,
        )

    def render_failures(self) -> OperatorCommandResult:
        failures = self.surface.failure_disclosures()
        lines = [
            self._section("Operator guidance"),
            self._guidance("Failures and degraded states are explicitly disclosed in this view."),
        ]
        lines.extend(self._failure_lines(failures))
        return OperatorCommandResult("READ-ONLY", "Failure Disclosure", self._screen("READ-ONLY", "Failure Disclosure", lines), {"failures": failures})

    def _handle_admin_approval(self, parts: list[str]) -> OperatorCommandResult:
        if len(parts) < 5 or parts[2] not in {"approve", "deny"}:
            return OperatorCommandResult(
                "ADMIN",
                "Invalid Admin Command",
                self._screen(
                    "ADMIN",
                    "Invalid Admin Command",
                    [self._guidance("Expected admin approval approve|deny <id> --actor <user_id> --confirm <APPROVED|DENIED>")],
                ),
                {"error": "invalid_admin_command"},
            )
        status = "approved" if parts[2] == "approve" else "denied"
        approval_record_id = parts[3]
        actor_user_id = self._option(parts, "--actor")
        confirmation = self._option(parts, "--confirm")
        if not actor_user_id or not confirmation:
            return OperatorCommandResult(
                "ADMIN",
                "Missing Admin Confirmation",
                self._screen("ADMIN", "Missing Admin Confirmation", [self._guidance("Admin approval resolution requires --actor and --confirm.")]),
                {"error": "missing_confirmation"},
            )
        try:
            data = self.surface.resolve_approval(
                approval_record_id,
                actor_user_id=actor_user_id,
                status=status,
                confirmation=confirmation,
            )
        except (PermissionError, ValueError) as exc:
            return self._admin_error("Approval Admin Rejected", str(exc), {"error": "admin_rejected", "action": "approval.resolve"})
        lines = [
            self._section("Admin action result"),
            f"Approval record: {approval_record_id}",
            self._badge(status.upper(), "ok" if status == "approved" else "warn"),
            f"Actor user: {actor_user_id}",
            f"Audit event: {data['audit_event']['audit_event_id']}",
            f"Event log id: {data['event_id']}",
        ]
        return OperatorCommandResult("ADMIN", "Approval Resolved", self._screen("ADMIN", "Approval Resolved", lines), data)

    def _handle_admin_user(self, parts: list[str]) -> OperatorCommandResult:
        if len(parts) < 3 or parts[2] not in {"create", "suspend", "reactivate"}:
            return self._admin_error(
                "Invalid User Admin Command",
                "Expected admin user create|suspend|reactivate with --actor and --confirm.",
                {"error": "invalid_admin_command"},
            )
        action = parts[2]
        actor_user_id = self._option(parts, "--actor")
        confirmation = self._option(parts, "--confirm")
        if not actor_user_id or not confirmation:
            return self._admin_error(
                "Missing User Admin Confirmation",
                "User administration requires --actor and --confirm.",
                {"error": "missing_confirmation"},
            )
        try:
            if action == "create":
                display_name = self._option(parts, "--display-name")
                authority_tier = self._option(parts, "--authority-tier") or "standard"
                timezone = self._option(parts, "--timezone") or "UTC"
                data = self.surface.create_user_admin(
                    actor_user_id=actor_user_id,
                    display_name=display_name or "",
                    authority_tier=authority_tier,
                    default_timezone=timezone,
                    confirmation=confirmation,
                )
                title = "User Created"
            else:
                if len(parts) < 4:
                    return self._admin_error(
                        "Missing User Id",
                        "Expected admin user suspend|reactivate <user_id>.",
                        {"error": "missing_user_id"},
                    )
                target_user_id = parts[3]
                if action == "suspend":
                    data = self.surface.suspend_user_admin(
                        target_user_id,
                        actor_user_id=actor_user_id,
                        confirmation=confirmation,
                    )
                    title = "User Suspended"
                else:
                    data = self.surface.reactivate_user_admin(
                        target_user_id,
                        actor_user_id=actor_user_id,
                        confirmation=confirmation,
                    )
                    title = "User Reactivated"
        except (PermissionError, ValueError) as exc:
            return self._admin_error("User Admin Rejected", str(exc), {"error": "admin_rejected", "action": f"user.{action}"})
        user = data["user"]
        lines = [
            self._section("Admin action result"),
            f"Action: user.{action}",
            f"Actor user: {actor_user_id}",
            f"Target user: {user['user_id']}",
            f"Display name: {user['display_name']}",
            f"Status: {user['status']}",
            f"Authority tier: {user['authority_tier']}",
            f"Audit event: {data['audit_event']['audit_event_id']}",
            f"Event log id: {data['event_id']}",
        ]
        return OperatorCommandResult("ADMIN", title, self._screen("ADMIN", title, lines), data)

    def _admin_error(self, title: str, message: str, data: dict[str, Any]) -> OperatorCommandResult:
        return OperatorCommandResult(
            "ADMIN",
            title,
            self._screen("ADMIN", title, [self._guidance(message)]),
            data,
        )

    def _screen(self, mode: str, title: str, lines: list[str], *, accent: str = "operator") -> str:
        shell = self.shell_mode.upper()
        width = 88
        top = "╭" + "─" * (width - 2) + "╮"
        bottom = "╰" + "─" * (width - 2) + "╯"
        header = [
            top,
            self._boxed_line(f"AgentFirst TUI  shell={shell}  result={mode}", width),
            self._boxed_line(title, width),
            "├" + "─" * (width - 2) + "┤",
        ]
        body = [self._boxed_line(line, width) if line else self._boxed_line("", width) for line in lines]
        rendered = "\n".join(header + body + [bottom])
        if accent == "chat":
            return self._style(rendered, "cyan")
        if mode == "ADMIN":
            return self._style(rendered, "yellow")
        return self._style(rendered, "green")

    def _boxed_line(self, text: str, width: int) -> str:
        clean = self._strip_ansi(text)
        available = width - 4
        if len(clean) <= available:
            return f"│ {text}{' ' * (available - len(clean))} │"
        chunks = self._wrap(clean, available)
        return "\n".join(f"│ {chunk}{' ' * (available - len(chunk))} │" for chunk in chunks)

    def _key_values(self, values: dict[str, Any]) -> list[str]:
        return [f"  {key:<28} {value}" for key, value in sorted(values.items())]

    def _rows(self, rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
        if not rows:
            return ["  " + self._badge("NONE", "muted")]
        rendered = []
        for row in rows:
            cells = []
            for column in columns:
                value = row.get(column)
                cells.append(f"{column}={self._short(value)}")
            rendered.append("  " + " | ".join(cells))
        return rendered

    def _failure_lines(self, failures: list[dict[str, Any]]) -> list[str]:
        if not failures:
            return ["  " + self._badge("NO FAILURES FOUND", "ok")]
        lines = ["", self._section("Failure disclosures")]
        for failure in failures:
            lines.append(
                "  "
                + " | ".join(
                    [
                        f"source={failure['source']}",
                        f"state={self._badge(str(failure['state']).upper(), 'warn')}",
                        f"object={failure['object']}",
                        f"summary={self._short(failure['summary'], 80)}",
                    ]
                )
            )
        return lines

    def _option(self, parts: list[str], name: str) -> str | None:
        if name not in parts:
            return None
        index = parts.index(name)
        if index + 1 >= len(parts):
            return None
        return parts[index + 1]

    def _short(self, value: Any, limit: int = 48) -> str:
        text = "" if value is None else str(value)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _normalize_mode(self, mode: str) -> str:
        if mode not in {"operator", "chat"}:
            raise ValueError("TUI mode must be operator or chat")
        return mode

    def _prompt(self) -> str:
        return f"agentfirst-{self.shell_mode}> "

    def _run_startup_splash(self) -> None:
        if not self._startup_splash_enabled():
            return
        width = min(76, shutil.get_terminal_size((80, 24)).columns)
        frames = 16
        try:
            sys.stdout.write("\033[?25l")
            for frame in range(frames):
                sys.stdout.write("\033[H\033[2J")
                sys.stdout.write(self._startup_splash_frame(frame, frames, width))
                sys.stdout.flush()
                time.sleep(0.07)
            time.sleep(5)
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write("\033[0m\033[?25h\n")
            sys.stdout.flush()

    def _startup_splash_enabled(self) -> bool:
        setting = os.environ.get("AGENTFIRST_TUI_SPLASH", "1").strip().lower()
        if setting in {"0", "false", "no", "off"}:
            return False
        size = shutil.get_terminal_size((80, 24))
        return bool(
            self.color
            and sys.stdin.isatty()
            and sys.stdout.isatty()
            and os.environ.get("TERM", "dumb") != "dumb"
            and os.environ.get("CI", "").lower() not in {"1", "true"}
            and size.columns >= 64
            and size.lines >= 27
        )

    def _startup_splash_frame(self, frame: int, total_frames: int, width: int) -> str:
        flag_width = 50
        flag_height = 13
        left = max(0, (width - flag_width) // 2)
        lines: list[str] = []
        reveal_start = max(1, total_frames // 2)
        brand_text = "Agent1st"
        reveal_count = max(0, min(len(brand_text), frame - reveal_start + 1))
        brand = brand_text[:reveal_count]
        burst = self._startup_firework(frame, width, reveal_start)
        for row in range(5):
            lines.append(burst.get(row, ""))
        for y in range(flag_height):
            wave = (frame + y) % 4
            indent = left + (1 if wave in {1, 2} else 0)
            if y < 7:
                canton = self._startup_canton(y, 16)
                stripe_width = flag_width - 16 - wave
                stripe = self._startup_stripe(y, stripe_width)
                line = " " * indent + canton + stripe
            else:
                stripe = self._startup_stripe(y, flag_width - wave)
                line = " " * indent + stripe
            lines.append(line)

        lines.append("")
        if brand:
            lines.extend(self._startup_brand_rows(brand, width, frame, reveal_start))
            if brand == "Agent1st":
                anniversary = "Happy 250th Anniversary to the United States of America!"
                lines.append("")
                lines.append(" " * max(0, (width - len(anniversary)) // 2) + anniversary)
        else:
            muted = self._style("trusted local startup", "muted")
            lines.append(" " * max(0, (width - len(self._strip_ansi(muted))) // 2) + muted)
        return "\n".join(lines) + "\n"

    def _startup_brand_rows(self, brand: str, width: int, frame: int, reveal_start: int) -> list[str]:
        glyphs = self._startup_brand_glyphs()
        rows: list[str] = []
        sparkle = self._style("✦", "bright_white") if frame < reveal_start + 5 else " "
        for row in range(8):
            parts: list[str] = []
            for index, char in enumerate(brand.upper()):
                glyph = glyphs.get(char, glyphs["?"])
                color = ["bright_red", "bright_white", "bright_blue"][index % 3]
                parts.append(self._style(glyph[row], color))
            rendered = "  ".join(parts)
            if row == 3 and sparkle.strip():
                rendered = f"{sparkle} {rendered} {sparkle}"
            rows.append(" " * max(0, (width - len(self._strip_ansi(rendered))) // 2) + rendered)
        return rows

    def _startup_brand_glyphs(self) -> dict[str, tuple[str, ...]]:
        return {
            "A": ("  AA ", " A  A", "A    A", "A    A", "AAAAAA", "A    A", "A    A", "A    A"),
            "D": ("DDDDD ", "D    D", "D    D", "D    D", "D    D", "D    D", "D    D", "DDDDD "),
            "E": ("EEEEEE", "E     ", "E     ", "EEEEE ", "E     ", "E     ", "E     ", "EEEEEE"),
            "F": ("FFFFFF", "F     ", "F     ", "FFFFF ", "F     ", "F     ", "F     ", "F     "),
            "G": ("  GGGG ", " G    G", "G      ", "G GGGG ", "G    G ", "G    G ", "G    G ", " GGGG  "),
            "I": ("IIIIII", "  II  ", "  II  ", "  II  ", "  II  ", "  II  ", "  II  ", "IIIIII"),
            "1": ("  11  ", " 111  ", "1 11  ", "  11  ", "  11  ", "  11  ", "  11  ", "111111"),
            "N": ("N    N", "NN   N", "N N  N", "N  N N", "N   NN", "N    N", "N    N", "N    N"),
            "R": ("RRRRR ", "R    R", "R    R", "RRRRR ", "R  R  ", "R   R ", "R    R", "R    R"),
            "S": (" SSSS ", "S    S", "S     ", " SSSS ", "     S", "     S", "S    S", " SSSS "),
            "T": ("TTTTTT", "  TT  ", "  TT  ", "  TT  ", "  TT  ", "  TT  ", "  TT  ", "  TT  "),
            "?": ("??????", "    ??", "   ?? ", "  ??  ", " ??   ", "      ", " ??   ", "??????"),
        }

    def _startup_canton(self, row: int, width: int) -> str:
        star_rows = ["* * * * * * * ", " * * * * * *  "]
        stars = star_rows[row % 2][:width]
        if self.color:
            return self._style(stars.ljust(width), "canton")
        return stars.ljust(width)

    def _startup_stripe(self, row: int, width: int) -> str:
        stripe_width = max(1, width)
        color = "stripe_red" if row % 2 == 0 else "stripe_white"
        if self.color:
            return self._style(" " * stripe_width, color)
        char = "=" if row % 2 == 0 else "-"
        return char * stripe_width

    def _startup_firework(self, frame: int, width: int, reveal_start: int) -> dict[int, str]:
        centers = [max(8, width // 2 - 20), width // 2, min(width - 8, width // 2 + 20)]
        colors = ["bright_red", "bright_white", "bright_blue"]
        burst_frame = min(6, max(0, frame - reveal_start + 3))
        sparks = {
            0: [(0, 1, "|")],
            1: [(0, 0, "."), (0, 1, "*"), (0, 2, "'")],
            2: [(-2, 1, "*"), (2, 1, "*"), (0, 0, "*"), (0, 2, "*"), (-1, 0, "."), (1, 2, ".")],
            3: [(-4, 1, "*"), (4, 1, "*"), (0, 0, "*"), (0, 3, "*"), (-2, 0, "."), (2, 2, ".")],
            4: [(-7, 1, "."), (7, 1, "."), (-4, 0, "*"), (4, 2, "*"), (0, 0, "."), (0, 3, ".")],
            5: [(-10, 1, "."), (10, 1, "."), (-6, 0, "."), (6, 2, "."), (-2, 3, "."), (2, 0, ".")],
            6: [],
        }[burst_frame]
        rows: dict[int, list[tuple[str, str | None]]] = {}
        for index, center in enumerate(centers):
            offset = (index - 1) * (burst_frame % 2)
            for dx, dy, char in sparks:
                row = dy
                col = max(0, min(width - 1, center + dx + offset))
                rows.setdefault(row, [(" ", None)] * width)
                rows[row][col] = (char, colors[index])
        rendered: dict[int, str] = {}
        for row, cells in rows.items():
            while cells and cells[-1][0] == " ":
                cells.pop()
            rendered[row] = "".join(self._style(char, color) if color else char for char, color in cells)
        return rendered

    def _color_enabled(self, color: bool | None) -> bool:
        if color is not None:
            return color
        if os.environ.get("NO_COLOR"):
            return False
        return bool(sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb")

    def _style(self, text: str, color: str) -> str:
        if not self.color:
            return text
        palette = {
            "green": "32",
            "yellow": "33",
            "cyan": "36",
            "muted": "2",
            "red": "31",
            "white": "37",
            "blue": "34",
            "bright_red": "91;1",
            "bright_white": "97;1",
            "bright_blue": "94;1",
            "canton": "44;97;1",
            "stripe_red": "41",
            "stripe_white": "47",
        }
        code = palette.get(color)
        if not code:
            return text
        return f"\033[{code}m{text}\033[0m"

    def _strip_ansi(self, text: str) -> str:
        while "\033[" in text:
            start = text.find("\033[")
            end = text.find("m", start)
            if end == -1:
                break
            text = text[:start] + text[end + 1 :]
        return text

    def _wrap(self, text: str, width: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = ""
        for word in words:
            if len(word) > width:
                if current:
                    lines.append(current)
                    current = ""
                lines.extend(word[index : index + width] for index in range(0, len(word), width))
                continue
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def _section(self, text: str) -> str:
        return f"== {text.upper()} =="

    def _guidance(self, text: str) -> str:
        return f"GUIDANCE | {text}"

    def _command_line(self, command: str, description: str | None = None) -> str:
        if description:
            return f"COMMAND  | {command} :: {description}"
        return f"COMMAND  | {command}"

    def _user_input(self, text: str) -> str:
        return f"USER INPUT | {text}"

    def _assistant_reply(self, text: str) -> str:
        return f"ASSISTANT REPLY | {text}"

    def _system_guidance(self, text: str) -> str:
        return f"SYSTEM GUIDANCE | {text}"

    def _badge(self, text: str, tone: str = "muted") -> str:
        badge = f"[{text}]"
        if tone == "ok":
            return self._style(badge, "green")
        if tone == "warn":
            return self._style(badge, "yellow")
        return self._style(badge, "muted")

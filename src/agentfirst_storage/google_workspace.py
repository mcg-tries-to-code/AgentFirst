"""Bounded per-user Google Workspace connection and action model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .authority import AuthorityEngine, AuthorityRequest
from .policy import GovernedAction, PolicyEngine
from .store import AgentFirstStore, new_id


GOOGLE_WORKSPACE_SERVICES = {"gmail", "calendar", "contacts", "drive"}


@dataclass(frozen=True)
class GoogleWorkspaceRequest:
    """A bounded Google Workspace action resolved through a user-owned account."""

    actor_user_id: str
    target_user_id: str
    service: str
    operation: str
    google_connection_id: str | None = None
    invoker_agent_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    content_classification: str = "internal"


class GoogleWorkspaceService:
    """Resolve Google Workspace actions through explicit per-user connection state."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        authority_engine: AuthorityEngine | None = None,
        policy_engine: PolicyEngine | None = None,
    ):
        self.store = store
        self.authority_engine = authority_engine or AuthorityEngine(store)
        self.policy_engine = policy_engine or PolicyEngine(store)

    def create_connection(
        self,
        *,
        user_id: str,
        google_account_email: str,
        services: list[str],
        scopes: list[str] | None = None,
        credential_ref: str | None = None,
        credential_secret_id: str | None = None,
        policy_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        actor_user_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create a bounded per-user Google connection record.

        `credential_ref` remains available for legacy opaque references.
        `credential_secret_id` is the V1 secret-broker migration path.
        This chunk still models ownership, service scope, and provenance without
        introducing a live OAuth flow.
        """
        normalized_services = self._normalize_services(services)
        if not normalized_services:
            raise ValueError("A Google connection must enable at least one supported service")
        if status not in {"active", "suspended", "revoked"}:
            raise ValueError(f"Unsupported Google connection status: {status}")

        self.store.initialize()
        with self.store.connect() as conn:
            self._require_active_user(conn, user_id)
            actor_ref = actor_user_id or user_id
            connection = self.store.insert(
                "google_connections",
                {
                    "google_connection_id": new_id("gconn"),
                    "user_id": user_id,
                    "google_account_email": google_account_email.strip().lower(),
                    "services_json": normalized_services,
                    "scopes_json": scopes or [],
                    "credential_ref": credential_ref,
                    "credential_secret_id": credential_secret_id,
                    "policy_refs_json": policy_refs or [],
                    "metadata_json": metadata or {},
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=actor_ref,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "google_connection_created",
                    "actor_type": "user",
                    "actor_ref": actor_ref,
                    "object_type": "google_connection",
                    "object_ref": connection["google_connection_id"],
                    "action_summary": "Created per-user Google Workspace connection",
                    "outcome": "created",
                    "metadata_json": {
                        "user_id": user_id,
                        "google_account_email": connection["google_account_email"],
                        "services": normalized_services,
                        "credential_mode": (
                            "secret_handle"
                            if credential_secret_id
                            else "opaque_ref"
                            if credential_ref
                            else "not_configured"
                        ),
                        "credential_secret_id": credential_secret_id,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            for service in normalized_services:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO destination_trust_tiers (
                        destination_id,
                        destination_type,
                        destination_identity,
                        trust_tier,
                        policy_refs_json,
                        status
                    )
                    VALUES (?, 'google_workspace', ?, 1, '[]', 'active')
                    """,
                    (new_id("dest"), f"{service}:{connection['google_account_email']}"),
                )
            self.store.append_event(
                "google_connection_created",
                "google_connection",
                connection["google_connection_id"],
                "user",
                actor_ref,
                {"audit_event_id": audit["audit_event_id"], "user_id": user_id},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return connection

    def perform_action(self, request: GoogleWorkspaceRequest) -> dict[str, Any]:
        """Resolve, authorize, policy-check, and record a bounded Google action."""
        service = self._normalize_service(request.service)
        if not request.operation.strip():
            raise ValueError("Google Workspace operation is required")

        self.store.initialize()
        with self.store.connect() as conn:
            self._require_active_user(conn, request.actor_user_id)
            self._require_active_user(conn, request.target_user_id)
            connection = self._resolve_connection(
                conn,
                target_user_id=request.target_user_id,
                service=service,
                google_connection_id=request.google_connection_id,
            )
            capability = self._ensure_tool_capability(conn, service)

        authority_decision = self.authority_engine.evaluate(
            AuthorityRequest(
                actor_user_id=request.actor_user_id,
                action="read",
                object_type="google_connection",
                object_ref=connection["google_connection_id"],
                metadata={
                    "google_service": service,
                    "google_operation": request.operation,
                    "target_user_id": request.target_user_id,
                    "connection_user_id": connection["user_id"],
                },
            )
        )
        if not authority_decision["allowed"]:
            action = self._record_google_action(
                request=request,
                connection=connection,
                service=service,
                status="authority_denied",
                authority_policy_decision_id=authority_decision["policy_decision"]["policy_decision_id"],
                provenance={
                    "blocked_by": "authority",
                    "authority_rationale": authority_decision["rationale"],
                    "google_connection_user_id": connection["user_id"],
                    "google_connection_id": connection["google_connection_id"],
                    "google_account_email": connection["google_account_email"],
                },
            )
            raise PermissionError(
                "Google Workspace connection access denied by authority policy "
                f"(action_id={action['google_workspace_action_id']})"
            )

        governed_action = GovernedAction(
            action_type="invoke_tool",
            actor_type="agent" if request.invoker_agent_id else "user",
            actor_ref=request.invoker_agent_id or request.actor_user_id,
            sponsoring_user_id=connection["user_id"],
            object_type="google_connection",
            object_ref=connection["google_connection_id"],
            destination_type="google_workspace",
            destination_identity=f"{service}:{connection['google_account_email']}",
            content_classification=request.content_classification,
            metadata={
                "actor_user_id": request.actor_user_id,
                "target_user_id": request.target_user_id,
                "google_service": service,
                "google_operation": request.operation,
                "google_connection_id": connection["google_connection_id"],
                "google_connection_user_id": connection["user_id"],
            },
        )
        policy_result = self.policy_engine.record_tool_invocation(
            governed_action,
            tool_capability_id=capability["tool_capability_id"],
            input_ref=f"google-workspace:{service}:{request.operation}",
        )
        tool_invocation = policy_result["tool_invocation"]
        policy_decision = policy_result["decision"]["decision"]
        if policy_decision == "deny":
            status = "policy_denied"
        elif policy_decision in {"require_primary_user_approval", "require_owner_approval"}:
            status = "awaiting_approval"
        else:
            status = "completed"

        action = self._record_google_action(
            request=request,
            connection=connection,
            service=service,
            status=status,
            tool_invocation_id=tool_invocation["tool_invocation_id"],
            authority_policy_decision_id=authority_decision["policy_decision"]["policy_decision_id"],
            result={
                "executed": status == "completed",
                "service": service,
                "operation": request.operation,
                "policy_decision": policy_decision,
            },
            provenance={
                "google_connection_user_id": connection["user_id"],
                "google_connection_id": connection["google_connection_id"],
                "google_account_email": connection["google_account_email"],
                "authority_policy_decision_id": authority_decision["policy_decision"]["policy_decision_id"],
                "tool_invocation_id": tool_invocation["tool_invocation_id"],
                "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                "service": service,
                "operation": request.operation,
            },
        )
        return {
            "action": action,
            "connection": connection,
            "authority_decision": authority_decision,
            "policy_result": policy_result,
        }

    def _record_google_action(
        self,
        *,
        request: GoogleWorkspaceRequest,
        connection: dict[str, Any],
        service: str,
        status: str,
        authority_policy_decision_id: str,
        tool_invocation_id: str | None = None,
        result: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        with self.store.connect() as conn:
            action = self.store.insert(
                "google_workspace_actions",
                {
                    "google_workspace_action_id": new_id("gwa"),
                    "service": service,
                    "operation": request.operation,
                    "actor_user_id": request.actor_user_id,
                    "target_user_id": request.target_user_id,
                    "google_connection_id": connection["google_connection_id"],
                    "google_connection_user_id": connection["user_id"],
                    "google_account_email": connection["google_account_email"],
                    "tool_invocation_id": tool_invocation_id,
                    "authority_policy_decision_id": authority_policy_decision_id,
                    "status": status,
                    "input_json": request.input,
                    "result_json": result or {},
                    "provenance_json": provenance or {},
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=request.actor_user_id,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "google_workspace_action_recorded",
                    "actor_type": "user",
                    "actor_ref": request.actor_user_id,
                    "object_type": "google_workspace_action",
                    "object_ref": action["google_workspace_action_id"],
                    "action_summary": f"Google Workspace {service}.{request.operation} recorded as {status}",
                    "outcome": status,
                    "policy_decision_id": authority_policy_decision_id,
                    "metadata_json": {
                        "target_user_id": request.target_user_id,
                        "google_connection_id": connection["google_connection_id"],
                        "google_connection_user_id": connection["user_id"],
                        "google_account_email": connection["google_account_email"],
                        "tool_invocation_id": tool_invocation_id,
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "google_workspace_action_recorded",
                "google_workspace_action",
                action["google_workspace_action_id"],
                "user",
                request.actor_user_id,
                {"status": status, "audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return action

    def _resolve_connection(
        self,
        conn: Any,
        *,
        target_user_id: str,
        service: str,
        google_connection_id: str | None,
    ) -> dict[str, Any]:
        if google_connection_id:
            connection = self.store.get_by_id("google_connections", google_connection_id, conn=conn)
            if connection is None:
                raise ValueError(f"Google connection not found: {google_connection_id}")
            if connection["user_id"] != target_user_id:
                raise PermissionError("Google connection does not belong to the requested target user")
            if connection["status"] != "active":
                raise PermissionError("Google connection is not active")
            if service not in connection["services_json"]:
                raise PermissionError(f"Google connection does not enable service: {service}")
            return connection

        rows = conn.execute(
            """
            SELECT * FROM google_connections
            WHERE user_id = ? AND status = 'active'
            ORDER BY connected_at, google_connection_id
            """,
            (target_user_id,),
        ).fetchall()
        matches = [
            self.store._decode_row(row)
            for row in rows
            if service in self.store._decode_row(row)["services_json"]
        ]
        if not matches:
            raise ValueError(f"No active Google connection for target user and service: {service}")
        if len(matches) > 1:
            raise ValueError("Multiple matching Google connections require explicit google_connection_id")
        return matches[0]

    def _ensure_tool_capability(self, conn: Any, service: str) -> dict[str, Any]:
        name = f"google.{service}"
        row = conn.execute(
            """
            SELECT * FROM tool_capabilities
            WHERE name = ? AND provider = 'google_workspace'
            """,
            (name,),
        ).fetchone()
        if row is not None:
            return self.store._decode_row(row)
        return self.store.insert(
            "tool_capabilities",
            {
                "tool_capability_id": new_id("tool"),
                "name": name,
                "provider": "google_workspace",
                "input_schema_ref": f"bounded://google-workspace/{service}/input",
                "output_schema_ref": f"bounded://google-workspace/{service}/output",
                "policy_refs_json": [],
                "availability_status": "enabled",
                "risk_class": "medium",
                "audit_requirements_json": {
                    "authority_required": True,
                    "provenance_required": True,
                    "connection_scope": "per_user",
                },
            },
            conn=conn,
            emit_event=False,
        )

    def _require_active_user(self, conn: Any, user_id: str) -> dict[str, Any]:
        user = self.store.get_by_id("users", user_id, conn=conn)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        if user["status"] != "active":
            raise PermissionError(f"User is not active: {user_id}")
        return user

    def _normalize_services(self, services: list[str]) -> list[str]:
        return sorted({self._normalize_service(service) for service in services})

    def _normalize_service(self, service: str) -> str:
        normalized = service.strip().lower()
        if normalized not in GOOGLE_WORKSPACE_SERVICES:
            raise ValueError(f"Unsupported Google Workspace service: {service}")
        return normalized

"""Bounded V1 tooling baseline and governed invocation service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .authority import AuthorityEngine, AuthorityRequest
from .policy import GovernedAction, PolicyEngine
from .store import AgentFirstStore, new_id


V1_TOOL_BASELINE = [
    {
        "name": "local.artifact_write",
        "provider": "agentfirst_core",
        "risk_class": "medium",
        "scope": "user_or_project_artifact",
        "consequential": True,
    },
    {
        "name": "local.commitment_progress",
        "provider": "agentfirst_core",
        "risk_class": "medium",
        "scope": "owned_commitment",
        "consequential": True,
    },
    {
        "name": "research.wikipedia_search",
        "provider": "wikipedia-api",
        "risk_class": "medium",
        "scope": "external_public_research",
        "consequential": True,
    },
    {
        "name": "channel.telegram_send_message",
        "provider": "telegram-bot-api",
        "risk_class": "medium",
        "scope": "enrolled_telegram_channel",
        "consequential": True,
    },
    {
        "name": "channel.bluebubbles_send_message",
        "provider": "bluebubbles-api",
        "risk_class": "medium",
        "scope": "enrolled_bluebubbles_channel",
        "consequential": True,
    },
    {
        "name": "google.gmail",
        "provider": "google_workspace",
        "risk_class": "medium",
        "scope": "per_user_google_connection",
        "consequential": True,
    },
    {
        "name": "google.calendar",
        "provider": "google_workspace",
        "risk_class": "medium",
        "scope": "per_user_google_connection",
        "consequential": True,
    },
    {
        "name": "google.contacts",
        "provider": "google_workspace",
        "risk_class": "medium",
        "scope": "per_user_google_connection",
        "consequential": True,
    },
    {
        "name": "google.drive",
        "provider": "google_workspace",
        "risk_class": "medium",
        "scope": "per_user_google_connection",
        "consequential": True,
    },
]


@dataclass(frozen=True)
class ToolInvocationRequest:
    """A consequential V1 tool request under explicit authority and policy."""

    actor_user_id: str
    sponsoring_user_id: str
    capability_name: str
    provider: str
    operation: str
    scope_type: str
    scope_ref: str
    input: dict[str, Any] = field(default_factory=dict)
    invoker_agent_id: str | None = None
    destination_type: str = "local"
    destination_identity: str = "agentfirst-core"
    content_classification: str = "internal"


class ToolingService:
    """Register and invoke the bounded V1 tool baseline."""

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

    def ensure_v1_baseline(self, *, actor_type: str = "system", actor_ref: str = "tooling_baseline") -> list[dict[str, Any]]:
        """Create or return the explicitly bounded V1 baseline capabilities."""
        self.store.initialize()
        capabilities = []
        with self.store.connect() as conn:
            self._ensure_local_destination(conn)
            for definition in V1_TOOL_BASELINE:
                row = conn.execute(
                    """
                    SELECT * FROM tool_capabilities
                    WHERE name = ? AND provider = ?
                    """,
                    (definition["name"], definition["provider"]),
                ).fetchone()
                if row is not None:
                    capabilities.append(self.store._decode_row(row))
                    continue
                capability = self.store.insert(
                    "tool_capabilities",
                    {
                        "tool_capability_id": new_id("tool"),
                        "name": definition["name"],
                        "provider": definition["provider"],
                        "input_schema_ref": f"bounded://v1-tools/{definition['name']}/input",
                        "output_schema_ref": f"bounded://v1-tools/{definition['name']}/output",
                        "policy_refs_json": [],
                        "availability_status": "enabled",
                        "risk_class": definition["risk_class"],
                        "audit_requirements_json": {
                            "baseline": "v1",
                            "scope": definition["scope"],
                            "consequential": definition["consequential"],
                            "authority_required": True,
                            "policy_required": True,
                            "provenance_required": True,
                        },
                    },
                    conn=conn,
                    emit_event=False,
                    actor_type=actor_type,
                    actor_ref=actor_ref,
                )
                audit = self.store.insert(
                    "audit_events",
                    {
                        "audit_event_id": new_id("aud"),
                        "event_type": "tool_capability_registered",
                        "actor_type": actor_type,
                        "actor_ref": actor_ref,
                        "object_type": "tool_capability",
                        "object_ref": capability["tool_capability_id"],
                        "action_summary": f"Registered V1 baseline tool capability {definition['name']}",
                        "outcome": "registered",
                        "metadata_json": definition,
                    },
                    conn=conn,
                    emit_event=False,
                )
                self.store.append_event(
                    "tool_capability_registered",
                    "tool_capability",
                    capability["tool_capability_id"],
                    actor_type,
                    actor_ref,
                    {"audit_event_id": audit["audit_event_id"], "baseline": "v1"},
                    audit_event_id=audit["audit_event_id"],
                    conn=conn,
                )
                capabilities.append(capability)
        return capabilities

    def invoke(self, request: ToolInvocationRequest) -> dict[str, Any]:
        """Authority-check, policy-check, execute the bounded local path, and record provenance."""
        if not request.operation.strip():
            raise ValueError("Tool operation is required")
        self.ensure_v1_baseline(actor_type="system", actor_ref="tooling_service")
        with self.store.connect() as conn:
            self._require_active_user(conn, request.actor_user_id)
            self._require_active_user(conn, request.sponsoring_user_id)
            capability = self._require_capability(conn, request.capability_name, request.provider)

        authority_decision = self.authority_engine.evaluate(
            AuthorityRequest(
                actor_user_id=request.actor_user_id,
                action="intervene",
                object_type=request.scope_type,
                object_ref=request.scope_ref,
                metadata={
                    "capability_name": request.capability_name,
                    "provider": request.provider,
                    "operation": request.operation,
                    "sponsoring_user_id": request.sponsoring_user_id,
                },
            )
        )
        if not authority_decision["allowed"]:
            invocation = self._record_authority_denied_invocation(request, capability, authority_decision)
            return {
                "tool_invocation": invocation,
                "capability": capability,
                "authority_decision": authority_decision,
                "policy_result": None,
                "executed": False,
            }

        input_ref = self.store.write_artifact(
            f"tool-invocations/{new_id('tin')}/input.json",
            json.dumps(request.input, indent=2, sort_keys=True),
        )
        policy_result = self.policy_engine.record_tool_invocation(
            GovernedAction(
                action_type="invoke_tool",
                actor_type="agent" if request.invoker_agent_id else "user",
                actor_ref=request.invoker_agent_id or request.actor_user_id,
                sponsoring_user_id=request.sponsoring_user_id,
                object_type=request.scope_type,
                object_ref=request.scope_ref,
                destination_type=request.destination_type,
                destination_identity=request.destination_identity,
                content_classification=request.content_classification,
                metadata={
                    "capability_name": request.capability_name,
                    "provider": request.provider,
                    "operation": request.operation,
                    "actor_user_id": request.actor_user_id,
                },
            ),
            capability["tool_capability_id"],
            input_ref=input_ref,
            authority_policy_decision_id=authority_decision["policy_decision"]["policy_decision_id"],
            operation=request.operation,
            scope={
                "scope_type": request.scope_type,
                "scope_ref": request.scope_ref,
                "destination_type": request.destination_type,
                "destination_identity": request.destination_identity,
            },
            provenance={
                "capability_name": request.capability_name,
                "provider": request.provider,
                "actor_user_id": request.actor_user_id,
                "authority_allowed": True,
            },
        )
        invocation = policy_result["tool_invocation"]
        if invocation["status"] != "policy_allowed":
            blocked = self._finalize_invocation(
                invocation["tool_invocation_id"],
                request,
                status=invocation["status"],
                outcome={
                    "executed": False,
                    "blocked_by": "policy",
                    "policy_decision": policy_result["decision"]["decision"],
                },
                output_ref=None,
                policy_decision_id=policy_result["decision"]["policy_decision_id"],
            )
            return {
                "tool_invocation": blocked,
                "capability": capability,
                "authority_decision": authority_decision,
                "policy_result": policy_result,
                "executed": False,
            }

        output_ref = self._execute_bounded_local_action(request)
        completed = self._finalize_invocation(
            invocation["tool_invocation_id"],
            request,
            status="completed",
            outcome={
                "executed": True,
                "operation": request.operation,
                "output_ref": output_ref,
            },
            output_ref=output_ref,
            policy_decision_id=policy_result["decision"]["policy_decision_id"],
        )
        return {
            "tool_invocation": completed,
            "capability": capability,
            "authority_decision": authority_decision,
            "policy_result": policy_result,
            "executed": True,
        }

    def _execute_bounded_local_action(self, request: ToolInvocationRequest) -> str:
        if request.capability_name == "local.artifact_write":
            body = str(request.input.get("body", ""))
            name = str(request.input.get("name", "tool-output.md"))
            return self.store.write_artifact(f"tool-output/{request.scope_ref}/{name}", body)
        if request.capability_name == "local.commitment_progress":
            return self.store.write_artifact(
                f"tool-output/{request.scope_ref}/commitment-progress.json",
                json.dumps({"operation": request.operation, "input": request.input}, indent=2, sort_keys=True),
            )
        return self.store.write_artifact(
            f"tool-output/{request.scope_ref}/simulated-output.json",
            json.dumps(
                {
                    "simulated": True,
                    "capability_name": request.capability_name,
                    "provider": request.provider,
                    "operation": request.operation,
                },
                indent=2,
                sort_keys=True,
            ),
        )

    def _record_authority_denied_invocation(
        self,
        request: ToolInvocationRequest,
        capability: dict[str, Any],
        authority_decision: dict[str, Any],
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            invocation = self.store.insert(
                "tool_invocations",
                {
                    "tool_invocation_id": new_id("tinv"),
                    "tool_capability_id": capability["tool_capability_id"],
                    "invoker_agent_id": request.invoker_agent_id,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "authority_policy_decision_id": authority_decision["policy_decision"]["policy_decision_id"],
                    "operation": request.operation,
                    "scope_json": {
                        "scope_type": request.scope_type,
                        "scope_ref": request.scope_ref,
                        "destination_type": request.destination_type,
                        "destination_identity": request.destination_identity,
                    },
                    "input_ref": None,
                    "output_ref": None,
                    "policy_decision_refs_json": [],
                    "provenance_json": {
                        "tool_capability_id": capability["tool_capability_id"],
                        "capability_name": request.capability_name,
                        "provider": request.provider,
                        "sponsoring_user_id": request.sponsoring_user_id,
                        "actor_user_id": request.actor_user_id,
                        "scope_type": request.scope_type,
                        "scope_ref": request.scope_ref,
                        "authority_policy_decision_id": authority_decision["policy_decision"]["policy_decision_id"],
                    },
                    "outcome_json": {
                        "executed": False,
                        "blocked_by": "authority",
                        "authority_rationale": authority_decision["rationale"],
                    },
                    "status": "authority_denied",
                },
                conn=conn,
                emit_event=False,
                actor_type="user",
                actor_ref=request.actor_user_id,
            )
            self._audit_invocation(conn, request, invocation, "authority_denied", authority_decision["policy_decision"]["policy_decision_id"])
            return invocation

    def _finalize_invocation(
        self,
        invocation_id: str,
        request: ToolInvocationRequest,
        *,
        status: str,
        outcome: dict[str, Any],
        output_ref: str | None,
        policy_decision_id: str,
    ) -> dict[str, Any]:
        invocation = self.store.update(
            "tool_invocations",
            invocation_id,
            {"status": status, "output_ref": output_ref, "outcome_json": outcome, "ended_at": _now()},
            actor_type="user",
            actor_ref=request.actor_user_id,
            event_type="tool_invocation_finalized",
        )
        with self.store.connect() as conn:
            self._audit_invocation(conn, request, invocation, status, policy_decision_id)
        return invocation

    def _audit_invocation(
        self,
        conn: Any,
        request: ToolInvocationRequest,
        invocation: dict[str, Any],
        status: str,
        policy_decision_id: str,
    ) -> None:
        audit = self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": "tool_invocation_recorded",
                "actor_type": "user",
                "actor_ref": request.actor_user_id,
                "object_type": "tool_invocation",
                "object_ref": invocation["tool_invocation_id"],
                "action_summary": f"Tool {request.capability_name}.{request.operation} recorded as {status}",
                "outcome": status,
                "policy_decision_id": policy_decision_id,
                "metadata_json": {
                    "capability_name": request.capability_name,
                    "provider": request.provider,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "scope_type": request.scope_type,
                    "scope_ref": request.scope_ref,
                },
            },
            conn=conn,
            emit_event=False,
        )
        self.store.append_event(
            "tool_invocation_recorded",
            "tool_invocation",
            invocation["tool_invocation_id"],
            "user",
            request.actor_user_id,
            {"status": status, "audit_event_id": audit["audit_event_id"]},
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )

    def _require_capability(self, conn: Any, name: str, provider: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT * FROM tool_capabilities
            WHERE name = ? AND provider = ?
            """,
            (name, provider),
        ).fetchone()
        if row is None:
            raise ValueError(f"Tool capability is outside the V1 baseline: {provider}:{name}")
        capability = self.store._decode_row(row)
        if capability["availability_status"] != "enabled":
            raise PermissionError(f"Tool capability is not enabled: {provider}:{name}")
        return capability

    def _require_active_user(self, conn: Any, user_id: str) -> dict[str, Any]:
        user = self.store.get_by_id("users", user_id, conn=conn)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        if user["status"] != "active":
            raise PermissionError(f"User is not active: {user_id}")
        return user

    def _ensure_local_destination(self, conn: Any) -> None:
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
            VALUES (?, 'local', 'agentfirst-core', 0, '[]', 'active')
            """,
            (new_id("dest"),),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

"""Bounded V1 model/provider routing with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .policy import GovernedAction, PolicyEngine
from .provider_catalog import bounded_model_providers, find_model
from .store import AgentFirstStore, new_id


V1_MODEL_PROVIDERS = bounded_model_providers()


@dataclass(frozen=True)
class ModelPreferenceRequest:
    """An explicit bounded model preference for a user, agent, or task scope."""

    scope_type: str
    scope_ref: str
    provider: str
    model: str
    rationale_summary: str
    purpose: str = "general"
    priority: int = 100
    fallback_routes: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    created_by_type: str = "system"
    created_by_ref: str = "model_routing"


@dataclass(frozen=True)
class ModelRouteRequest:
    """A governed model route request with attributable scope."""

    actor_user_id: str
    sponsoring_user_id: str
    purpose: str = "general"
    scope_type: str = "user"
    scope_ref: str | None = None
    requesting_agent_id: str | None = None
    content_classification: str = "internal"
    origin_entity_ref: str | None = None
    unavailable_providers: set[str] = field(default_factory=set)
    unavailable_provider_models: set[str] = field(default_factory=set)
    task_scope_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelRoutingService:
    """Resolve bounded model/provider preferences and record every routing decision."""

    def __init__(self, store: AgentFirstStore, *, policy_engine: PolicyEngine | None = None):
        self.store = store
        self.policy_engine = policy_engine or PolicyEngine(store)

    def ensure_v1_provider_destinations(
        self,
        *,
        actor_type: str = "system",
        actor_ref: str = "model_routing_baseline",
    ) -> list[dict[str, Any]]:
        """Materialize bounded V1 model providers as policy destinations."""
        self.store.initialize()
        destinations: list[dict[str, Any]] = []
        with self.store.connect() as conn:
            for provider in V1_MODEL_PROVIDERS:
                row = conn.execute(
                    """
                    SELECT * FROM destination_trust_tiers
                    WHERE destination_type = 'model_provider'
                      AND destination_identity = ?
                    """,
                    (provider["destination_identity"],),
                ).fetchone()
                if row is not None:
                    destinations.append(self.store._decode_row(row))
                    continue
                destination = self.store.insert(
                    "destination_trust_tiers",
                    {
                        "destination_id": new_id("dest"),
                        "destination_type": "model_provider",
                        "destination_identity": provider["destination_identity"],
                        "trust_tier": provider["trust_tier"],
                        "policy_refs_json": [],
                        "status": "active",
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
                        "event_type": "model_provider_destination_registered",
                        "actor_type": actor_type,
                        "actor_ref": actor_ref,
                        "object_type": "destination_trust_tier",
                        "object_ref": destination["destination_id"],
                        "action_summary": f"Registered V1 model provider destination {provider['provider']}",
                        "outcome": "registered",
                        "metadata_json": provider,
                    },
                    conn=conn,
                    emit_event=False,
                )
                self.store.append_event(
                    "model_provider_destination_registered",
                    "destination_trust_tier",
                    destination["destination_id"],
                    actor_type,
                    actor_ref,
                    {"audit_event_id": audit["audit_event_id"], "provider": provider["provider"]},
                    audit_event_id=audit["audit_event_id"],
                    conn=conn,
                )
                destinations.append(destination)
        return destinations

    def create_preference(self, request: ModelPreferenceRequest) -> dict[str, Any]:
        """Create an explicit routing preference after validating bounded providers and scope."""
        self.ensure_v1_provider_destinations(actor_type="system", actor_ref="model_routing_service")
        self._require_provider_model(request.provider, request.model)
        for fallback in request.fallback_routes:
            self._require_provider_model(str(fallback.get("provider", "")), str(fallback.get("model", "")))
        if request.scope_type not in {"user", "agent", "task"}:
            raise ValueError("Model preference scope_type must be user, agent, or task")
        if not request.scope_ref.strip():
            raise ValueError("Model preference scope_ref is required")
        if not request.rationale_summary.strip():
            raise ValueError("Model preference rationale_summary is required")

        self.store.initialize()
        with self.store.connect() as conn:
            self._validate_scope(conn, request.scope_type, request.scope_ref)
            preference = self.store.insert(
                "model_provider_preferences",
                {
                    "model_preference_id": new_id("mpref"),
                    "scope_type": request.scope_type,
                    "scope_ref": request.scope_ref,
                    "purpose": request.purpose,
                    "provider": request.provider,
                    "model": request.model,
                    "priority": request.priority,
                    "fallback_routes_json": request.fallback_routes,
                    "constraints_json": request.constraints,
                    "rationale_summary": request.rationale_summary,
                    "status": "active",
                    "created_by_type": request.created_by_type,
                    "created_by_ref": request.created_by_ref,
                },
                conn=conn,
                emit_event=False,
                actor_type=request.created_by_type,
                actor_ref=request.created_by_ref,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "model_preference_created",
                    "actor_type": request.created_by_type,
                    "actor_ref": request.created_by_ref,
                    "object_type": "model_provider_preference",
                    "object_ref": preference["model_preference_id"],
                    "action_summary": f"Created model preference for {request.scope_type}:{request.scope_ref}",
                    "outcome": "created",
                    "metadata_json": {
                        "scope_type": request.scope_type,
                        "scope_ref": request.scope_ref,
                        "purpose": request.purpose,
                        "provider": request.provider,
                        "model": request.model,
                        "fallback_count": len(request.fallback_routes),
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "model_preference_created",
                "model_provider_preference",
                preference["model_preference_id"],
                request.created_by_type,
                request.created_by_ref,
                {"audit_event_id": audit["audit_event_id"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            return preference

    def route(self, request: ModelRouteRequest) -> dict[str, Any]:
        """Select a governed provider/model and persist fallback and policy provenance."""
        self.ensure_v1_provider_destinations(actor_type="system", actor_ref="model_routing_service")
        scope_type, scope_ref = self._request_scope(request)
        actor_type = "agent" if request.requesting_agent_id else "user"
        actor_ref = request.requesting_agent_id or request.actor_user_id

        self.store.initialize()
        with self.store.connect() as conn:
            self._require_active_user(conn, request.actor_user_id)
            self._require_active_user(conn, request.sponsoring_user_id)
            if request.requesting_agent_id:
                self._require_active_agent(conn, request.requesting_agent_id)
            self._validate_scope(conn, scope_type, scope_ref)
            preference = self._resolve_preference(conn, request, scope_type, scope_ref)

        if preference is None:
            return self._record_unroutable(
                request,
                scope_type,
                scope_ref,
                actor_type,
                actor_ref,
                "No active model/provider preference matched the request scope",
            )

        selected = self._select_route(preference, request)
        if selected is None:
            return self._record_unroutable(
                request,
                scope_type,
                scope_ref,
                actor_type,
                actor_ref,
                "Preferred provider was unavailable and no configured fallback was available",
                preference=preference,
            )

        policy_action = GovernedAction(
            action_type="query_model",
            actor_type=actor_type,
            actor_ref=actor_ref,
            sponsoring_user_id=request.sponsoring_user_id,
            object_type="model_route",
            object_ref=f"{scope_type}:{scope_ref}",
            destination_type="model_provider",
            destination_identity=selected["provider"],
            content_classification=request.content_classification,
            origin_entity_ref=request.origin_entity_ref,
            metadata={
                "purpose": request.purpose,
                "scope_type": scope_type,
                "scope_ref": scope_ref,
                "preferred_provider": preference["provider"],
                "preferred_model": preference["model"],
                "selected_provider": selected["provider"],
                "selected_model": selected["model"],
                "fallback_used": selected["fallback_used"],
                **request.metadata,
            },
        )
        policy_result = self.policy_engine.evaluate_and_record(policy_action)
        policy_decision = policy_result["decision"]["decision"]
        status = {
            "deny": "denied",
            "require_primary_user_approval": "awaiting_approval",
            "require_owner_approval": "awaiting_approval",
        }.get(policy_decision, "selected")

        disclosure = self._disclosure(preference, selected, status, policy_decision)
        route_decision = self._record_decision(
            request,
            scope_type,
            scope_ref,
            actor_type,
            actor_ref,
            preference,
            selected,
            disclosure,
            status,
            policy_result=policy_result,
        )
        return {
            "route_decision": route_decision,
            "preference": preference,
            "policy_result": policy_result,
            "selected": status == "selected",
            "fallback_used": bool(selected["fallback_used"]),
            "disclosure": disclosure,
        }

    def _resolve_preference(
        self,
        conn: Any,
        request: ModelRouteRequest,
        scope_type: str,
        scope_ref: str,
    ) -> dict[str, Any] | None:
        scopes: list[tuple[str, str]] = [(scope_type, scope_ref)]
        if request.requesting_agent_id and (scope_type, scope_ref) != ("agent", request.requesting_agent_id):
            scopes.append(("agent", request.requesting_agent_id))
        if (scope_type, scope_ref) != ("user", request.sponsoring_user_id):
            scopes.append(("user", request.sponsoring_user_id))

        for candidate_scope_type, candidate_scope_ref in scopes:
            for purpose in (request.purpose, "general"):
                row = conn.execute(
                    """
                    SELECT * FROM model_provider_preferences
                    WHERE scope_type = ?
                      AND scope_ref = ?
                      AND purpose = ?
                      AND status = 'active'
                    ORDER BY priority ASC, created_at DESC, model_preference_id ASC
                    LIMIT 1
                    """,
                    (candidate_scope_type, candidate_scope_ref, purpose),
                ).fetchone()
                if row is not None:
                    return self.store._decode_row(row)
        return None

    def _select_route(self, preference: dict[str, Any], request: ModelRouteRequest) -> dict[str, Any] | None:
        routes = [
            {
                "provider": preference["provider"],
                "model": preference["model"],
                "fallback_used": False,
                "fallback_reason": None,
            }
        ]
        for fallback in preference.get("fallback_routes_json", []):
            routes.append(
                {
                    "provider": fallback["provider"],
                    "model": fallback["model"],
                    "fallback_used": True,
                    "fallback_reason": fallback.get("reason") or "preferred route unavailable",
                }
            )

        for route in routes:
            key = f"{route['provider']}:{route['model']}"
            if route["provider"] in request.unavailable_providers:
                continue
            if key in request.unavailable_provider_models:
                continue
            return route
        return None

    def _record_decision(
        self,
        request: ModelRouteRequest,
        scope_type: str,
        scope_ref: str,
        actor_type: str,
        actor_ref: str,
        preference: dict[str, Any],
        selected: dict[str, Any],
        disclosure: str,
        status: str,
        *,
        policy_result: dict[str, Any],
    ) -> dict[str, Any]:
        approval = policy_result.get("approval_record")
        policy_decision = policy_result["decision"]
        with self.store.connect() as conn:
            decision = self.store.insert(
                "model_route_decisions",
                {
                    "model_route_decision_id": new_id("mroute"),
                    "model_preference_id": preference["model_preference_id"],
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "requesting_agent_id": request.requesting_agent_id,
                    "scope_type": scope_type,
                    "scope_ref": scope_ref,
                    "purpose": request.purpose,
                    "preferred_provider": preference["provider"],
                    "preferred_model": preference["model"],
                    "selected_provider": selected["provider"],
                    "selected_model": selected["model"],
                    "fallback_used": selected["fallback_used"],
                    "fallback_reason": selected["fallback_reason"],
                    "disclosure_summary": disclosure,
                    "policy_decision_id": policy_decision["policy_decision_id"],
                    "approval_record_id": approval["approval_record_id"] if approval else None,
                    "provenance_json": {
                        "preference_scope_type": preference["scope_type"],
                        "preference_scope_ref": preference["scope_ref"],
                        "request_scope_type": scope_type,
                        "request_scope_ref": scope_ref,
                        "actor_user_id": request.actor_user_id,
                        "requesting_agent_id": request.requesting_agent_id,
                        "sponsoring_user_id": request.sponsoring_user_id,
                        "policy_decision": policy_decision["decision"],
                        "policy_decision_id": policy_decision["policy_decision_id"],
                        "approval_record_id": approval["approval_record_id"] if approval else None,
                        "fallback_disclosed": bool(selected["fallback_used"]),
                    },
                    "outcome_json": {
                        "policy_decision": policy_decision["decision"],
                        "selected": status == "selected",
                        "approval_required": status == "awaiting_approval",
                        "denied": status == "denied",
                    },
                    "status": status,
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self._audit_decision(conn, decision, actor_type, actor_ref, status, disclosure, policy_decision["policy_decision_id"])
            return decision

    def _record_unroutable(
        self,
        request: ModelRouteRequest,
        scope_type: str,
        scope_ref: str,
        actor_type: str,
        actor_ref: str,
        reason: str,
        *,
        preference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            decision = self.store.insert(
                "model_route_decisions",
                {
                    "model_route_decision_id": new_id("mroute"),
                    "model_preference_id": preference["model_preference_id"] if preference else None,
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "sponsoring_user_id": request.sponsoring_user_id,
                    "requesting_agent_id": request.requesting_agent_id,
                    "scope_type": scope_type,
                    "scope_ref": scope_ref,
                    "purpose": request.purpose,
                    "preferred_provider": preference["provider"] if preference else None,
                    "preferred_model": preference["model"] if preference else None,
                    "selected_provider": None,
                    "selected_model": None,
                    "fallback_used": 0,
                    "fallback_reason": reason,
                    "disclosure_summary": f"Model routing failed: {reason}.",
                    "policy_decision_id": None,
                    "approval_record_id": None,
                    "provenance_json": {
                        "actor_user_id": request.actor_user_id,
                        "requesting_agent_id": request.requesting_agent_id,
                        "sponsoring_user_id": request.sponsoring_user_id,
                        "request_scope_type": scope_type,
                        "request_scope_ref": scope_ref,
                        "failure_reason": reason,
                    },
                    "outcome_json": {"selected": False, "failed": True, "reason": reason},
                    "status": "failed",
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self._audit_decision(conn, decision, actor_type, actor_ref, "failed", reason, None)
            return {
                "route_decision": decision,
                "preference": preference,
                "policy_result": None,
                "selected": False,
                "fallback_used": False,
                "disclosure": decision["disclosure_summary"],
            }

    def _audit_decision(
        self,
        conn: Any,
        decision: dict[str, Any],
        actor_type: str,
        actor_ref: str,
        status: str,
        disclosure: str,
        policy_decision_id: str | None,
    ) -> None:
        audit = self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": "model_route_decision_recorded",
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "object_type": "model_route_decision",
                "object_ref": decision["model_route_decision_id"],
                "action_summary": disclosure,
                "outcome": status,
                "policy_decision_id": policy_decision_id,
                "metadata_json": {
                    "selected_provider": decision["selected_provider"],
                    "selected_model": decision["selected_model"],
                    "fallback_used": bool(decision["fallback_used"]),
                    "scope_type": decision["scope_type"],
                    "scope_ref": decision["scope_ref"],
                },
            },
            conn=conn,
            emit_event=False,
        )
        self.store.append_event(
            "model_route_decision_recorded",
            "model_route_decision",
            decision["model_route_decision_id"],
            actor_type,
            actor_ref,
            {"status": status, "audit_event_id": audit["audit_event_id"]},
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )

    def _disclosure(
        self,
        preference: dict[str, Any],
        selected: dict[str, Any],
        status: str,
        policy_decision: str,
    ) -> str:
        route = f"{selected['provider']}:{selected['model']}"
        if selected["fallback_used"]:
            base = (
                f"Model route used fallback {route}; preferred "
                f"{preference['provider']}:{preference['model']} was unavailable. "
                f"Fallback reason: {selected['fallback_reason']}."
            )
        else:
            base = f"Model route selected preferred provider {route}."
        if status == "awaiting_approval":
            return f"{base} Provider use is awaiting approval ({policy_decision})."
        if status == "denied":
            return f"{base} Provider use was denied by policy."
        return base

    def _request_scope(self, request: ModelRouteRequest) -> tuple[str, str]:
        if request.task_scope_ref:
            return "task", request.task_scope_ref
        if request.scope_type == "task":
            if not request.scope_ref:
                raise ValueError("Task-scoped model routes require scope_ref")
            return "task", request.scope_ref
        if request.scope_type == "agent":
            scope_ref = request.scope_ref or request.requesting_agent_id
            if not scope_ref:
                raise ValueError("Agent-scoped model routes require scope_ref or requesting_agent_id")
            return "agent", scope_ref
        if request.scope_type == "user":
            return "user", request.scope_ref or request.sponsoring_user_id
        raise ValueError("Model route scope_type must be user, agent, or task")

    def _validate_scope(self, conn: Any, scope_type: str, scope_ref: str) -> None:
        if scope_type == "user":
            self._require_active_user(conn, scope_ref)
        elif scope_type == "agent":
            self._require_active_agent(conn, scope_ref)
        elif scope_type == "task" and not scope_ref.strip():
            raise ValueError("Task scope_ref is required")

    def _require_provider_model(self, provider: str, model: str) -> None:
        if find_model(provider, model) is None:
            raise ValueError(f"Model provider is outside the bounded V1 set: {provider}:{model}")

    def _require_active_user(self, conn: Any, user_id: str) -> dict[str, Any]:
        user = self.store.get_by_id("users", user_id, conn=conn)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        if user["status"] != "active":
            raise PermissionError(f"User is not active: {user_id}")
        return user

    def _require_active_agent(self, conn: Any, agent_id: str) -> dict[str, Any]:
        agent = self.store.get_by_id("agents", agent_id, conn=conn)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        if agent["status"] != "active":
            raise PermissionError(f"Agent is not active: {agent_id}")
        return agent

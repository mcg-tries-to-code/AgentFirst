#!/usr/bin/env python3
"""Validate V1 Chunk 7 governed model/provider routing."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import (
    AgentFirstStore,
    ModelPreferenceRequest,
    ModelRouteRequest,
    ModelRoutingService,
    V1_MODEL_PROVIDERS,
)
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk7-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 7 Primary", "America/New_York")
        alex = store.create_user(
            display_name="Alex Model Sponsor",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        agent = store.insert(
            "agents",
            {
                "agent_id": new_id("agt"),
                "display_name": "Alex Routing Agent",
                "owner_user_id": alex["user_id"],
                "persona_profile_json": {"purpose": "routing validation"},
                "capability_profile_json": {},
                "tool_policy_bindings_json": [],
                "memory_bindings_json": [],
                "model_routing_policy_json": {},
                "status": "active",
            },
            actor_type="user",
            actor_ref=alex["user_id"],
        )

        routing = ModelRoutingService(store)
        destinations = routing.ensure_v1_provider_destinations(
            actor_type="system",
            actor_ref="v1_chunk7_validation",
        )
        if len(destinations) != len(V1_MODEL_PROVIDERS):
            raise RuntimeError("V1 model provider destinations were not registered explicitly")

        user_preference = routing.create_preference(
            ModelPreferenceRequest(
                scope_type="user",
                scope_ref=alex["user_id"],
                purpose="general",
                provider="openai",
                model="gpt-5.4",
                fallback_routes=[
                    {
                        "provider": "local",
                        "model": "llama.cpp-default",
                        "reason": "OpenAI route unavailable during validation",
                    }
                ],
                rationale_summary="Alex prefers OpenAI for general work with a local fallback.",
                created_by_type="user",
                created_by_ref=alex["user_id"],
            )
        )
        agent_preference = routing.create_preference(
            ModelPreferenceRequest(
                scope_type="agent",
                scope_ref=agent["agent_id"],
                purpose="drafting",
                provider="openai",
                model="gpt-5.4",
                fallback_routes=[
                    {
                        "provider": "local",
                        "model": "llama.cpp-default",
                        "reason": "Agent drafting can continue locally when cloud routing is unavailable",
                    }
                ],
                rationale_summary="Agent drafts on OpenAI first, then local if the preferred route is unavailable.",
                created_by_type="user",
                created_by_ref=alex["user_id"],
            )
        )
        task_preference = routing.create_preference(
            ModelPreferenceRequest(
                scope_type="task",
                scope_ref="task:v1-chunk7-sensitive-summary",
                purpose="sensitive_summary",
                provider="openai",
                model="gpt-5.4",
                fallback_routes=[],
                rationale_summary="This task explicitly requests OpenAI and must be policy-gated for private content.",
                created_by_type="user",
                created_by_ref=alex["user_id"],
            )
        )

        preferred = routing.route(
            ModelRouteRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                purpose="general",
                scope_type="user",
                scope_ref=alex["user_id"],
                content_classification="internal",
            )
        )
        preferred_decision = preferred["route_decision"]
        if preferred_decision["status"] != "selected":
            raise RuntimeError(f"Preferred route was not selected: {preferred_decision['status']}")
        if preferred_decision["model_preference_id"] != user_preference["model_preference_id"]:
            raise RuntimeError("Preferred route did not use the user-scoped preference")
        if preferred_decision["selected_provider"] != "openai":
            raise RuntimeError("Preferred route did not select OpenAI")
        if preferred_decision["fallback_used"]:
            raise RuntimeError("Preferred route incorrectly recorded fallback use")
        if preferred_decision["provenance_json"].get("preference_scope_type") != "user":
            raise RuntimeError("Preferred route provenance lost user scope attribution")

        fallback = routing.route(
            ModelRouteRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                requesting_agent_id=agent["agent_id"],
                purpose="drafting",
                scope_type="agent",
                scope_ref=agent["agent_id"],
                content_classification="internal",
                unavailable_provider_models={"openai:gpt-5.4"},
            )
        )
        fallback_decision = fallback["route_decision"]
        if fallback_decision["status"] != "selected":
            raise RuntimeError(f"Fallback route was not selected: {fallback_decision['status']}")
        if fallback_decision["model_preference_id"] != agent_preference["model_preference_id"]:
            raise RuntimeError("Fallback route did not use the agent-scoped preference")
        if fallback_decision["selected_provider"] != "local":
            raise RuntimeError("Fallback route did not select the local provider")
        if not fallback_decision["fallback_used"]:
            raise RuntimeError("Fallback route did not record fallback_used")
        if "fallback" not in fallback_decision["disclosure_summary"].lower():
            raise RuntimeError("Fallback route did not disclose fallback behavior")
        if not fallback_decision["provenance_json"].get("fallback_disclosed"):
            raise RuntimeError("Fallback route provenance did not record disclosure")

        approval_gated = routing.route(
            ModelRouteRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                purpose="sensitive_summary",
                scope_type="task",
                scope_ref="task:v1-chunk7-sensitive-summary",
                content_classification="private",
            )
        )
        approval_decision = approval_gated["route_decision"]
        if approval_decision["status"] != "awaiting_approval":
            raise RuntimeError(f"Private provider route was not approval-gated: {approval_decision['status']}")
        if approval_decision["model_preference_id"] != task_preference["model_preference_id"]:
            raise RuntimeError("Approval-gated route did not use the task-scoped preference")
        if not approval_decision["approval_record_id"]:
            raise RuntimeError("Approval-gated provider route did not create an approval record")
        if approval_decision["outcome_json"].get("selected"):
            raise RuntimeError("Approval-gated provider route was treated as selected")
        if approval_decision["provenance_json"].get("preference_scope_type") != "task":
            raise RuntimeError("Approval-gated route provenance lost task scope attribution")

        audits = store.list_records("audit_events", 1000)
        route_audits = [audit for audit in audits if audit["event_type"] == "model_route_decision_recorded"]
        policy_audits = [audit for audit in audits if audit["event_type"] == "policy_evaluated"]
        preference_audits = [audit for audit in audits if audit["event_type"] == "model_preference_created"]
        if len(route_audits) < 3:
            raise RuntimeError("Model route audit events were not recorded")
        if len(policy_audits) < 3:
            raise RuntimeError("Policy audit events were not recorded for model routes")
        if len(preference_audits) < 3:
            raise RuntimeError("Model preference audit events were not recorded")

        output = {
            "ok": True,
            "bounded_providers": [
                {
                    "provider": item["provider"],
                    "model": item["model"],
                    "trust_tier": item["trust_tier"],
                }
                for item in V1_MODEL_PROVIDERS
            ],
            "preferences": {
                "user_preference_id": user_preference["model_preference_id"],
                "agent_preference_id": agent_preference["model_preference_id"],
                "task_preference_id": task_preference["model_preference_id"],
            },
            "preferred_route": {
                "route_decision_id": preferred_decision["model_route_decision_id"],
                "status": preferred_decision["status"],
                "scope": {
                    "type": preferred_decision["scope_type"],
                    "ref": preferred_decision["scope_ref"],
                },
                "selected": f"{preferred_decision['selected_provider']}:{preferred_decision['selected_model']}",
                "policy_decision_id": preferred_decision["policy_decision_id"],
            },
            "fallback_route": {
                "route_decision_id": fallback_decision["model_route_decision_id"],
                "status": fallback_decision["status"],
                "scope": {
                    "type": fallback_decision["scope_type"],
                    "ref": fallback_decision["scope_ref"],
                },
                "preferred": f"{fallback_decision['preferred_provider']}:{fallback_decision['preferred_model']}",
                "selected": f"{fallback_decision['selected_provider']}:{fallback_decision['selected_model']}",
                "fallback_reason": fallback_decision["fallback_reason"],
                "disclosure": fallback_decision["disclosure_summary"],
            },
            "approval_gated_route": {
                "route_decision_id": approval_decision["model_route_decision_id"],
                "status": approval_decision["status"],
                "scope": {
                    "type": approval_decision["scope_type"],
                    "ref": approval_decision["scope_ref"],
                },
                "selected_provider": approval_decision["selected_provider"],
                "policy_decision_id": approval_decision["policy_decision_id"],
                "approval_record_id": approval_decision["approval_record_id"],
                "disclosure": approval_decision["disclosure_summary"],
            },
            "audit": {
                "model_preference_count": count(store, "model_provider_preferences"),
                "model_route_decision_count": count(store, "model_route_decisions"),
                "route_audit_count": len(route_audits),
                "policy_audit_count": len(policy_audits),
                "approval_record_count": count(store, "approval_records"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

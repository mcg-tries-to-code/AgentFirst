#!/usr/bin/env python3
"""Validate the governed live external research/provider path."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError

from agentfirst_storage import AgentFirstStore, PolicyEngine, ResearchService, TaskEngine


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-research-provider-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        admin = store.bootstrap_admin("Research Primary", "America/New_York")
        agent = store.insert(
            "agents",
            {
                "display_name": "Research Validation Agent",
                "owner_user_id": admin["user_id"],
                "persona_profile_json": {"validation": "final-v0-research-provider"},
                "capability_profile_json": {"live_external_research": True},
            },
            actor_type="system",
            actor_ref="research_validation",
        )
        project_note_ref = store.write_artifact(
            "projects/research-provider-proof.md",
            "Final v0 proof project for a governed live external research provider path.",
        )
        project = store.insert(
            "projects",
            {
                "name": "Final v0 Research Provider Proof",
                "description_ref": project_note_ref,
                "owner_scope_type": "user",
                "owner_scope_ref": admin["user_id"],
                "participants_json": [{"user_id": admin["user_id"]}, {"agent_id": agent["agent_id"]}],
                "goals_json": ["Prove one policy-aware live external research path."],
                "milestones_json": ["Policy decision recorded", "Live provider response persisted"],
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="research_validation",
        )

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "tool_provider",
                "destination_identity": "wikipedia-api",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="research_validation",
        )
        store.insert(
            "policies",
            {
                "policy_type": "global",
                "priority": 5,
                "rules_json": [
                    {
                        "action": "invoke_tool",
                        "classification": "public",
                        "destination_type": "tool_provider",
                        "destination_identity": "wikipedia-api",
                        "decision": "allow_with_logging",
                        "rationale": "Public live research through the approved Wikipedia API is allowed with audit.",
                    },
                    {
                        "action": "invoke_tool",
                        "classification_floor": "private",
                        "destination_type": "tool_provider",
                        "destination_identity": "wikipedia-api",
                        "decision": "require_primary_user_approval",
                        "rationale": "Private or higher content may not be sent to external research providers silently.",
                    },
                ],
                "targets_json": ["tool_invocation", "research_run", "search_run"],
                "status": "active",
            },
            actor_type="system",
            actor_ref="research_validation",
        )

        task_engine = TaskEngine(store)
        commitment = task_engine.create_commitment(
            title="Research SQLite write-ahead logging through a live public provider",
            commitment_type="research",
            owner_scope_type="agent",
            owner_scope_ref=agent["agent_id"],
            project_id=project["project_id"],
            priority=2,
            next_action="Run a governed external research search and persist provenance.",
            review_at="2026-04-23T15:00:00Z",
            completion_criteria={
                "required": [
                    "policy decision",
                    "tool invocation",
                    "live provider search result",
                    "search/research provenance",
                ]
            },
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        active_commitment = task_engine.activate_commitment(
            commitment["commitment_id"],
            next_action="Call the live provider after policy evaluation.",
            review_at="2026-04-23T15:00:00Z",
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        research_service = ResearchService(store, PolicyEngine(store))
        try:
            result = research_service.run_external_search_research(
                question="Find public background material on SQLite write-ahead logging.",
                query="SQLite write-ahead logging",
                requestor_user_id=admin["user_id"],
                sponsoring_agent_id=agent["agent_id"],
                actor_type="agent",
                actor_ref=agent["agent_id"],
                project_id=project["project_id"],
                commitment_id=active_commitment["commitment_id"],
                classification="public",
                limit=3,
            )
        except URLError as exc:
            raise RuntimeError(
                "Live external provider validation could not reach wikipedia-api. "
                "This script is intentionally live-by-default and does not fall back to fixtures."
            ) from exc

        research = result["research_run"]
        search = result["search_run"]
        policy_decision = result["policy_result"]["decision"]
        policy_audit = result["policy_result"]["audit_event"]
        invocation = result["tool_invocation"]
        audit = result["audit_event"]
        provider_response = result["provider_response"]

        if policy_decision["decision"] not in {"allow", "allow_with_logging"}:
            raise RuntimeError(f"Expected allowed public provider policy decision, got {policy_decision['decision']}")
        if invocation["status"] != "completed":
            raise RuntimeError(f"Expected completed tool invocation, got {invocation['status']}")
        if research["status"] != "completed" or not research["search_refs_json"]:
            raise RuntimeError("Research run did not complete with a linked search run")
        if search["provider"] != "wikipedia-api" or search["status"] != "returned":
            raise RuntimeError("Search run did not record the live provider result")
        if not provider_response.results:
            raise RuntimeError("Live provider returned no results")
        if not search["request_context_json"].get("policy_decision_id"):
            raise RuntimeError("Search run lacks policy decision provenance")
        if policy_decision["policy_decision_id"] not in invocation["policy_decision_refs_json"]:
            raise RuntimeError("Tool invocation is not linked to the policy decision")
        if audit["policy_decision_id"] != policy_decision["policy_decision_id"]:
            raise RuntimeError("External research audit is not linked to the policy decision")
        if result["progress_update"] is None:
            raise RuntimeError("Research result was not attached back to the commitment")

        proof = task_engine.record_completion_proof(
            active_commitment["commitment_id"],
            evidence_refs=[
                research["research_run_id"],
                search["search_run_id"],
                invocation["tool_invocation_id"],
                policy_decision["policy_decision_id"],
                audit["audit_event_id"],
                result["results_ref"],
                result["output_ref"],
            ],
            verified_by_type="agent",
            verified_by_ref=agent["agent_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        completed = task_engine.complete_commitment(
            active_commitment["commitment_id"],
            proof_id=proof["completion_proof_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )
        if completed["status"] != "completed":
            raise RuntimeError("Research commitment did not complete")

        output = {
            "ok": True,
            "live_external_provider": True,
            "provider": {
                "name": provider_response.provider,
                "destination_identity": "wikipedia-api",
                "http_status": provider_response.status_code,
                "result_count": len(provider_response.results),
                "first_result_title": provider_response.results[0]["title"],
            },
            "records": {
                "project_id": project["project_id"],
                "commitment_id": completed["commitment_id"],
                "research_run_id": research["research_run_id"],
                "search_run_id": search["search_run_id"],
                "tool_invocation_id": invocation["tool_invocation_id"],
                "policy_decision_id": policy_decision["policy_decision_id"],
                "policy_audit_event_id": policy_audit["audit_event_id"],
                "research_audit_event_id": audit["audit_event_id"],
                "completion_proof_id": proof["completion_proof_id"],
            },
            "linkage": {
                "research_attached_to_project": research["scope_json"]["project_id"] == project["project_id"],
                "research_attached_to_commitment": research["scope_json"]["commitment_id"]
                == completed["commitment_id"],
                "search_links_policy_decision": search["request_context_json"]["policy_decision_id"]
                == policy_decision["policy_decision_id"],
                "tool_links_policy_decision": policy_decision["policy_decision_id"]
                in invocation["policy_decision_refs_json"],
                "audit_links_policy_decision": audit["policy_decision_id"] == policy_decision["policy_decision_id"],
                "commitment_completed_with_research_proof": completed["status"] == "completed",
            },
            "real_vs_stubbed": {
                "real": [
                    "Policy evaluated before the external HTTP request",
                    "Live HTTPS request made to the public Wikipedia API",
                    "Search and research rows persisted with provider provenance",
                    "Tool invocation, policy decision, audit, project, and commitment records linked",
                ],
                "stubbed_or_not_exercised": [
                    "No private data is sent in this validation scenario",
                    "No secret-bearing provider is used",
                    "No Telegram live send is part of this validation",
                ],
            },
            "event_log_rows": len(store.list_records("event_log", 1000)),
            "recommendation": "With this live provider path plus the prior staged proofs, AgentFirst v0 can be called operationally complete for the non-secret research/provider requirement; Telegram live delivery remains separately proven outside this repo.",
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        message = str(exc)
        if "Live external provider validation could not reach" not in message:
            raise
        print(
            json.dumps(
                {
                    "ok": False,
                    "live_external_provider": False,
                    "provider": "wikipedia-api",
                    "failure": message,
                    "fixture_fallback_used": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        sys.exit(1)

#!/usr/bin/env python3
"""Validate V1 Chunk 8 governable memory, retrieval, search, and research."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentfirst_storage import (
    AgentFirstStore,
    MemoryRetrievalRequest,
    MemoryScope,
    MemoryService,
    PolicyEngine,
    ResearchService,
)
from agentfirst_storage.research import SearchProviderResponse
from agentfirst_storage.store import new_id


class FixtureSearchProvider:
    provider_name = "wikipedia-api"
    destination_type = "tool_provider"
    destination_identity = "wikipedia-api"
    endpoint = "fixture://wikipedia-api/search"

    def search(self, query: str, *, limit: int = 3) -> SearchProviderResponse:
        results = [
            {
                "title": "Retrieval-augmented generation",
                "page_id": 12345,
                "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
                "snippet": "Retrieval-augmented generation combines retrieval with generated responses.",
                "word_count": 600,
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ][:limit]
        return SearchProviderResponse(
            provider=self.provider_name,
            query=query,
            request_url=f"{self.endpoint}?q={query}",
            status_code=200,
            fetched_at="2026-04-22T12:00:00.000Z",
            results=results,
            raw={"fixture": True, "query": query, "result_count": len(results)},
        )


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-chunk8-") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()

        primary = store.bootstrap_admin("V1 Chunk 8 Primary", "America/New_York")
        alex = store.create_user(
            display_name="Alex Memory Owner",
            authority_tier="standard",
            default_timezone="America/New_York",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        blair = store.create_user(
            display_name="Blair Boundary Tester",
            authority_tier="standard",
            default_timezone="America/Chicago",
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        agent = store.insert(
            "agents",
            {
                "agent_id": new_id("agt"),
                "display_name": "Alex Research Agent",
                "owner_user_id": alex["user_id"],
                "persona_profile_json": {"purpose": "chunk8 validation"},
                "capability_profile_json": {},
                "tool_policy_bindings_json": [],
                "memory_bindings_json": [],
                "model_routing_policy_json": {},
                "status": "active",
            },
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        shared = store.insert(
            "shared_contexts",
            {
                "shared_context_id": new_id("shctx"),
                "name": "Chunk 8 Shared Space",
                "context_type": "team",
                "visibility_model": "shared-members",
                "governance_policy_refs_json": [],
                "status": "active",
            },
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        store.add_shared_context_member(
            shared["shared_context_id"],
            "user",
            alex["user_id"],
            actor_type="user",
            actor_ref=primary["user_id"],
        )
        project = store.insert(
            "projects",
            {
                "project_id": new_id("proj"),
                "name": "Chunk 8 Retrieval Project",
                "owner_scope_type": "user",
                "owner_scope_ref": alex["user_id"],
                "participants_json": [{"user_id": alex["user_id"]}, {"agent_id": agent["agent_id"]}],
                "goals_json": ["Validate scoped retrieval and cited research provenance."],
                "milestones_json": ["Allowed retrieval", "Denied retrieval", "Cited search result"],
                "policy_refs_json": [],
                "status": "active",
            },
            actor_type="user",
            actor_ref=alex["user_id"],
        )

        memory = MemoryService(store)
        private_memory = memory.create_memory(
            owner_scope_type="user",
            owner_scope_ref=alex["user_id"],
            memory_type="preference",
            body="Alex private deployment note: vector retrieval must use explicit scope gates.",
            canonicality="canonical",
            source_refs=["note://alex/private/retrieval"],
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        shared_memory = memory.create_memory(
            owner_scope_type="shared_context",
            owner_scope_ref=shared["shared_context_id"],
            memory_type="team_note",
            body="Shared team note: project research results require citations and source provenance.",
            canonicality="derived",
            source_refs=["note://shared/research/provenance"],
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        project_memory = memory.create_memory(
            owner_scope_type="project",
            owner_scope_ref=project["project_id"],
            memory_type="project_fact",
            body="Project fact: bounded retrieval validates one allowed result and one denied overreach.",
            canonicality="canonical",
            source_refs=["project://chunk8/fact"],
            actor_type="user",
            actor_ref=alex["user_id"],
        )
        agent_memory = memory.create_memory(
            owner_scope_type="agent",
            owner_scope_ref=agent["agent_id"],
            memory_type="agent_note",
            body="Agent note: retrieval summaries must preserve memory_id and content_ref provenance.",
            canonicality="scratch",
            source_refs=["agent://chunk8/note"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
        )

        allowed = memory.retrieve(
            MemoryRetrievalRequest(
                actor_user_id=alex["user_id"],
                sponsoring_user_id=alex["user_id"],
                query="vector retrieval explicit scope",
                scopes=[MemoryScope("user", alex["user_id"])],
                limit=3,
            )
        )
        allowed_retrieval = allowed["retrieval"]
        if allowed_retrieval["status"] != "returned":
            raise RuntimeError("Allowed private scoped retrieval did not return results")
        if allowed["results"][0]["memory_id"] != private_memory["memory_id"]:
            raise RuntimeError("Allowed retrieval did not return the expected private memory")
        if allowed["results"][0]["owner_scope_ref"] != alex["user_id"]:
            raise RuntimeError("Allowed retrieval crossed the requested user scope")
        if not allowed_retrieval["authority_policy_decision_refs_json"]:
            raise RuntimeError("Allowed retrieval is not authority-linked")
        if allowed["results"][0]["provenance"].get("memory_id") != private_memory["memory_id"]:
            raise RuntimeError("Allowed retrieval result lost memory provenance")

        denied = memory.retrieve(
            MemoryRetrievalRequest(
                actor_user_id=blair["user_id"],
                sponsoring_user_id=blair["user_id"],
                query="vector retrieval explicit scope",
                scopes=[MemoryScope("user", alex["user_id"])],
                limit=3,
            )
        )
        denied_retrieval = denied["retrieval"]
        if denied_retrieval["status"] != "denied":
            raise RuntimeError("Cross-scope memory retrieval was not denied")
        if denied["results"]:
            raise RuntimeError("Denied cross-scope memory retrieval leaked results")
        if not denied_retrieval["denied_scopes_json"]:
            raise RuntimeError("Denied retrieval did not record denied scope details")
        if not denied_retrieval["authority_policy_decision_refs_json"]:
            raise RuntimeError("Denied retrieval is not authority-linked")

        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "tool_provider",
                "destination_identity": "wikipedia-api",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="v1_chunk8_validation",
        )
        research_service = ResearchService(store, PolicyEngine(store), FixtureSearchProvider())
        research_result = research_service.run_external_search_research(
            question="Find public background material on retrieval-augmented generation.",
            query="retrieval augmented generation",
            requestor_user_id=alex["user_id"],
            sponsoring_agent_id=agent["agent_id"],
            actor_type="agent",
            actor_ref=agent["agent_id"],
            project_id=project["project_id"],
            classification="public",
            limit=1,
        )
        research = research_result["research_run"]
        search = research_result["search_run"]
        provider_response = research_result["provider_response"]
        if research["status"] != "completed" or not research["citation_refs_json"]:
            raise RuntimeError("Research run did not complete with citation refs")
        provenance = search["request_context_json"].get("provenance", {})
        citations = search["request_context_json"].get("citations", [])
        if provenance.get("provider") != "wikipedia-api":
            raise RuntimeError("Search provenance lost provider attribution")
        if provenance.get("policy_decision_id") != research_result["policy_result"]["decision"]["policy_decision_id"]:
            raise RuntimeError("Search provenance lost policy decision linkage")
        if not citations or citations[0].get("url") != provider_response.results[0]["url"]:
            raise RuntimeError("Search result did not preserve cited source URL provenance")
        if citations[0].get("tool_invocation_id") != research_result["tool_invocation"]["tool_invocation_id"]:
            raise RuntimeError("Citation provenance lost tool invocation linkage")

        audits = store.list_records("audit_events", 1000)
        retrieval_audits = [audit for audit in audits if audit["event_type"] == "memory_retrieval_recorded"]
        authority_audits = [audit for audit in audits if audit["event_type"] == "authority_evaluated"]
        research_audits = [audit for audit in audits if audit["event_type"] == "external_research_completed"]
        if len(retrieval_audits) < 2:
            raise RuntimeError("Memory retrieval audit events were not recorded")
        if len(authority_audits) < 2:
            raise RuntimeError("Authority audits were not recorded for memory retrieval")
        if len(research_audits) < 1:
            raise RuntimeError("Research completion audit was not recorded")

        output = {
            "ok": True,
            "memory_scopes_seeded": {
                "private_user_memory_id": private_memory["memory_id"],
                "shared_memory_id": shared_memory["memory_id"],
                "project_memory_id": project_memory["memory_id"],
                "agent_memory_id": agent_memory["memory_id"],
            },
            "allowed_scoped_retrieval": {
                "retrieval_id": allowed_retrieval["retrieval_id"],
                "status": allowed_retrieval["status"],
                "result_refs": allowed_retrieval["result_refs_json"],
                "authority_policy_decision_refs": allowed_retrieval["authority_policy_decision_refs_json"],
                "first_result_provenance": allowed["results"][0]["provenance"],
            },
            "denied_cross_scope_retrieval": {
                "retrieval_id": denied_retrieval["retrieval_id"],
                "status": denied_retrieval["status"],
                "denied_scopes": denied_retrieval["denied_scopes_json"],
                "result_count": len(denied["results"]),
                "authority_policy_decision_refs": denied_retrieval["authority_policy_decision_refs_json"],
            },
            "provenance_aware_research": {
                "research_run_id": research["research_run_id"],
                "search_run_id": search["search_run_id"],
                "provider": provider_response.provider,
                "citation_refs": research["citation_refs_json"],
                "search_provenance": provenance,
                "first_citation": citations[0],
            },
            "audit": {
                "memory_retrieval_count": count(store, "memory_retrievals"),
                "memory_retrieval_audit_count": len(retrieval_audits),
                "authority_audit_count": len(authority_audits),
                "research_audit_count": len(research_audits),
                "policy_decision_count": count(store, "policy_decisions"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

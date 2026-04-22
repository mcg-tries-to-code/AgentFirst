"""Governed external research provider path for AgentFirst v0."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .policy import GovernedAction, PolicyEngine
from .store import AgentFirstStore, new_id


@dataclass(frozen=True)
class SearchProviderResponse:
    provider: str
    query: str
    request_url: str
    status_code: int
    fetched_at: str
    results: list[dict[str, Any]]
    raw: dict[str, Any]


class WikipediaSearchProvider:
    """Small no-secret live search provider using the public Wikipedia API."""

    provider_name = "wikipedia-api"
    destination_type = "tool_provider"
    destination_identity = "wikipedia-api"
    endpoint = "https://en.wikipedia.org/w/api.php"

    def __init__(self, timeout_seconds: float = 12.0):
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 3) -> SearchProviderResponse:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "utf8": "1",
            "srlimit": str(limit),
        }
        request_url = f"{self.endpoint}?{urlencode(params)}"
        request = Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AgentFirst-v0-research-validation/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
            payload = json.loads(body.decode("utf-8"))
            status_code = int(response.status)

        results = []
        for item in payload.get("query", {}).get("search", []):
            page_id = item.get("pageid")
            results.append(
                {
                    "title": item.get("title"),
                    "page_id": page_id,
                    "url": f"https://en.wikipedia.org/?curid={page_id}" if page_id else None,
                    "snippet": _clean_snippet(item.get("snippet", "")),
                    "word_count": item.get("wordcount"),
                    "timestamp": item.get("timestamp"),
                }
            )

        return SearchProviderResponse(
            provider=self.provider_name,
            query=query,
            request_url=request_url,
            status_code=status_code,
            fetched_at=_now(),
            results=results,
            raw=payload,
        )


class ResearchService:
    """Policy-gated service that records external search and research runs."""

    def __init__(
        self,
        store: AgentFirstStore,
        policy_engine: PolicyEngine | None = None,
        provider: WikipediaSearchProvider | None = None,
    ):
        self.store = store
        self.policy_engine = policy_engine or PolicyEngine(store)
        self.provider = provider or WikipediaSearchProvider()

    def run_external_search_research(
        self,
        *,
        question: str,
        query: str,
        requestor_user_id: str,
        sponsoring_agent_id: str,
        actor_type: str,
        actor_ref: str,
        project_id: str | None = None,
        commitment_id: str | None = None,
        classification: str = "public",
        limit: int = 3,
    ) -> dict[str, Any]:
        self.store.initialize()
        capability = self._ensure_capability(actor_type=actor_type, actor_ref=actor_ref)
        research = self.store.insert(
            "research_runs",
            {
                "requestor_user_id": requestor_user_id,
                "sponsoring_agent_id": sponsoring_agent_id,
                "question": question,
                "scope_json": {
                    "project_id": project_id,
                    "commitment_id": commitment_id,
                    "provider": self.provider.provider_name,
                    "live_external_provider": True,
                },
                "status": "started",
                "started_at": _now(),
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        input_ref = self.store.write_artifact(
            f"research/{research['research_run_id']}/provider-request.json",
            json.dumps(
                {
                    "provider": self.provider.provider_name,
                    "destination_type": self.provider.destination_type,
                    "destination_identity": self.provider.destination_identity,
                    "endpoint": self.provider.endpoint,
                    "query": query,
                    "limit": limit,
                    "question": question,
                    "classification": classification,
                    "project_id": project_id,
                    "commitment_id": commitment_id,
                    "live_external_provider": True,
                },
                indent=2,
                sort_keys=True,
            ),
        )

        policy_result = self.policy_engine.record_tool_invocation(
            GovernedAction(
                action_type="invoke_tool",
                actor_type=actor_type,
                actor_ref=actor_ref,
                sponsoring_user_id=requestor_user_id,
                object_type="research_run",
                object_ref=research["research_run_id"],
                destination_type=self.provider.destination_type,
                destination_identity=self.provider.destination_identity,
                content_classification=classification,
                metadata={
                    "provider": self.provider.provider_name,
                    "query": query,
                    "commitment_id": commitment_id,
                    "project_id": project_id,
                },
            ),
            capability["tool_capability_id"],
            input_ref=input_ref,
        )
        invocation = policy_result["tool_invocation"]
        if invocation["status"] != "policy_allowed":
            blocked = self.store.update(
                "research_runs",
                research["research_run_id"],
                {"status": "blocked_by_policy", "updated_at": _now()},
                actor_type=actor_type,
                actor_ref=actor_ref,
                event_type="research_blocked_by_policy",
            )
            return {"research_run": blocked, "policy_result": policy_result, "tool_invocation": invocation}

        try:
            provider_response = self.provider.search(query, limit=limit)
        except Exception as exc:
            self.store.update(
                "tool_invocations",
                invocation["tool_invocation_id"],
                {"status": "failed", "started_at": research["started_at"], "ended_at": _now()},
                actor_type=actor_type,
                actor_ref=actor_ref,
                event_type="tool_invocation_failed",
            )
            self.store.update(
                "research_runs",
                research["research_run_id"],
                {"status": "failed_provider_unavailable", "ended_at": _now(), "updated_at": _now()},
                actor_type=actor_type,
                actor_ref=actor_ref,
                event_type="research_provider_unavailable",
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "external_research_failed",
                    "actor_type": actor_type,
                    "actor_ref": actor_ref,
                    "object_type": "research_run",
                    "object_ref": research["research_run_id"],
                    "action_summary": f"Live external research failed through {self.provider.provider_name}.",
                    "outcome": "failed_provider_unavailable",
                    "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                    "metadata_json": {
                        "tool_invocation_id": invocation["tool_invocation_id"],
                        "provider": self.provider.provider_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "live_external_provider": True,
                    },
                },
                actor_type=actor_type,
                actor_ref=actor_ref,
                emit_event=False,
            )
            self.store.append_event(
                "external_research_failed",
                "research_run",
                research["research_run_id"],
                actor_type,
                actor_ref,
                {
                    "tool_invocation_id": invocation["tool_invocation_id"],
                    "audit_event_id": audit["audit_event_id"],
                    "provider": self.provider.provider_name,
                },
                audit_event_id=audit["audit_event_id"],
            )
            raise
        results_ref = self.store.write_artifact(
            f"research/{research['research_run_id']}/search-results.json",
            json.dumps(
                {
                    "provider": provider_response.provider,
                    "query": provider_response.query,
                    "request_url": provider_response.request_url,
                    "status_code": provider_response.status_code,
                    "fetched_at": provider_response.fetched_at,
                    "results": provider_response.results,
                    "raw": provider_response.raw,
                    "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                    "tool_invocation_id": invocation["tool_invocation_id"],
                },
                indent=2,
                sort_keys=True,
            ),
        )
        search = self.store.insert(
            "search_runs",
            {
                "query": query,
                "provider": provider_response.provider,
                "filters_json": {"limit": limit},
                "request_context_json": {
                    "research_run_id": research["research_run_id"],
                    "tool_invocation_id": invocation["tool_invocation_id"],
                    "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                    "project_id": project_id,
                    "commitment_id": commitment_id,
                    "live_external_provider": True,
                    "request_url": provider_response.request_url,
                },
                "results_ref": results_ref,
                "freshness_metadata_json": {
                    "fetched_at": provider_response.fetched_at,
                    "provider_status_code": provider_response.status_code,
                },
                "status": "returned",
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        output_ref = self.store.write_artifact(
            f"research/{research['research_run_id']}/summary.md",
            self._render_summary(question, provider_response.results),
        )
        notes_ref = self.store.write_artifact(
            f"research/{research['research_run_id']}/working-notes.md",
            self._render_notes(query, provider_response),
        )
        completed_research = self.store.update(
            "research_runs",
            research["research_run_id"],
            {
                "search_refs_json": [search["search_run_id"]],
                "source_refs_json": [results_ref],
                "working_notes_ref": notes_ref,
                "output_ref": output_ref,
                "citation_refs_json": [
                    result["url"] for result in provider_response.results if result.get("url")
                ],
                "status": "completed",
                "ended_at": _now(),
                "updated_at": _now(),
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="research_completed",
        )
        completed_invocation = self.store.update(
            "tool_invocations",
            invocation["tool_invocation_id"],
            {"output_ref": results_ref, "status": "completed", "started_at": research["started_at"], "ended_at": _now()},
            actor_type=actor_type,
            actor_ref=actor_ref,
            event_type="tool_invocation_completed",
        )
        audit = self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": "external_research_completed",
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "object_type": "research_run",
                "object_ref": research["research_run_id"],
                "action_summary": f"Completed live external research through {provider_response.provider}.",
                "outcome": "completed",
                "policy_decision_id": policy_result["decision"]["policy_decision_id"],
                "metadata_json": {
                    "search_run_id": search["search_run_id"],
                    "tool_invocation_id": invocation["tool_invocation_id"],
                    "results_ref": results_ref,
                    "result_count": len(provider_response.results),
                    "provider_status_code": provider_response.status_code,
                    "live_external_provider": True,
                },
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
            emit_event=False,
        )
        event_id = self.store.append_event(
            "external_research_completed",
            "research_run",
            research["research_run_id"],
            actor_type,
            actor_ref,
            {
                "search_run_id": search["search_run_id"],
                "tool_invocation_id": invocation["tool_invocation_id"],
                "audit_event_id": audit["audit_event_id"],
            },
            audit_event_id=audit["audit_event_id"],
        )
        progress = None
        if commitment_id:
            progress = self.store.insert(
                "progress_updates",
                {
                    "parent_type": "commitment",
                    "parent_ref": commitment_id,
                    "author_agent_id": sponsoring_agent_id,
                    "summary": f"Completed live external research via {provider_response.provider}.",
                    "detail_ref": output_ref,
                    "state_change_json": {
                        "research_run_id": research["research_run_id"],
                        "search_run_id": search["search_run_id"],
                    },
                },
                actor_type=actor_type,
                actor_ref=actor_ref,
            )

        return {
            "research_run": completed_research,
            "search_run": search,
            "policy_result": policy_result,
            "tool_invocation": completed_invocation,
            "audit_event": audit,
            "event_id": event_id,
            "progress_update": progress,
            "provider_response": provider_response,
            "results_ref": results_ref,
            "output_ref": output_ref,
        }

    def _ensure_capability(self, *, actor_type: str, actor_ref: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tool_capabilities
                WHERE name = ? AND provider = ?
                """,
                ("wikipedia_search", self.provider.provider_name),
            ).fetchone()
            if row:
                return self.store._decode_row(row)

        return self.store.insert(
            "tool_capabilities",
            {
                "name": "wikipedia_search",
                "provider": self.provider.provider_name,
                "input_schema_ref": "schema://tool/wikipedia_search/input",
                "output_schema_ref": "schema://tool/wikipedia_search/output",
                "policy_refs_json": [],
                "availability_status": "enabled",
                "risk_class": "medium",
                "audit_requirements_json": {"audit": "always", "live_external_provider": True},
            },
            actor_type=actor_type,
            actor_ref=actor_ref,
        )

    def _render_summary(self, question: str, results: list[dict[str, Any]]) -> str:
        lines = [f"# Research Summary", "", f"Question: {question}", "", "Live provider results:"]
        for index, result in enumerate(results, start=1):
            lines.extend(
                [
                    "",
                    f"{index}. {result.get('title')}",
                    f"   URL: {result.get('url')}",
                    f"   Snippet: {result.get('snippet')}",
                ]
            )
        return "\n".join(lines) + "\n"

    def _render_notes(self, query: str, response: SearchProviderResponse) -> str:
        return "\n".join(
            [
                "# Working Notes",
                "",
                f"Provider: {response.provider}",
                f"Query: {query}",
                f"Request URL: {response.request_url}",
                f"HTTP status: {response.status_code}",
                f"Fetched at: {response.fetched_at}",
                f"Result count: {len(response.results)}",
                "",
            ]
        )


def _clean_snippet(snippet: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(snippet))).strip()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

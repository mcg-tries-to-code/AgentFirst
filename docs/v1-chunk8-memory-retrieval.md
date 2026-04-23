# AgentFirst V1 Chunk 8 Governable Memory, Retrieval, Search, and Research

## Scope

V1 Chunk 8 adds a bounded memory and retrieval governance layer.

The implementation covers:
- explicit private user, shared context, project, and agent memory scopes
- governed retrieval requests that name the exact scopes being searched
- authority-linked retrieval decisions through existing policy decision and audit records
- no-result leakage on denied cross-scope retrieval
- provenance-bearing memory results and search/research citations

It intentionally does not implement broad ranking optimization, long-context orchestration, research dashboards, dynamic corpora, or live provider expansion.

## Memory Scope Model

Memory records continue to use canonical owner scope fields:
- `owner_scope_type`: `user`, `shared_context`, `project`, or `agent`
- `owner_scope_ref`: the owning object id
- `canonicality`: `canonical`, `mirror`, `derived`, `speculative`, or `scratch`
- `source_refs_json` and `content_ref` as provenance anchors

`MemoryService.retrieve` requires a `MemoryRetrievalRequest` with explicit `MemoryScope` entries. A retrieval with no scopes is invalid. V1 does not infer broad retrieval scope from ambient user identity.

## Retrieval Governance

Each requested scope is checked through `AuthorityEngine.evaluate` with action `read`.

Allowed scopes are searched only after all requested scopes pass authority. If any requested scope is denied, the retrieval is recorded as `denied` and returns no memory results. This is deliberately conservative: partial scoped search would be possible later, but V1 prioritizes preventing silent cross-scope leakage.

`memory_retrievals` records:
- actor and sponsoring user
- query
- requested, allowed, and denied scopes
- authority policy decision refs
- returned memory refs
- bounded retrieval provenance
- status: `returned`, `empty`, or `denied`

Every retrieval writes a `memory_retrieval_recorded` audit event and event-log entry.

## Authority Linkage

Authority decisions remain first-class `policy_decisions` with `action_type = authority:read`. Retrieval rows link those decision ids through `authority_policy_decision_refs_json`.

Project-owned memory is now supported by the authority resolver. Project visibility resolves through the project owner scope, including user-owned, shared-context-owned, or agent-owned projects.

## Search And Research Provenance

`ResearchService` now records bounded V1 provenance shape for search results:
- `bounded_version = v1-chunk8`
- provider and query
- request URL and fetched timestamp
- policy decision id
- tool invocation id
- cited source URL, title, provider page id, and provider timestamp where available

`search_runs.request_context_json` contains a `provenance` block and per-result `citations`. `research_runs.citation_refs_json` remains the compact citation URL list for existing callers.

## Non-Goals

This chunk does not implement:
- vector indexes or embedding providers
- cross-corpus synthesis
- long-context packing
- a full short-term / mid-term / long-term memory lifecycle with compaction between tiers
- checkpoint-on-`/new` or `/restart` before ephemeral conversational context is cleared
- lane reset semantics for long-lived independent chats
- external web search provider expansion beyond the existing research provider abstraction
- UI or dashboards for memory review

## Follow-on priorities

The next memory-specific operational slice should extend this bounded retrieval model into an explicit lifecycle:
- **short-term** active lane/session context that can be safely reset
- **mid-term** compacted resumable lane summaries to reduce context rot
- **long-term** curated durable memory for stable facts, preferences, and important decisions
- **checkpointing** before `/new` or `/restart`, preserving durable signal without blindly dumping transient context noise

This follow-on should remain distinct from canonical system-of-record state such as enrollments, approvals, secrets, projects, and audit history. AgentFirst should remember conversation appropriately without confusing memory with governed backend truth.

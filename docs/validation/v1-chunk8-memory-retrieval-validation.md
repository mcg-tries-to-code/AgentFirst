# AgentFirst V1 Chunk 8 Memory/Retrieval Validation

## Command

```bash
PYTHONPATH=src python scripts/validate_v1_chunk8_memory_retrieval.py
```

## Coverage

The validation proves:
- one correct private scoped retrieval for the owning user
- one denied cross-scope private retrieval by a different user with zero returned results
- one provenance-aware cited search/research result
- memory retrieval audit events
- authority policy-decision linkage for retrieval
- policy/tool/audit linkage for research search provenance

## Expected Result

The script prints JSON with `ok: true`.

Key output sections:
- `allowed_scoped_retrieval`
- `denied_cross_scope_retrieval`
- `provenance_aware_research`
- `audit`

## Notes

The research provider is fixture-backed in this validation so Chunk 8 can validate record shape and provenance without depending on network availability. Live provider behavior remains covered by `scripts/validate_research_provider.py`.

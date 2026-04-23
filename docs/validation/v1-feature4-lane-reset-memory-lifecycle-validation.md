# AgentFirst V1 Feature 4 Lane Reset and Memory Lifecycle Validation

## Validation Mode
This validation is bounded and local. It proves the narrowed post-spec Feature 4 slice without claiming a full memory engine, long-term promotion system, or wiki reconciliation path.

Executable check:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature4_lane_reset_memory_lifecycle.py
```

Latest run result:

```json
{
  "status": "ok",
  "checks": {
    "audit_events_recorded": true,
    "canonical_state_unchanged": true,
    "checkpoint_artifact_is_selective": true,
    "derived_memory_records_created_for_resumability": true,
    "lane_identity_canonical": true,
    "mid_term_checkpoint_records_exist": true,
    "new_checkpoints_before_clear": true,
    "restart_checkpoints_before_reinitialize": true,
    "short_term_active_context_represented": true,
    "wiki_mutation_absent": true
  }
}
```

## Scenarios Validated

### Scenario 1. Lane Identity Exists
The script runs `/lane` after local onboarding bootstrap.

Validated evidence:
- `conversation_lanes` contains one stable lane for the primary operator
- the lane has owner scope, lane key, role, behavior metadata, and channel-mapping metadata
- the command output reports `bounded_lane_identity_and_lifecycle_scaffold`

### Scenario 2. Short-Term Active Context Exists
The script appends two context items through `MemoryService.add_active_context_item`:
- one durable decision
- one ephemeral working note

Validated evidence:
- `lane_active_contexts` has an active context row
- context JSON declares `lifecycle_layer: short_term_active_context`
- the active context is scoped to the lane id

### Scenario 3. `/new` Checkpoints Before Clear
The script runs `/new` after seeding one durable and one ephemeral item.

Validated evidence:
- a `lane_checkpoints` row is created
- a checkpoint artifact is written under the artifact root
- the durable decision is preserved
- the ephemeral note text is absent from the checkpoint artifact
- the prior active context is marked `cleared`
- a new active context is created
- command output reports `fresh_conversation_working_set`

### Scenario 4. `/restart` Checkpoints Before Reinitialize
The script appends another durable item, then runs `/restart`.

Validated evidence:
- the lane id is unchanged
- a second `lane_checkpoints` row is created
- the prior active context is marked `reinitialized`
- a new active context is created
- command output reports `same_lane_runtime_reinitialized`

### Scenario 5. Mid-Term Checkpoint Representation
Each reset creates:
- a `lane_checkpoints` row with `lifecycle_layer: mid_term_checkpoint`
- a checkpoint artifact ref
- preserved item refs
- dropped ephemeral refs
- an empty `wiki_candidate_refs_json`

When durable signal exists, the reset also creates a derived `memory_records` row with source refs back to:
- `conversation_lane:<lane_id>`
- `lane_active_context:<active_context_id>`
- `lane_checkpoint:<checkpoint_id>`

### Scenario 6. Canonical and Wiki Boundaries
The script snapshots canonical users and onboarding bootstrap records before `/new`, then compares them after reset.

Validated evidence:
- users are unchanged
- onboarding bootstrap records are unchanged
- `knowledge_corpora` remains empty
- command output includes `wiki_mutation: not_performed`
- checkpoint artifacts include `wiki_candidate_status: not_emitted`

### Scenario 7. Audit Evidence
The script verifies two `lane_checkpoint_before_reset` audit events, one for `/new` and one for `/restart`.

## Commands Run

```bash
python3 -m compileall src scripts/validate_v1_feature4_lane_reset_memory_lifecycle.py
PYTHONPATH=src python3 scripts/validate_v1_feature4_lane_reset_memory_lifecycle.py
```

Both commands completed successfully.

## Residual Limits
This validation does not prove:
- production Telegram lane mapping
- full conversational replay
- semantic compaction by an LLM
- long-term promotion decisions
- wiki candidate emission
- wiki reconciliation or mutation
- coordinated retrieval across memory, wiki, and guidance

Those remain future slices.


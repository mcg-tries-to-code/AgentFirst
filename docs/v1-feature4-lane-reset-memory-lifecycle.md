# AgentFirst V1 Feature 4 Lane Reset and Memory Lifecycle

## Scope Delivered
Feature 4 implements the narrowed post-spec lane/reset and memory lifecycle scaffold.

Delivered in code:
- canonical lane identity rows in `conversation_lanes`
- short-term active lane context rows in `lane_active_contexts`
- mid-term checkpoint rows in `lane_checkpoints`
- checkpoint artifact files under the configured artifact root
- `/lane`, `/new`, and `/restart` command behavior through `MemoryService`
- transparent reset output that states what was checkpointed, dropped, and left untouched

This slice does not implement full long-term promotion, direct wiki writes, wiki reconciliation, remote lane routing, or Telegram lane administration.

## Lifecycle Representation
Feature 4 keeps the architecture's layer boundaries explicit.

Short-term active context:
- stored in `lane_active_contexts.context_json`
- scoped to one `conversation_lanes.lane_id`
- treated as resettable, high-churn working state
- not durable truth by default

Mid-term checkpoint:
- stored in `lane_checkpoints`
- writes a bounded JSON checkpoint artifact to `memory/lane_checkpoints/<lane_id>/<checkpoint_id>.json`
- preserves only context items marked as durable signal or durable memory kinds such as decisions, facts, preferences, questions, commitments, and summaries
- records dropped ephemeral item refs and reasons
- creates a derived `memory_records` row when durable signal exists, so later retrieval and promotion work has a resumable anchor

Long-term memory:
- remains represented by existing `memory_records`
- receives only derived summary anchors from this slice
- is not promoted or curated into final retained memory by Feature 4

Knowledge/wiki:
- is not mutated
- checkpoint artifacts explicitly mark `wiki_candidate_status` as `not_emitted`
- `lane_checkpoints.wiki_candidate_refs_json` remains empty in this slice

Canonical operational state:
- users, onboarding, approvals, projects, secrets, and audit remain outside memory
- resets record audit/event evidence but do not mutate canonical operating truth

## Lane Identity
`conversation_lanes` provides bounded canonical identity for long-lived conversational lanes:
- stable `lane_id`
- owner scope: `user`, `agent`, `shared_context`, or `project`
- lane key such as `operator-default`
- display name
- role
- behavior metadata
- future channel mapping metadata

The current command surface uses the primary operator's default lane. Future Telegram routing can map Telegram chat/thread identity into the lane metadata without changing reset semantics.

## Command Behavior
`/lane`:
- creates or reads the primary operator default lane
- returns lane identity
- returns the current active short-term context
- returns recent checkpoint metadata
- does not reset or promote memory

`/new`:
- checkpoints selected durable signal from the active context
- marks the old active context as `cleared`
- creates a new empty active context generation
- keeps the lane identity stable
- does not erase memory records, canonical state, wiki state, or shared guidance
- reports reset semantics as `fresh_conversation_working_set`

`/restart`:
- checkpoints selected durable signal from the active context
- marks the old active context as `reinitialized`
- creates a new empty runtime context generation for the same lane
- keeps the lane identity stable
- does not erase memory records, canonical state, wiki state, or shared guidance
- reports reset semantics as `same_lane_runtime_reinitialized`

## Checkpoint Discipline
Checkpointing is selective. It does not dump raw transcript sprawl.

Preserved by default:
- items with `retention_intent` of `durable_signal`, `checkpoint`, `mid_term`, or `long_term_candidate`
- items with kind `decision`, `fact`, `preference`, `question`, `open_question`, `commitment`, or `summary`

Dropped by default:
- ordinary working notes
- transient phrasing
- items marked `ephemeral`
- low-signal context

The command output includes:
- preserved item count and refs
- summary artifact ref
- derived memory record id when one was created
- dropped ephemeral count and refs
- untouched stores and layers
- explicit `wiki_mutation: not_performed`

## Boundaries Preserved
Feature 4 preserves the four-layer architecture:
- canonical state remains system-of-record state
- memory owns active context and checkpoints
- wiki remains a separate reconciliation surface
- shared guidance remains separate from memory and wiki

The implementation intentionally avoids:
- direct wiki writes
- full wiki candidate emission
- full long-term promotion
- cross-channel lane routing
- treating checkpoint summaries as canonical truth
- replacing audit or canonical state with memory text

## Validation
Executable validation lives at:

```bash
PYTHONPATH=src python3 scripts/validate_v1_feature4_lane_reset_memory_lifecycle.py
```

The script proves:
- bounded lane identity exists
- short-term active context exists
- `/new` checkpoints before clearing
- `/restart` checkpoints before runtime reinitialization
- checkpoint artifacts preserve durable signal and omit ephemeral text
- canonical user/onboarding state is unchanged by reset
- no knowledge/wiki corpora are written
- audit events are recorded for checkpoint-before-reset behavior


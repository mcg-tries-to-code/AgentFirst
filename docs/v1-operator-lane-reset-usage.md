# AgentFirst V1 Operator Lane Reset Usage

## Commands

Inspect the current default operator lane:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /lane
```

Start a fresh working set after checkpointing durable signal:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /new
```

Restart runtime state for the same lane after checkpointing durable signal:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /restart
```

## Required State
Lane commands require a primary operator user. If the store has not been bootstrapped, run onboarding first:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /onboard bootstrap \
  --operator-display-name "Primary Operator" \
  --custody-mode operator-passphrase \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled
```

## What `/new` Does
`/new`:
- creates a checkpoint artifact from selected durable short-term signal
- marks the prior active context as `cleared`
- creates a new empty active context
- preserves the lane id
- leaves canonical state, long-term memory, wiki, and shared guidance untouched

Use `/new` when the current conversation should stop influencing the next working set except through the checkpointed durable signal.

## What `/restart` Does
`/restart`:
- creates a checkpoint artifact from selected durable short-term signal
- marks the prior active context as `reinitialized`
- creates a new empty active context for the same lane
- preserves the lane id
- leaves canonical state, long-term memory, wiki, and shared guidance untouched

Use `/restart` when the same lane should continue, but runtime working state should be reinitialized.

## Output To Inspect
Both reset commands return `transparent_checkpoint_output` with:
- `checkpointed.count`
- `checkpointed.summary_ref`
- `checkpointed.memory_record_id`
- `dropped_ephemeral.count`
- `left_untouched`
- `wiki_mutation`
- `reset_semantics`

The summary ref points at a bounded JSON artifact under the configured artifact root. It is intended for resumability and inspection, not raw transcript archiving.

## Current Limits
This slice does not:
- route remote Telegram `/new` or `/restart`
- switch between multiple operator-selected lanes
- promote checkpoints into curated long-term memory
- emit or reconcile wiki candidates
- write wiki pages


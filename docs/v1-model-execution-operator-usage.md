# AgentFirst V1 Model Execution Operator Usage

## Scope

This slice adds governed model execution after model routing. Model queries remain `query_model` governed actions. The system does not execute a model unless routing selects a provider/model and policy allows it.

## Catalogs

Show the bounded point-in-time catalog:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model catalog
```

The catalog includes OpenAI, Anthropic, Google, and local placeholder entries. It is a snapshot, not a promise of current account availability.

## Readiness

Show local lane readiness:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model readiness --provider openai
```

Readiness checks do not read or print secret plaintext. They report whether required secret handles, binaries, and local configuration markers are present.

## OpenAI API Lane

Store an OpenAI API key in the local encrypted secret broker:

```bash
printf '%s' "$OPENAI_API_KEY" | PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  secret put \
  --handle openai.api_key \
  --kind api_key \
  --integration model_provider \
  --owner-type system \
  --owner-ref operator \
  --stdin
```

Run a governed OpenAI API execution:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model execute \
  --lane api \
  --prompt 'Return one short sentence confirming live execution.'
```

Expected result when configured: `ok=true`, `real_execution=true`, and `lane=api`.

Expected result when the secret is absent or invalid: `ok=false`, `real_execution=false`, with a disclosure that no live API execution occurred.

## OpenAI Codex CLI Lane

Check readiness first:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model readiness --provider openai
```

Run a governed Codex CLI execution:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model execute \
  --lane codex_cli \
  --prompt 'Return one short sentence confirming Codex CLI execution.'
```

This lane is subscription-backed through the local Codex CLI. If the `codex` binary or local configuration marker is absent, readiness and execution output say so instead of pretending the lane is live.

## Anthropic And Google

Anthropic and Google are present in the provider catalog with secret and CLI lane requirements:
- Anthropic API key lane and Claude Code CLI lane
- Google API credential lane and Antigravity CLI lane

Their live adapters are not implemented in this slice. Readiness can report missing or present local prerequisites, but execution returns `real_execution=false` until those adapters are implemented and validated.

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_model_execution.py
PYTHONPATH=src python3 scripts/validate_v1_chunk7_model_routing.py
```

The model execution validation uses an injected OpenAI API transport. It proves the governed execution path and audit persistence without sending a real external provider call.

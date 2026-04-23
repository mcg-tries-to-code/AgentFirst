# AgentFirst V1 Current Local Test Guide

## Status
**Completed:** 2026-04-22
**Outcome:** **PASS for bounded local acceptance** with a **CONDITIONAL GO** posture for the implemented slices, and **NO-GO for unqualified production launch**.

Completion evidence:
- manual/CLI guide completed end to end, including real `codex_cli` model execution proof
- validation scripts completed for Features 1-4, model execution, model routing, and bounded integration acceptance
- formal acceptance summary written to `docs/validation/v1-current-local-acceptance-summary-2026-04-22.md`

## Completion notes
- Live model execution was proven through the **OpenAI Codex CLI lane**, not the raw OpenAI API lane.
- The **OpenAI API lane** remains structurally supported but unconfigured in this local environment unless `secret://openai.api_key` is provided.
- External channels and non-OpenAI providers remain out of scope for this guide and should not be implied as locally proven.

## Purpose
This is the focused operator test guide for the **currently completed local build**, not the older full-V1 wish-list sweep.

It covers the bounded operational slices that are now implemented:
- Feature 1: onboarding/bootstrap
- Feature 2: doctor/bounded repair
- Feature 3: minimal command surface
- Feature 4: narrowed lane/reset and memory lifecycle scaffolding
- Model execution slice: governed OpenAI-first execution with provider catalog/readiness scaffolding

Use this guide at the desktop while walking through real local behavior with Jarvis step by step.

## What this guide does not try to prove
This guide does **not** attempt to prove:
- live Telegram routing and enrollment end to end
- BlueBubbles live behavior
- full Google Workspace live integration
- Anthropic or Google live model execution
- full wiki/knowledge reconciliation
- full long-term memory promotion
- remote multi-user production behavior

This is a **bounded local operator validation guide**.

## Important model-provider note
The repo now has a bounded provider catalog snapshot and an execution service.

What can be real:
- OpenAI API lane, when `secret://openai.api_key` is present in the secret broker and the account/model are valid
- OpenAI Codex CLI lane, when the local `codex` binary and configuration are present

What is structurally ready but not live-implemented:
- Anthropic API and Claude Code CLI lanes
- Google API credential and Antigravity CLI lanes

Provider catalogs are point-in-time snapshots, not claims of universal or future model availability.

## Test environment recommendation
Use a fresh local test store unless you explicitly want to test against an existing one.

Simple default local state path:
- `~/.agentfirst/agentfirst.sqlite3`
- `~/.agentfirst/artifacts`
- `~/.agentfirst/secure-secrets`

If you want a separate test location, use:

```bash
export AGENTFIRST_SECRET_PASSPHRASE='choose-a-local-test-passphrase'
export AGENTFIRST_HOME="$HOME/agentfirst-test"
mkdir -p "$AGENTFIRST_HOME"
```

Optional low-level overrides still exist:

```bash
export AF_DB="$HOME/agentfirst-test/agentfirst.sqlite3"
export AF_ARTIFACTS="$HOME/agentfirst-test/artifacts"
export AF_SECRETS="$HOME/agentfirst-test/secure-secrets"
```

All commands below can now be run in the simpler form, for example:

```bash
agentfirst tui
agentfirst onboarding
agentfirst doctor
agentfirst model readiness --provider openai
```

The older explicit module form still works when needed:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS"
```

## Pass / Hold / Fail
- **Pass**: behavior matches expectation and output is honest
- **Hold**: feature is behaving locally but external/live dependency is intentionally not under test
- **Fail**: behavior contradicts the implemented contract or silently blurs boundaries

---

## Test 0. Preflight
### Command
```bash
PYTHONPATH=src python3 -m compileall src
```

### Expected
- compile succeeds

### Why it matters
Confirms the local code is at least importable before you begin user-facing tests.

---

## Test 1. Help surface
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /help
```

### Expected
- JSON output
- bounded command list includes:
  - `/help`
  - `/status`
  - `/onboard`
  - `/doctor`
  - `/approve`
  - `/lane`
  - `/model`
  - `/new`
  - `/restart`
- output makes clear this is a bounded command surface, not a free-form control plane

---

## Test 2. Initial status before onboarding
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /status
```

### Expected
- system is not yet runnable
- onboarding/readiness reports missing bootstrap state honestly
- no fake "all good" posture

---

## Test 3. Onboarding/bootstrap
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /onboard bootstrap \
  --operator-display-name "Primary Operator" \
  --timezone America/New_York \
  --custody-mode operator-passphrase \
  --provider openai \
  --model gpt-5.4 \
  --channel local=enabled
```

### Expected
- primary operator is created or returned
- custody mode is explicit
- model/provider preference is recorded
- local channel choice is recorded
- readiness becomes runnable in bounded local form
- no secret plaintext is printed

### Optional variant
If you want to test Telegram readiness intent later, rerun onboarding with:
- `--channel telegram=deferred`

That keeps Telegram visible without forcing live-token handling yet.

---

## Test 4. Status after onboarding
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /status
```

### Expected
- onboarding section reports runnable bounded-local state
- doctor section should not show major blockers in the fresh setup
- operator counts should be present

---

## Test 5. Model routing proof, not live OpenAI connectivity
### Command
```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk7_model_routing.py
```

### Expected
- JSON output with `"ok": true`
- bounded providers include `openai:gpt-5.4`
- preferred route selects `openai:gpt-5.4`
- fallback route discloses movement to `local:llama.cpp-default`
- private provider route shows approval gating rather than silent execution

### Honest judgment
- **Pass** for governed provider/model routing
- **Hold** for live OpenAI connectivity; live OpenAI is tested separately below and requires local credentials or CLI configuration

### Why this matters
This confirms the current build can govern and record model-provider decisions honestly.
It does **not** confirm that AgentFirst can send a live prompt to OpenAI and receive a completion.

---

## Test 5A. Provider catalog and readiness
### Commands
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model catalog

PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model readiness --provider openai
```

### Expected
- catalog reports a snapshot version and disclosure
- OpenAI, Anthropic, Google, and local entries are visible
- readiness names missing secrets, binaries, or configuration markers plainly
- readiness does not print secret plaintext

---

## Test 5B. OpenAI API lane
### Secret setup
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

### Execution
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model execute \
  --lane api \
  --prompt 'Return one short sentence confirming live OpenAI execution.'
```

### Expected
- with valid key/model/account access: `ok=true`, `real_execution=true`, `lane=api`
- without valid setup: `ok=false`, `real_execution=false`, with a disclosure naming the missing or failed prerequisite
- route and policy evidence are recorded before execution

---

## Test 5C. Codex CLI lane
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  model execute \
  --lane codex_cli \
  --prompt 'Return one short sentence confirming Codex CLI execution.'
```

### Expected
- with local Codex CLI installed and configured: `ok=true`, `real_execution=true`, `lane=codex_cli`
- if binary/configuration is absent or the CLI fails: `ok=false`, `real_execution=false`
- output discloses that this lane is Codex CLI subscription-backed

---

## Test 5D. Execution validation script
### Command
```bash
PYTHONPATH=src python3 scripts/validate_v1_model_execution.py
```

### Expected
- JSON output with `"ok": true`
- fake OpenAI API transport proves the governed execution path without external network
- Google structural path returns unavailable instead of faking live execution
- `model_executions` and `model_execution_recorded` audit events are present

---

## Test 6. Doctor read-only health check
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /doctor
```

### Expected
- JSON output
- healthy fresh setup should be runnable
- no fabricated repairs
- findings clearly classified

---

## Test 7. Lane inspection
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /lane
```

### Expected
- lane identity exists
- output shows a stable lane id
- active short-term context exists, even if empty
- this is read-only inspection, not reset

---

## Test 8. `/new` reset behavior
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /new
```

### Expected
- command succeeds
- checkpoint is created before reset
- output explicitly reports:
  - what was checkpointed
  - what was dropped as ephemeral
  - what was left untouched
- lane identity remains stable
- wiki mutation is explicitly absent
- canonical state remains untouched

### Important note
If there is very little active context yet, the checkpoint may be mostly empty. That is acceptable as long as the behavior is honest.

---

## Test 9. `/restart` reset behavior
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /restart
```

### Expected
- checkpoint happens before reinitialization
- lane identity remains the same
- runtime/session context is reinitialized
- output explicitly distinguishes restart from `/new`
- no wiki mutation
- canonical state remains untouched

---

## Test 10. Post-reset lane inspection
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /lane
```

### Expected
- same lane id as before
- recent checkpoints visible
- active context generation changed after resets
- state remains coherent, not blended or corrupted

---

## Test 11. Explicit failure path
### Command
```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli \
  --db "$AF_DB" \
  --artifact-root "$AF_ARTIFACTS" \
  --secret-root "$AF_SECRETS" \
  command /unknown
```

### Expected
- explicit JSON failure
- no silent fallback
- no hidden side effects

---

## Optional Test 12. Bounded automated validations
If you want a quick confidence pass after manual checks:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk7_model_routing.py
python3 scripts/validate_v1_feature1_onboarding_bootstrap.py
python3 scripts/validate_v1_feature2_doctor_bounded_repair.py
python3 scripts/validate_v1_feature3_minimal_command_surface.py
python3 scripts/validate_v1_feature4_lane_reset_memory_lifecycle.py
```

### Expected
- all return status `ok`

---

## Completed execution order
This guide was completed in practice with the following local acceptance path:
1. Test 0, `compileall src`
2. Test 1, `/help`
3. Test 2, `/status` before onboarding
4. Test 3, `/onboard bootstrap`
5. Test 4, `/status` after onboarding
6. Test 5, governed model routing proof
7. Test 5A, provider catalog/readiness inspection
8. Test 5C, live `codex_cli` execution proof
9. Test 5D, model execution validation script
10. Test 6, `/doctor`
11. Test 7, `/lane`
12. Test 8, `/new`
13. Test 9, `/restart`
14. Test 10, `/lane` again
15. Test 11, explicit failure path
16. Optional validation scripts for Features 1-4 and chunk-level acceptance

This order is now a tested path rather than a speculative recommendation.

# AgentFirst V1 Feature 3 Minimal Command Surface

## Scope Delivered
Feature 3 adds a bounded local slash-command surface under:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli command /help
PYTHONPATH=src python3 -m agentfirst_storage.cli command /status
```

The surface is intentionally small. It routes explicit commands only, does not infer natural language, and does not create a second control plane.

## Command Set
Implemented commands:

- `/help`: returns the bounded command list, usage details, and the authority boundary.
- `/status`: reports real local state by reading Feature 1 onboarding status, Feature 2 doctor status, and trusted operator-store counts.
- `/onboard status`: delegates to `OnboardingService.status`.
- `/onboard bootstrap ...`: delegates to `OnboardingService.bootstrap`.
- `/doctor`: delegates to `DoctorService.run(fix=False)`.
- `/doctor --fix`: delegates to `DoctorService.run(fix=True)` and inherits Feature 2 bounded repair limits.
- `/approve list [--limit N]`: reads canonical approval records through `OperatorSurface`.
- `/approve approve|deny <approval_record_id> --actor <user_id> --confirm APPROVED|DENIED`: delegates to the existing trusted operator approval resolution logic.
- `/lane`: returns a read-only context placeholder that discloses lane/reset behavior is not implemented in Feature 3.

Explicit failures:

- `/new`: returns `not_implemented` and exits nonzero because memory/lane lifecycle behavior is out of scope.
- `/restart`: returns `not_implemented` and exits nonzero because memory/lane lifecycle behavior is out of scope.
- Any unsupported command returns `unsupported_command` and exits nonzero.

## Canonical Delegation
The new module is `src/agentfirst_storage/command_surface.py`.

It delegates rather than duplicating core behavior:

- Feature 1 onboarding: `OnboardingService`
- Feature 2 doctor and bounded repair: `DoctorService`
- approval listing and resolution: `OperatorSurface`
- status aggregation: `OnboardingService.status`, `DoctorService.run`, and `OperatorSurface.status_overview`

The existing direct CLI entry points remain available:

```bash
PYTHONPATH=src python3 -m agentfirst_storage.cli onboarding bootstrap ...
PYTHONPATH=src python3 -m agentfirst_storage.cli onboarding status
PYTHONPATH=src python3 -m agentfirst_storage.cli doctor
```

Feature 3 only fronts those canonical paths.

## Authority Boundaries
The command surface is local and trusted-operator oriented. It does not:

- route remote chat commands
- infer commands from ordinary text
- fabricate secrets
- bypass enrollment or approval requirements
- widen authority
- implement lane reset behavior
- implement `/new` or `/restart` memory lifecycle behavior

Delegated failures are returned as explicit JSON command failures. Reserved and unsupported commands do not silently fall through into side effects.

## Output Shape
Command output is JSON with stable top-level fields:

- `ok`
- `surface`
- `command` when a command was accepted
- `exit_code`
- `data`

Failures keep the same JSON envelope with `ok: false`, a machine-readable `data.error`, and a nonzero process exit code.

## Deferred By Design
Feature 3 does not implement:

- lane creation, switching, reset, or persistence
- `/new` checkpoint behavior
- `/restart` reload/reset behavior
- memory lifecycle scaffolding beyond explicit reserved-command failures
- remote command routing across Telegram, BlueBubbles, Google Chat, or other channels

Those should be handled in a later lane/reset and memory lifecycle feature without moving authority away from canonical services.

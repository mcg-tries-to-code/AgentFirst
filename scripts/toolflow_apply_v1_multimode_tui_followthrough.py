#!/usr/bin/env python3
"""Apply the multimode TUI follow-through repo updates.

This script is intentionally narrow. It aligns the chunk documentation and the
existing chunk-10 validation surface with the already-landed multimode TUI
implementation.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CHUNK_DOC = REPO / "docs" / "v1-chunk10-audit-tui.md"
VALIDATION_DOC = REPO / "docs" / "validation" / "v1-chunk10-audit-tui-validation.md"
VALIDATION_SCRIPT = REPO / "scripts" / "validate_v1_chunk10_audit_tui.py"

CHUNK_DOC_CONTENT = """# AgentFirst V1 Chunk 10 Auditability, Observability, Failure Handling, and Multimode Trusted TUI

## Scope

V1 Chunk 10 now represents a bounded **multimode** trusted local terminal shell.

The implementation covers:
- operator-mode status overview
- approvals review
- audit and event inspection
- user, channel identity, and enrollment inspection
- task, blocker, and project inspection
- explicit failure disclosure
- one consequential administrative action for approval resolution
- explicit shell mode switching between operator and chat scaffold surfaces
- a first visual-language overhaul for readability and role distinction

It intentionally does not implement remote dashboard collaboration, live notification routing, real channel-backed chat, or broad workflow administration.

## Shell model

The trusted local shell lives in `TrustedOperatorTUI` and reads canonical state through `OperatorSurface`.

The shell now has two explicit contexts:
- `operator`
- `chat`

These are shell contexts, not identical to command authority. Command results still report their actual outcome class:
- `READ-ONLY`
- `ADMIN`
- `CHAT-SCAFFOLD`
- `SHELL`

This distinction matters. Operator inspection stays truthful and non-mutating; chat remains an explicit scaffold and must not impersonate real channel behavior.

## Operator surface model

Read-only operator views remain pure inspection:
- `status`
- `approvals`
- `audit`
- `users`
- `tasks`
- `failures`

These views query trusted local SQLite state and do not write audit or event rows. Validation checks this by comparing audit and event counts before and after scripted inspection.

Consequential administration remains explicit:
- `admin approval approve <approval_record_id> --actor <user_id> --confirm APPROVED`
- `admin approval deny <approval_record_id> --actor <user_id> --confirm DENIED`

Admin commands require an active local operator user, require the assigned approver or primary user, and require a confirmation token matching the target outcome. Successful resolution updates `approval_records`, writes `operator_approval_resolved` to `audit_events`, and appends the same action to `event_log`.

## Chat scaffold boundary

The new chat mode is intentionally honest and narrow.

It may render:
- chat home/help
- scaffold status
- local drafts
- visual roles such as user input, assistant reply, and system guidance

It does **not**:
- connect to Telegram, BlueBubbles, Google Chat, email, or any live channel
- read live conversation history
- fabricate inbound messages
- generate or send assistant replies through a provider
- imply real delivery or synchronization

Current scaffold commands:
- `mode chat`
- `chat help`
- `chat status`
- `chat compose <text>`
- `mode operator`

## Failure disclosure

Failure disclosure remains explicit in both `status` and `failures`.

The bounded V1 failure sources remain:
- audit outcomes such as `deny`, `denied`, `failed`, `policy_denied`, and `authority_denied`
- blocked or failed commitments
- denied or failed tool invocations
- denied or failed Google Workspace actions
- denied or failed model route decisions
- suspended, revoked, or rebinding-required channel identities and enrollments

The surface treats blocked work and suspended enrollment as operator-visible degraded state, not as missing or silent data.

## Visual language

The shell still uses only the Python standard library, but it is no longer intentionally austere.

The multimode refresh adds:
- boxed screens
- explicit shell/result headers
- section headers
- badges for trust or boundary disclosures
- clearer distinction between guidance, commands, user input, assistant reply, and system guidance

The goal is not decoration for its own sake. The goal is to make authority, boundaries, and message roles legible at a glance.

## TUI shape

Start the shell with:

```bash
agentfirst tui
```

Or explicitly choose a starting mode:

```bash
agentfirst tui --mode operator
agentfirst tui --mode chat
```

Scripted commands remain supported:

```bash
agentfirst tui --command status --command failures
agentfirst tui --mode chat --command status
agentfirst tui --command "mode chat" --command "chat compose Review this later"
```

## Validation

Run:

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk10_audit_tui.py
```

The validation now proves:
- read-only operator commands remain available and non-mutating
- operator failure disclosure still exposes blocked work and suspended enrollment
- operator admin approval resolution still updates trusted local state and audit history
- shell mode switching works
- chat scaffold commands remain explicitly non-live
- chat scaffold commands do not mutate audit or event state
- local draft rendering remains a draft and reports `sent = false`

## Remaining boundaries

This chunk still does not implement a full terminal UI framework, search or filter pagination, portfolio analytics, real inbox synchronization, or remote multi-operator coordination.

Approval resolution remains the only consequential TUI administration path in this chunk. Additional admin paths should follow the same model: explicit `admin` command namespace, active local operator identity, authority check, confirmation token, audit event, and event-log linkage.
"""

VALIDATION_DOC_CONTENT = """# AgentFirst V1 Chunk 10 Validation

## Command

```bash
PYTHONPATH=src python3 scripts/validate_v1_chunk10_audit_tui.py
```

## Scenario

The validation creates trusted local state in a temporary SQLite store:
- primary user
- local operator user
- worker user
- active project
- blocked project commitment
- active blocker requiring human decision
- suspended Telegram enrollment and channel identity
- policy decision requiring approval

It then drives `TrustedOperatorTUI` through both shell contexts.

Operator commands exercised:
- `status`
- `approvals`
- `audit`
- `users`
- `tasks`
- `failures`
- `admin approval approve ... --confirm APPROVED`

Chat scaffold commands exercised:
- `mode chat`
- `chat status`
- `chat compose ...`
- `mode operator`

## Assertions

The validation asserts:
- all operator inspection commands report `READ-ONLY`
- read-only operator inspection does not change audit or event counts
- status and failure views disclose blocked work and suspended enrollment
- approvals view exposes the pending approval
- admin approval resolution reports `ADMIN`
- the approval is updated to `approved`
- `operator_approval_resolved` is written to audit history
- chat scaffold commands report truthful non-live metadata
- chat scaffold commands do not mutate audit or event counts
- chat draft rendering reports `sent = false`
- returning to operator mode yields the operator home surface rather than an error

## Expected result

The script prints JSON with `"ok": true`, the operator commands exercised, the chat commands exercised, the resolved approval id, failure-disclosure sources, and trusted-state counts.

## Boundary note

A passing validation here does **not** mean AgentFirst has live inbox or messaging support in the TUI. It means the multimode shell is truthful, visually structured, and functionally safe within the current bounded local implementation.
"""

VALIDATION_SCRIPT_CONTENT = """#!/usr/bin/env python3
\"\"\"Validate V1 Chunk 10 auditability, failure disclosure, and multimode trusted TUI.\"\"\"

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentfirst_storage import AgentFirstStore, GovernedAction, PolicyEngine, TrustedOperatorTUI
from agentfirst_storage.store import new_id


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix=\"agentfirst-v1-chunk10-\") as tmp:
        root = Path(tmp)
        store = AgentFirstStore(root / \"agentfirst.sqlite3\", root / \"artifacts\")
        store.initialize()

        primary = store.bootstrap_admin(\"V1 Chunk 10 Primary\", \"America/New_York\")
        operator = store.create_user(
            display_name=\"Trusted Local Operator\",
            authority_tier=\"administrator\",
            default_timezone=\"America/New_York\",
            actor_type=\"user\",
            actor_ref=primary[\"user_id\"],
        )
        worker = store.create_user(
            display_name=\"Chunk 10 Worker\",
            authority_tier=\"standard\",
            default_timezone=\"America/Chicago\",
            actor_type=\"user\",
            actor_ref=primary[\"user_id\"],
        )
        project = store.insert(
            \"projects\",
            {
                \"project_id\": new_id(\"proj\"),
                \"name\": \"Chunk 10 Operator Surface\",
                \"owner_scope_type\": \"user\",
                \"owner_scope_ref\": worker[\"user_id\"],
                \"participants_json\": [
                    {
                        \"participant_id\": new_id(\"part\"),
                        \"subject_type\": \"user\",
                        \"subject_ref\": worker[\"user_id\"],
                        \"role\": \"owner\",
                        \"permissions\": [\"read\", \"monitor\", \"intervene\", \"approve\", \"manage_membership\"],
                        \"status\": \"active\",
                        \"policy_refs\": [],
                        \"added_by_user_id\": worker[\"user_id\"],
                        \"added_at\": \"2026-04-22T12:00:00.000Z\",
                    }
                ],
                \"goals_json\": [\"Validate operator inspection and administrative resolution.\"],
                \"milestones_json\": [],
                \"policy_refs_json\": [],
                \"status\": \"active\",
            },
            actor_type=\"user\",
            actor_ref=worker[\"user_id\"],
        )
        commitment = store.insert(
            \"commitments\",
            {
                \"commitment_id\": new_id(\"com\"),
                \"title\": \"Resolve explicit Chunk 10 approval\",
                \"commitment_type\": \"validation\",
                \"owner_scope_type\": \"project\",
                \"owner_scope_ref\": project[\"project_id\"],
                \"project_id\": project[\"project_id\"],
                \"status\": \"blocked\",
                \"priority\": 2,
                \"next_action\": \"Trusted operator reviews failure and approval queues\",
                \"blocker_state_json\": {\"reason\": \"approval_required\", \"disclosure_required\": True},
                \"policy_refs_json\": [],
            },
            actor_type=\"user\",
            actor_ref=worker[\"user_id\"],
        )
        store.insert(
            \"blocker_records\",
            {
                \"blocker_id\": new_id(\"blk\"),
                \"commitment_id\": commitment[\"commitment_id\"],
                \"blocker_type\": \"approval\",
                \"summary\": \"Policy approval must be reviewed through the trusted local operator surface.\",
                \"evidence_refs_json\": [],
                \"resolution_options_json\": [{\"option\": \"approve\"}, {\"option\": \"deny\"}],
                \"requires_human_decision\": True,
                \"status\": \"active\",
            },
            actor_type=\"user\",
            actor_ref=worker[\"user_id\"],
        )
        enrollment = store.insert(
            \"channel_enrollments\",
            {
                \"enrollment_id\": new_id(\"enr\"),
                \"channel_type\": \"telegram\",
                \"address\": \"telegram:chunk10-worker\",
                \"user_id\": worker[\"user_id\"],
                \"state\": \"suspended\",
                \"challenge_status\": \"verified\",
                \"owner_approval_status\": \"approved\",
                \"status\": \"suspended\",
                \"metadata_json\": {\"reason\": \"validation failure disclosure\"},
            },
            actor_type=\"user\",
            actor_ref=primary[\"user_id\"],
        )
        store.insert(
            \"channel_identities\",
            {
                \"channel_identity_id\": new_id(\"chan\"),
                \"user_id\": worker[\"user_id\"],
                \"channel_type\": \"telegram\",
                \"address\": \"telegram:chunk10-worker\",
                \"enrollment_id\": enrollment[\"enrollment_id\"],
                \"enrollment_state\": \"suspended\",
                \"binding_generation\": 1,
                \"metadata_json\": {\"reason\": \"validation failure disclosure\"},
                \"routing_policy_refs_json\": [],
                \"status\": \"suspended\",
            },
            actor_type=\"user\",
            actor_ref=primary[\"user_id\"],
        )

        policy_result = PolicyEngine(store).evaluate_and_record(
            GovernedAction(
                action_type=\"export\",
                actor_type=\"user\",
                actor_ref=worker[\"user_id\"],
                sponsoring_user_id=worker[\"user_id\"],
                object_type=\"commitment\",
                object_ref=commitment[\"commitment_id\"],
                destination_type=\"external_workspace\",
                destination_identity=\"unknown-review-target\",
                content_classification=\"private\",
                metadata={\"chunk\": \"v1-chunk10\"},
            )
        )
        approval = policy_result[\"approval_record\"]
        if approval is None:
            raise RuntimeError(\"Validation setup did not create an approval record\")

        tui = TrustedOperatorTUI(store)
        audit_before = count(store, \"audit_events\")
        events_before = count(store, \"event_log\")
        read_results = tui.run_script([\"status\", \"approvals\", \"audit\", \"users\", \"tasks\", \"failures\"])
        audit_after_read = count(store, \"audit_events\")
        events_after_read = count(store, \"event_log\")
        if audit_before != audit_after_read or events_before != events_after_read:
            raise RuntimeError(\"Read-only TUI inspection mutated audit or event state\")
        if not all(result.mode == \"READ-ONLY\" for result in read_results):
            raise RuntimeError(\"A read-only TUI command did not report READ-ONLY mode\")
        status_result = read_results[0]
        if status_result.data[\"failure_disclosure_count\"] < 2:
            raise RuntimeError(\"Status view did not disclose representative failures\")
        failure_result = read_results[-1]
        failure_sources = {item[\"source\"] for item in failure_result.data[\"failures\"]}
        if \"commitments\" not in failure_sources or \"channel_enrollments\" not in failure_sources:
            raise RuntimeError(\"Failure view did not disclose blocked work and suspended enrollment\")
        approvals_result = read_results[1]
        if approvals_result.data[\"approvals\"][0][\"approval_record_id\"] != approval[\"approval_record_id\"]:
            raise RuntimeError(\"Approvals TUI view did not expose the trusted local approval\")
        if \"AgentFirst TUI\" not in status_result.text or \"[TRUSTED LOCAL]\" not in status_result.text:
            raise RuntimeError(\"Status view did not render the updated visual shell markers\")

        chat_audit_before = count(store, \"audit_events\")
        chat_events_before = count(store, \"event_log\")
        chat_mode_result = tui.handle_command(\"mode chat\")
        chat_status_result = tui.handle_command(\"chat status\")
        chat_compose_result = tui.handle_command(\"chat compose Draft a cautious reply later\")
        back_to_operator_result = tui.handle_command(\"mode operator\")
        chat_audit_after = count(store, \"audit_events\")
        chat_events_after = count(store, \"event_log\")
        if chat_audit_before != chat_audit_after or chat_events_before != chat_events_after:
            raise RuntimeError(\"Chat scaffold commands mutated audit or event state\")
        if chat_mode_result.mode != \"CHAT-SCAFFOLD\" or chat_status_result.mode != \"CHAT-SCAFFOLD\":
            raise RuntimeError(\"Chat scaffold commands did not report CHAT-SCAFFOLD mode\")
        if chat_status_result.data[\"chat\"][\"live_channel_integration\"] is not False:
            raise RuntimeError(\"Chat scaffold status blurred the no-live-channel boundary\")
        if chat_compose_result.data[\"sent\"] is not False:
            raise RuntimeError(\"Chat scaffold draft incorrectly claimed message delivery\")
        if chat_compose_result.data[\"draft\"] != \"Draft a cautious reply later\":
            raise RuntimeError(\"Chat scaffold draft did not preserve the drafted text\")
        if \"USER INPUT |\" not in chat_compose_result.text or \"SYSTEM GUIDANCE |\" not in chat_compose_result.text:
            raise RuntimeError(\"Chat scaffold did not render the expected visual role markers\")
        if back_to_operator_result.mode != \"READ-ONLY\":
            raise RuntimeError(\"Returning to operator mode did not restore the operator surface\")

        admin_result = tui.handle_command(
            \"admin approval approve \"
            f\"{approval['approval_record_id']} --actor {primary['user_id']} --confirm APPROVED\"
        )
        if admin_result.mode != \"ADMIN\":
            raise RuntimeError(\"Approval resolution did not report ADMIN mode\")
        resolved = store.get_by_id(\"approval_records\", approval[\"approval_record_id\"])
        if resolved is None or resolved[\"status\"] != \"approved\" or not resolved[\"resolved_at\"]:
            raise RuntimeError(\"TUI admin approval resolution did not update trusted local state\")
        audit_types = {
            audit[\"event_type\"]
            for audit in store.list_records(\"audit_events\", 1000)
            if audit[\"object_ref\"] == approval[\"approval_record_id\"]
        }
        if \"operator_approval_resolved\" not in audit_types:
            raise RuntimeError(\"TUI admin approval resolution did not write operator audit\")

        post_approvals = tui.handle_command(\"approvals\")
        if post_approvals.data[\"approvals\"][0][\"status\"] != \"approved\":
            raise RuntimeError(\"Post-admin TUI inspection did not show resolved approval\")

        output = {
            \"ok\": True,
            \"tui\": {
                \"operator_commands\": [result.title for result in read_results],
                \"chat_commands\": [
                    chat_mode_result.title,
                    chat_status_result.title,
                    chat_compose_result.title,
                    back_to_operator_result.title,
                ],
                \"read_only_mutated_audit_or_events\": False,
                \"chat_mutated_audit_or_events\": False,
                \"admin_command_title\": admin_result.title,
                \"admin_mode\": admin_result.mode,
            },
            \"approval\": {
                \"approval_record_id\": approval[\"approval_record_id\"],
                \"policy_decision_id\": approval[\"policy_decision_id\"],
                \"resolved_status\": resolved[\"status\"],
                \"operator_audit_recorded\": \"operator_approval_resolved\" in audit_types,
            },
            \"failure_disclosure\": {
                \"count\": status_result.data[\"failure_disclosure_count\"],
                \"sources\": sorted(failure_sources),
            },
            \"chat_scaffold\": {
                \"live_channel_integration\": chat_status_result.data[\"chat\"][\"live_channel_integration\"],
                \"history_loaded\": chat_status_result.data[\"chat\"][\"history_loaded\"],
                \"draft_sent\": chat_compose_result.data[\"sent\"],
            },
            \"trusted_state\": {
                \"users\": count(store, \"users\"),
                \"projects\": count(store, \"projects\"),
                \"commitments\": count(store, \"commitments\"),
                \"channel_enrollments\": count(store, \"channel_enrollments\"),
                \"audit_events\": count(store, \"audit_events\"),
                \"event_log\": count(store, \"event_log\"),
            },
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == \"__main__\":
    main()
"""


def main() -> None:
    CHUNK_DOC.write_text(CHUNK_DOC_CONTENT, encoding="utf-8")
    VALIDATION_DOC.write_text(VALIDATION_DOC_CONTENT, encoding="utf-8")
    VALIDATION_SCRIPT.write_text(VALIDATION_SCRIPT_CONTENT, encoding="utf-8")
    print(
        "Wrote multimode TUI follow-through updates:\n"
        f"- {CHUNK_DOC}\n"
        f"- {VALIDATION_DOC}\n"
        f"- {VALIDATION_SCRIPT}"
    )


if __name__ == "__main__":
    main()

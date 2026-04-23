#!/usr/bin/env python3
"""Validate V1 Feature 4 lane/reset and memory lifecycle scaffolding."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import AgentFirstStore  # noqa: E402
from agentfirst_storage.memory import MemoryService  # noqa: E402


def run_command(root: Path, args: list[str], env: dict[str, str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "agentfirst_storage.cli",
        "--db",
        str(root / "agentfirst.sqlite3"),
        "--artifact-root",
        str(root / "artifacts"),
        "--secret-root",
        str(root / "secure-secrets"),
        "command",
        *args,
    ]
    return subprocess.run(cmd, text=True, capture_output=True, check=check, env=env, cwd=str(ROOT))


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def read_artifact(content_ref: str, artifact_root: Path) -> dict:
    parsed = urlparse(content_ref)
    if parsed.scheme != "file":
        raise RuntimeError(f"expected file artifact ref, got {content_ref}")
    path = Path(parsed.path).resolve()
    if not str(path).startswith(str(artifact_root.resolve())):
        raise RuntimeError("checkpoint artifact escaped artifact root")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "AGENTFIRST_SECRET_PASSPHRASE": "feature4-validation-passphrase",
    }

    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature4-") as tmp:
        root = Path(tmp)
        secret_source = root / "trusted-local-secret.txt"
        secret_source.write_text("feature4-validation-token", encoding="utf-8")

        bootstrap = payload(
            run_command(
                root,
                [
                    "/onboard",
                    "bootstrap",
                    "--operator-display-name",
                    "Feature 4 Primary",
                    "--timezone",
                    "America/New_York",
                    "--custody-mode",
                    "operator-passphrase",
                    "--provider",
                    "openai",
                    "--model",
                    "gpt-5.4",
                    "--channel",
                    "local=enabled",
                    "--secret-file",
                    "telegram.bot.primary",
                    "bot_token",
                    "telegram",
                    str(secret_source),
                ],
                env,
            )
        )
        if not bootstrap["data"]["readiness"]["runnable"]:
            raise RuntimeError("bootstrap did not create runnable local state")

        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        service = MemoryService(store)
        lane_snapshot = payload(run_command(root, ["/lane"], env))
        if lane_snapshot["data"]["status"] != "active":
            raise RuntimeError("/lane did not create/read active lane state")
        lane_id = lane_snapshot["data"]["lane_state"]["lane"]["lane_id"]
        active_id = lane_snapshot["data"]["lane_state"]["active_context"]["active_context_id"]

        service.add_active_context_item(
            text="Decision: keep Telegram lane reset behavior bounded to local trusted command execution.",
            kind="decision",
            retention_intent="durable_signal",
            source_ref="validation:durable-decision",
            actor_ref="feature4.validation",
        )
        service.add_active_context_item(
            text="Noise: transient phrasing that should not survive reset.",
            kind="working_note",
            retention_intent="ephemeral",
            source_ref="validation:ephemeral-noise",
            actor_ref="feature4.validation",
        )

        before_users = store.list_records("users", 1000)
        before_bootstraps = store.list_records("onboarding_bootstraps", 1000)
        new_result = payload(run_command(root, ["/new"], env))
        transparent = new_result["data"]["transparent_checkpoint_output"]
        if transparent["checkpointed"]["count"] != 1:
            raise RuntimeError("/new did not preserve exactly one durable signal item")
        if transparent["dropped_ephemeral"]["count"] != 1:
            raise RuntimeError("/new did not disclose dropped ephemeral context")
        if "knowledge/wiki store" not in transparent["left_untouched"]:
            raise RuntimeError("/new did not disclose untouched wiki boundary")
        if transparent["reset_semantics"] != "fresh_conversation_working_set":
            raise RuntimeError("/new semantics were not distinct")
        if store.list_records("users", 1000) != before_users:
            raise RuntimeError("/new mutated canonical users")
        if store.list_records("onboarding_bootstraps", 1000) != before_bootstraps:
            raise RuntimeError("/new mutated onboarding canonical state")

        new_checkpoint = new_result["data"]["checkpoint"]
        new_artifact = read_artifact(new_checkpoint["summary_ref"], root / "artifacts")
        if "Noise: transient" in json.dumps(new_artifact):
            raise RuntimeError("checkpoint artifact retained ephemeral noise text")
        if new_artifact["wiki_candidate_status"] != "not_emitted":
            raise RuntimeError("checkpoint artifact implied wiki candidate emission")
        if new_checkpoint["memory_record_id"] is None:
            raise RuntimeError("/new did not create a derived memory record for resumable signal")
        if new_result["data"]["new_active_context"]["active_context_id"] == active_id:
            raise RuntimeError("/new did not create a fresh active context")

        service.add_active_context_item(
            text="Preference: after restart, retain the lane identity while reinitializing runtime state.",
            kind="preference",
            retention_intent="durable_signal",
            source_ref="validation:restart-preference",
            actor_ref="feature4.validation",
        )
        restart_result = payload(run_command(root, ["/restart"], env))
        restart_transparent = restart_result["data"]["transparent_checkpoint_output"]
        if restart_result["data"]["lane"]["lane_id"] != lane_id:
            raise RuntimeError("/restart did not preserve stable lane identity")
        if restart_transparent["reset_semantics"] != "same_lane_runtime_reinitialized":
            raise RuntimeError("/restart semantics were not distinct")
        if restart_transparent["checkpointed"]["count"] != 1:
            raise RuntimeError("/restart did not checkpoint durable signal")
        if restart_transparent["wiki_mutation"] != "not_performed":
            raise RuntimeError("/restart implied wiki mutation")

        lanes = store.list_records("conversation_lanes", 1000)
        active_contexts = store.list_records("lane_active_contexts", 1000)
        checkpoints = store.list_records("lane_checkpoints", 1000)
        memories = store.list_records("memory_records", 1000)
        corpora = store.list_records("knowledge_corpora", 1000)
        if len(lanes) != 1:
            raise RuntimeError(f"expected one lane, got {len(lanes)}")
        if len(checkpoints) != 2:
            raise RuntimeError(f"expected two checkpoints, got {len(checkpoints)}")
        if len([ctx for ctx in active_contexts if ctx["status"] == "active"]) != 1:
            raise RuntimeError("expected exactly one active short-term context")
        if len(memories) != 2:
            raise RuntimeError("expected two derived memory records from checkpoints")
        if corpora != []:
            raise RuntimeError("Feature 4 validation unexpectedly wrote wiki/knowledge corpora")

        audit_events = store.list_records("audit_events", 1000)
        reset_audits = [event for event in audit_events if event["event_type"] == "lane_checkpoint_before_reset"]
        if len(reset_audits) != 2:
            raise RuntimeError("expected checkpoint-before-reset audit events for /new and /restart")

        secret_source.unlink()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "checks": {
                        "lane_identity_canonical": True,
                        "short_term_active_context_represented": True,
                        "new_checkpoints_before_clear": True,
                        "restart_checkpoints_before_reinitialize": True,
                        "checkpoint_artifact_is_selective": True,
                        "mid_term_checkpoint_records_exist": True,
                        "derived_memory_records_created_for_resumability": True,
                        "canonical_state_unchanged": True,
                        "wiki_mutation_absent": True,
                        "audit_events_recorded": True,
                    },
                    "lane_id": lane_id,
                    "checkpoint_ids": [checkpoint["checkpoint_id"] for checkpoint in checkpoints],
                    "memory_record_ids": [memory["memory_id"] for memory in memories],
                    "active_context_statuses": sorted(ctx["status"] for ctx in active_contexts),
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

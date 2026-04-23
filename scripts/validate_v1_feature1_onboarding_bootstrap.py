#!/usr/bin/env python3
"""Validate V1 Feature 1 onboarding/bootstrap without printing secret plaintext."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import AgentFirstStore  # noqa: E402


TEST_SECRET = "feature1-validation-token-plaintext"


def run_cli(root: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
        *args,
    ]
    return subprocess.run(cmd, text=True, capture_output=True, check=True, env=env, cwd=str(ROOT))


def count(store: AgentFirstStore, table: str) -> int:
    return len(store.list_records(table, 1000))


def assert_no_secret_leak(result: subprocess.CompletedProcess[str]) -> None:
    if TEST_SECRET in result.stdout or TEST_SECRET in result.stderr:
        raise RuntimeError("onboarding command leaked plaintext secret in terminal output")


def assert_no_plaintext_in_state(root: Path) -> None:
    needle = TEST_SECRET.encode("utf-8")
    for state_root in [root / "secure-secrets", root / "artifacts"]:
        for path in state_root.rglob("*"):
            if path.is_file() and needle in path.read_bytes():
                raise RuntimeError(f"plaintext secret leaked into state file: {path}")
    db_bytes = (root / "agentfirst.sqlite3").read_bytes()
    if needle in db_bytes:
        raise RuntimeError("plaintext secret leaked into canonical SQLite database")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature1-onboarding-") as tmp:
        root = Path(tmp)
        secret_source = root / "trusted-local-secret.txt"
        secret_source.write_text(TEST_SECRET, encoding="utf-8")
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "AGENTFIRST_SECRET_PASSPHRASE": "feature1-validation-passphrase",
        }

        incomplete = run_cli(
            root,
            [
                "onboarding",
                "bootstrap",
                "--operator-display-name",
                "Feature 1 Primary",
                "--timezone",
                "America/New_York",
                "--custody-mode",
                "operator-passphrase",
                "--provider",
                "openai",
                "--model",
                "gpt-5.4",
                "--channel",
                "telegram=enabled",
            ],
            env,
        )
        incomplete_payload = json.loads(incomplete.stdout)
        if incomplete_payload["status"] != "incomplete":
            raise RuntimeError("onboarding did not honestly report missing Telegram secret")
        if "telegram_required_secret" not in incomplete_payload["readiness"]["missing"]:
            raise RuntimeError("readiness summary did not identify missing Telegram secret")

        complete = run_cli(
            root,
            [
                "onboarding",
                "bootstrap",
                "--operator-display-name",
                "Feature 1 Primary",
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
                "--channel",
                "telegram=enabled",
                "--channel",
                "bluebubbles=deferred",
                "--secret-file",
                "telegram.bot.primary",
                "bot_token",
                "telegram",
                str(secret_source),
            ],
            env,
        )
        assert_no_secret_leak(complete)
        complete_payload = json.loads(complete.stdout)
        if complete_payload["status"] != "ready" or not complete_payload["readiness"]["runnable"]:
            raise RuntimeError("onboarding with required secret did not become bounded-local ready")

        status = run_cli(root, ["onboarding", "status"], env)
        status_payload = json.loads(status.stdout)
        if not status_payload["bootstrapped"] or not status_payload["readiness"]["runnable"]:
            raise RuntimeError("onboarding status did not report latest ready bootstrap")

        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        if count(store, "users") != 1:
            raise RuntimeError("expected exactly one primary operator user")
        if count(store, "secret_records") != 1:
            raise RuntimeError("expected exactly one ingested secret metadata record")
        if count(store, "model_provider_preferences") < 1:
            raise RuntimeError("expected persisted model provider preference")
        if count(store, "onboarding_bootstraps") != 2:
            raise RuntimeError("expected incomplete and ready onboarding records")

        latest = status_payload["latest_bootstrap"]
        if latest["custody_mode"] != "operator_passphrase":
            raise RuntimeError("custody mode was not represented canonically")
        channel_states = {item["channel"]: item["state"] for item in latest["channels_json"]}
        if channel_states.get("telegram") != "enabled" or channel_states.get("bluebubbles") != "deferred":
            raise RuntimeError("channel enablement choices were not represented canonically")

        assert_no_plaintext_in_state(root)
        secret_source.unlink()

        result = {
            "status": "ok",
            "db": str(root / "agentfirst.sqlite3"),
            "checks": {
                "first_run_invocation": True,
                "primary_operator_persisted": True,
                "custody_choice_recorded": True,
                "trusted_local_secret_ingest_no_plaintext_output": True,
                "provider_model_persisted": True,
                "channel_choices_persisted": True,
                "readiness_missing_then_ready": True,
            },
            "counts": {
                "users": count(store, "users"),
                "secret_records": count(store, "secret_records"),
                "model_provider_preferences": count(store, "model_provider_preferences"),
                "onboarding_bootstraps": count(store, "onboarding_bootstraps"),
            },
            "latest_readiness": complete_payload["readiness"],
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

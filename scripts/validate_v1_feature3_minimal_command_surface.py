#!/usr/bin/env python3
"""Validate V1 Feature 3 minimal command surface."""

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


TEST_SECRET = "feature3-validation-token-plaintext"


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


def assert_no_secret_leak(result: subprocess.CompletedProcess[str]) -> None:
    if TEST_SECRET in result.stdout or TEST_SECRET in result.stderr:
        raise RuntimeError("command surface leaked plaintext secret in terminal output")


def main() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "AGENTFIRST_SECRET_PASSPHRASE": "feature3-validation-passphrase",
    }

    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature3-") as tmp:
        root = Path(tmp)
        secret_source = root / "trusted-local-secret.txt"
        secret_source.write_text(TEST_SECRET, encoding="utf-8")

        help_payload = payload(run_command(root, ["/help"], env))
        commands = {item["command"] for item in help_payload["data"]["commands"]}
        expected = {"/help", "/status", "/onboard", "/doctor", "/approve", "/new", "/restart", "/lane", "/model"}
        if commands != expected:
            raise RuntimeError(f"unexpected command set: {sorted(commands)}")
        if not help_payload["data"].get("authority_boundary"):
            raise RuntimeError("help output did not disclose authority boundary")

        bootstrap = run_command(
            root,
            [
                "/onboard",
                "bootstrap",
                "--operator-display-name",
                "Feature 3 Primary",
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
                "--secret-file",
                "telegram.bot.primary",
                "bot_token",
                "telegram",
                str(secret_source),
            ],
            env,
        )
        assert_no_secret_leak(bootstrap)
        bootstrap_payload = payload(bootstrap)
        if bootstrap_payload["command"] != "/onboard" or not bootstrap_payload["data"]["readiness"]["runnable"]:
            raise RuntimeError("/onboard bootstrap did not delegate to a runnable Feature 1 bootstrap")

        onboard_status = payload(run_command(root, ["/onboard", "status"], env))
        latest = onboard_status["data"]["latest_bootstrap"]
        if latest["created_by_ref"] != "command_surface./onboard.bootstrap":
            raise RuntimeError("/onboard status did not read command-surface-created canonical bootstrap")

        doctor = payload(run_command(root, ["/doctor"], env))
        if doctor["command"] != "/doctor" or not doctor["data"]["runnable"]:
            raise RuntimeError("/doctor did not delegate to healthy Feature 2 doctor output")
        if not any(item["check"] == "onboarding_bootstrap" for item in doctor["data"]["findings"]):
            raise RuntimeError("/doctor output did not include canonical onboarding inspection")

        status = payload(run_command(root, ["/status"], env))
        if not status["data"]["runnable"]:
            raise RuntimeError("/status did not report real runnable local state")
        if status["data"]["operator"]["counts"]["users"] != 1:
            raise RuntimeError("/status did not include real operator-store counts")

        approval_list = payload(run_command(root, ["/approve", "list"], env))
        if approval_list["data"]["mode"] != "read_only" or approval_list["data"]["approvals"] != []:
            raise RuntimeError("/approve list did not expose bounded read-only approval state")

        model_readiness = payload(run_command(root, ["/model", "readiness", "--provider", "openai"], env))
        if model_readiness["command"] != "/model" or model_readiness["data"]["providers"][0]["provider"] != "openai":
            raise RuntimeError("/model readiness did not expose provider readiness")

        lane = payload(run_command(root, ["/lane"], env))
        if lane["data"]["status"] != "active" or not lane["data"]["lane_state"]:
            raise RuntimeError("/lane did not expose bounded lane state")

        reset = payload(run_command(root, ["/new"], env))
        if not reset["ok"] or reset["command"] != "/new":
            raise RuntimeError("/new did not delegate to bounded lane reset")

        unsupported = payload(run_command(root, ["/does-not-exist"], env, check=False))
        if unsupported["ok"] or unsupported["data"]["error"] != "unsupported_command":
            raise RuntimeError("unsupported command did not fail explicitly")

        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        bootstraps = store.list_records("onboarding_bootstraps", 1000)
        if len(bootstraps) != 1:
            raise RuntimeError("expected exactly one canonical onboarding bootstrap")

        secret_source.unlink()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "checks": {
                        "bounded_help_command_set": True,
                        "onboard_delegates_to_feature1": True,
                        "doctor_delegates_to_feature2": True,
                        "status_reflects_real_state": True,
                        "approve_list_is_bounded_read_only": True,
                        "model_readiness_is_bounded": True,
                        "lane_state_is_bounded": True,
                        "reset_delegates_to_feature4": True,
                        "unsupported_commands_fail_explicitly": True,
                        "plaintext_secret_not_printed": True,
                    },
                    "command_set": sorted(commands),
                    "latest_readiness": latest["readiness_json"],
                    "doctor_counts": doctor["data"]["counts"],
                    "status_counts": status["data"]["operator"]["counts"],
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

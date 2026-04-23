#!/usr/bin/env python3
"""Validate V1 Feature 2 doctor inspection and bounded repair."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import AgentFirstStore  # noqa: E402


TEST_SECRET = "feature2-validation-token-plaintext"


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


def bootstrap_ready(root: Path, env: dict[str, str]) -> dict:
    secret_source = root / "trusted-local-secret.txt"
    secret_source.write_text(TEST_SECRET, encoding="utf-8")
    result = run_cli(
        root,
        [
            "onboarding",
            "bootstrap",
            "--operator-display-name",
            "Feature 2 Primary",
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
    payload = json.loads(result.stdout)
    if not payload["readiness"]["runnable"]:
        raise RuntimeError("ready bootstrap did not become runnable")
    secret_source.unlink()
    return payload


def bootstrap_blocked(root: Path, env: dict[str, str]) -> dict:
    result = run_cli(
        root,
        [
            "onboarding",
            "bootstrap",
            "--operator-display-name",
            "Feature 2 Blocked",
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
    payload = json.loads(result.stdout)
    if payload["readiness"]["runnable"]:
        raise RuntimeError("blocked bootstrap unexpectedly became runnable")
    return payload


def latest_bootstrap_id(root: Path) -> str:
    with sqlite3.connect(root / "agentfirst.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT onboarding_bootstrap_id
            FROM onboarding_bootstraps
            ORDER BY created_at DESC, onboarding_bootstrap_id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("missing onboarding bootstrap row")
    return str(row[0])


def introduce_fixable_drift(root: Path) -> None:
    bootstrap_id = latest_bootstrap_id(root)
    with sqlite3.connect(root / "agentfirst.sqlite3") as conn:
        conn.execute(
            """
            UPDATE onboarding_bootstraps
            SET model_preference_id = NULL,
                readiness_json = ?,
                status = 'incomplete'
            WHERE onboarding_bootstrap_id = ?
            """,
            (json.dumps({"stale": True}, sort_keys=True), bootstrap_id),
        )
        conn.commit()
    shutil.rmtree(root / "artifacts")


def find_check(payload: dict, check: str) -> list[dict]:
    return [item for item in payload["findings"] if item["check"] == check]


def main() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "AGENTFIRST_SECRET_PASSPHRASE": "feature2-validation-passphrase",
    }

    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature2-healthy-") as tmp:
        root = Path(tmp)
        bootstrap_ready(root, env)
        healthy = json.loads(run_cli(root, ["doctor"], env).stdout)
        if not healthy["runnable"]:
            raise RuntimeError("doctor did not report healthy state as runnable")
        if healthy["counts"]["blocked"] != 0 or healthy["counts"]["fixable"] != 0:
            raise RuntimeError("healthy doctor reported blocked or fixable findings")

        introduce_fixable_drift(root)
        drifted = json.loads(run_cli(root, ["doctor"], env).stdout)
        if drifted["runnable"]:
            raise RuntimeError("doctor reported drifted state as runnable before --fix")
        if not find_check(drifted, "artifact_root") or not find_check(drifted, "model_provider_preference"):
            raise RuntimeError("doctor did not surface expected fixable drift")
        if drifted["counts"]["blocked"] != 0 or drifted["counts"]["fixable"] < 2:
            raise RuntimeError("doctor did not classify drift as fixable-only")

        fixed = json.loads(run_cli(root, ["doctor", "--fix"], env).stdout)
        if not fixed["runnable"]:
            raise RuntimeError("doctor --fix did not restore runnable state")
        if fixed["counts"]["blocked"] != 0 or fixed["counts"]["fixed"] < 2:
            raise RuntimeError("doctor --fix did not report applied fixes")

        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        audits = [
            row
            for row in store.list_records("audit_events", 1000)
            if row["event_type"] == "doctor_fix_applied"
        ]
        if not audits:
            raise RuntimeError("doctor --fix did not record a bounded repair audit event")

    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-feature2-blocked-") as tmp:
        root = Path(tmp)
        bootstrap_blocked(root, env)
        blocked = json.loads(run_cli(root, ["doctor"], env).stdout)
        if blocked["runnable"] or blocked["counts"]["blocked"] == 0:
            raise RuntimeError("doctor did not report missing secret as blocked")
        if "telegram_required_secret" not in {item["check"] for item in blocked["findings"]}:
            raise RuntimeError("doctor did not identify missing Telegram required secret")

        fixed_blocked = json.loads(run_cli(root, ["doctor", "--fix"], env).stdout)
        if fixed_blocked["runnable"] or fixed_blocked["counts"]["blocked"] == 0:
            raise RuntimeError("doctor --fix incorrectly repaired authority-sensitive secret absence")
        secret_records = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts").list_records("secret_records", 1000)
        if secret_records:
            raise RuntimeError("doctor --fix fabricated a secret record")

    print(
        json.dumps(
            {
                "status": "ok",
                "checks": {
                    "healthy_state_runnable": True,
                    "fixable_drift_classified": True,
                    "bounded_fix_applied": True,
                    "blocked_secret_not_fixed": True,
                    "doctor_fix_audited": True,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

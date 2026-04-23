#!/usr/bin/env python3
"""Validate the bounded V1 secret broker slice phase 1 implementation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentfirst_storage import (  # noqa: E402
    AgentFirstStore,
    LocalEncryptedSecretVault,
    MacOSKeychainRootKeyProvider,
    OperatorPassphraseRootKeyProvider,
    OperatorSurface,
    SecretBroker,
    TelegramBotApiTransport,
    TelegramChannelService,
)


TEST_TOKEN_V1 = "123456:PHASE1_TOKEN_ALPHA"
TEST_TOKEN_V2 = "123456:PHASE1_TOKEN_BRAVO"


def enroll_telegram(telegram: TelegramChannelService, user_id: str) -> dict[str, object]:
    enrollment = telegram.issue_enrollment_challenge(
        telegram_user_id="551122",
        display_name="Phase One",
        username="phase_one",
        requested_by_type="user",
        requested_by_ref=user_id,
    )
    verified = telegram.verify_enrollment_challenge(
        enrollment["enrollment_id"],
        challenge_secret=enrollment["challenge_material"]["challenge_secret"],
        challenge_nonce=enrollment["challenge_material"]["challenge_nonce"],
        actor_type="system",
        actor_ref="v1_secret_broker_validation",
    )
    OperatorSurface(telegram.store).resolve_approval(
        verified["metadata_json"]["approval_record_id"],
        actor_user_id=user_id,
        status="approved",
        confirmation="APPROVED",
    )
    return telegram.approve_enrollment(
        verified["enrollment_id"],
        user_id=user_id,
        approver_user_id=user_id,
    )


def run_cli(*, env: dict[str, str], root: Path, stdin_text: str | None, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "agentfirst_storage.cli", "--db", str(root / "agentfirst.sqlite3"), "--artifact-root", str(root / "artifacts"), "--secret-root", str(root / "secure-secrets"), *args]
    return subprocess.run(
        cmd,
        input=stdin_text,
        text=True,
        capture_output=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentfirst-v1-secret-broker-") as tmp:
        root = Path(tmp)
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "AGENTFIRST_SECRET_PASSPHRASE": "phase1-validation-passphrase"}

        store = AgentFirstStore(root / "agentfirst.sqlite3", root / "artifacts")
        store.initialize()
        admin = store.bootstrap_admin("Secret Broker Primary", "America/New_York")

        put_result = run_cli(
            env=env,
            root=root,
            stdin_text=TEST_TOKEN_V1,
            args=[
                "secret",
                "put",
                "--stdin",
                "--handle",
                "telegram.bot.primary",
                "--kind",
                "bot_token",
                "--integration",
                "telegram",
                "--owner-type",
                "system",
                "--owner-ref",
                "validation",
            ],
        )
        if TEST_TOKEN_V1 in put_result.stdout or TEST_TOKEN_V1 in put_result.stderr:
            raise RuntimeError("CLI secret put leaked plaintext token")
        secret_record = json.loads(put_result.stdout)

        list_result = run_cli(env=env, root=root, stdin_text=None, args=["secret", "list"])
        if TEST_TOKEN_V1 in list_result.stdout:
            raise RuntimeError("CLI secret list leaked plaintext token")

        broker = SecretBroker(
            store,
            LocalEncryptedSecretVault(root / "secure-secrets", OperatorPassphraseRootKeyProvider(passphrase="phase1-validation-passphrase")),
        )
        resolved_v1 = broker.resolve_secret_text(
            secret_record["secret_id"],
            actor_type="system",
            actor_ref="validation_direct",
            purpose="pre_rotation_check",
            integration_type="telegram",
        )
        if resolved_v1 != TEST_TOKEN_V1:
            raise RuntimeError("Resolved broker secret did not match stored value")

        rotate_result = run_cli(
            env=env,
            root=root,
            stdin_text=TEST_TOKEN_V2,
            args=["secret", "rotate", secret_record["secret_id"], "--stdin", "--reason", "validation_rotation"],
        )
        if TEST_TOKEN_V2 in rotate_result.stdout or TEST_TOKEN_V2 in rotate_result.stderr:
            raise RuntimeError("CLI secret rotate leaked plaintext token")
        rotated_record = json.loads(rotate_result.stdout)
        resolved_v2 = broker.resolve_secret_text(
            secret_record["secret_id"],
            actor_type="system",
            actor_ref="validation_direct",
            purpose="post_rotation_check",
            integration_type="telegram",
        )
        if resolved_v2 != TEST_TOKEN_V2:
            raise RuntimeError("Resolved broker secret did not use rotated version")

        transport = TelegramBotApiTransport(
            bot_token_secret_id=secret_record["secret_id"],
            secret_broker=broker,
            execute_live=True,
            api_base_url="http://127.0.0.1:9",
            secret_actor_ref="telegram_phase1_validation",
        )
        telegram = TelegramChannelService(store, bot_api_transport=transport)
        enroll_telegram(telegram, admin["user_id"])
        inbound = telegram.ingest_message(
            {
                "update_id": 91001,
                "bot_id": "phase1-bot",
                "bot_username": "agentfirst_phase1_bot",
                "message": {
                    "message_id": 701,
                    "date": 1776878400,
                    "chat": {"id": 42001, "type": "private"},
                    "from": {"id": 551122, "is_bot": False, "first_name": "Phase", "last_name": "One", "username": "phase_one"},
                    "text": "/commit Validate the brokered Telegram token path.",
                },
                "agentfirst": {"classification": "private"},
            }
        )
        store.insert(
            "destination_trust_tiers",
            {
                "destination_type": "channel",
                "destination_identity": "telegram:chat:42001",
                "trust_tier": 1,
                "policy_refs_json": [],
            },
            actor_type="system",
            actor_ref="v1_secret_broker_validation",
        )
        outbound = telegram.create_outbound_message(
            thread_id=inbound["thread"]["thread_id"],
            text="Brokered Telegram token retrieval was attempted without storing plaintext.",
            actor_type="agent",
            actor_ref=inbound["agent"]["agent_id"],
            sponsoring_user_id=admin["user_id"],
            classification="public",
            provenance={"source": "v1-secret-broker-phase1-validation"},
        )
        if outbound["transport"]["status"] != "send_failed":
            raise RuntimeError("Expected live transport to fail against loopback sink after brokered token resolution")

        access_events = broker.list_secrets()
        if len(access_events) != 1:
            raise RuntimeError("Expected one active secret record")

        with store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM secret_access_events WHERE secret_id = ? ORDER BY created_at, secret_access_event_id",
                (secret_record["secret_id"],),
            ).fetchall()
            secret_events = [store._decode_row(row) for row in rows]
        if len(secret_events) < 4:
            raise RuntimeError("Expected audited ingest, access, rotation, and telegram retrieval events")
        if not any(row["purpose"] == "telegram_send_message" and row["outcome"] == "resolved" for row in secret_events):
            raise RuntimeError("Telegram transport did not record brokered secret access")

        if broker.vault.contains_plaintext(TEST_TOKEN_V1) or broker.vault.contains_plaintext(TEST_TOKEN_V2):
            raise RuntimeError("Encrypted secret vault contains plaintext token bytes")
        for path in (root / "artifacts").rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                if TEST_TOKEN_V1.encode("utf-8") in data or TEST_TOKEN_V2.encode("utf-8") in data:
                    raise RuntimeError(f"Plaintext token leaked into ordinary artifact path: {path}")

        revoke_result = run_cli(
            env=env,
            root=root,
            stdin_text=None,
            args=["secret", "revoke", secret_record["secret_id"], "--reason", "validation_cleanup"],
        )
        revoked_record = json.loads(revoke_result.stdout)
        if revoked_record["status"] != "revoked":
            raise RuntimeError("Secret revoke command did not mark the secret revoked")
        denied_after_revoke = False
        try:
            broker.resolve_secret_text(
                secret_record["secret_id"],
                actor_type="system",
                actor_ref="validation_direct",
                purpose="post_revoke_check",
                integration_type="telegram",
            )
        except PermissionError:
            denied_after_revoke = True
        if not denied_after_revoke:
            raise RuntimeError("Revoked secret unexpectedly resolved")

        macos_keychain = {"status": "not_run", "reason": "non_darwin"}
        if sys.platform == "darwin":
            service_name = f"agentfirst.v1.secret-root.validation.{os.getpid()}"
            keychain_provider = MacOSKeychainRootKeyProvider(service_name=service_name)
            keychain_vault = LocalEncryptedSecretVault(root / "secure-secrets-keychain", keychain_provider)
            keychain_broker = SecretBroker(store, keychain_vault)
            keychain_record = keychain_broker.ingest_secret(
                plaintext="keychain-only-validation-token",
                handle_name="telegram.bot.keychain-validation",
                secret_kind="bot_token",
                integration_type="telegram",
                owner_type="system",
                owner_ref="validation",
                actor_type="system",
                actor_ref="keychain_validation",
            )
            roundtrip = keychain_broker.resolve_secret_text(
                keychain_record["secret_id"],
                actor_type="system",
                actor_ref="keychain_validation",
                purpose="keychain_roundtrip",
                integration_type="telegram",
            )
            if roundtrip != "keychain-only-validation-token":
                raise RuntimeError("macOS keychain root key provider roundtrip failed")
            keychain_provider.delete_if_present(account=f"vault:{(root / 'secure-secrets-keychain').name}")
            macos_keychain = {"status": "passed", "service_name": service_name}

        with store.connect() as conn:
            final_secret_event_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM secret_access_events WHERE secret_id = ?",
                    (secret_record["secret_id"],),
                ).fetchone()["n"]
            )

        result = {
            "status": "ok",
            "secret_record": {
                "secret_id": secret_record["secret_id"],
                "handle_uri": secret_record["handle_uri"],
                "current_version": rotated_record["current_version"],
                "status": revoked_record["status"],
            },
            "vault_root": str(root / "secure-secrets"),
            "artifact_root": str(root / "artifacts"),
            "secret_access_event_count": final_secret_event_count,
            "telegram_transport_status": outbound["transport"]["status"],
            "macos_keychain": macos_keychain,
            "checks": {
                "cli_ingest_masked": True,
                "vault_payload_encrypted": True,
                "telegram_brokered_retrieval_audited": True,
                "revoked_secret_denied": True,
            },
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

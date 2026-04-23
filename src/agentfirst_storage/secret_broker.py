"""Bounded local secret custody and broker services for AgentFirst V1."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import AgentFirstStore, new_id


def _now_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS now").fetchone()
    assert row is not None
    return str(row["now"])


class RootKeyProvider(ABC):
    """Resolve or create the vault root key without storing it in canonical state."""

    provider_name: str

    @abstractmethod
    def get_or_create_root_key(
        self,
        *,
        vault_id: str,
        provider_metadata: dict[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"provider_name": self.provider_name}


class MacOSKeychainRootKeyProvider(RootKeyProvider):
    """Store the shared vault root key in macOS Keychain."""

    provider_name = "macos_keychain"

    def __init__(self, *, service_name: str = "agentfirst.v1.secret-root"):
        self.service_name = service_name

    def get_or_create_root_key(
        self,
        *,
        vault_id: str,
        provider_metadata: dict[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        account = str(provider_metadata.get("account") or f"vault:{vault_id}")
        existing = self._read_password(account)
        if existing is None:
            raw = os.urandom(32)
            encoded = base64.urlsafe_b64encode(raw).decode("ascii")
            self._write_password(account, encoded)
            existing = encoded
        root_key = base64.urlsafe_b64decode(existing.encode("ascii"))
        if len(root_key) != 32:
            raise ValueError("macOS keychain root key must decode to 32 bytes")
        return root_key, {"account": account, "service_name": self.service_name}

    def describe(self) -> dict[str, Any]:
        return {"provider_name": self.provider_name, "service_name": self.service_name}

    def delete_if_present(self, *, account: str) -> None:
        subprocess.run(
            ["security", "delete-generic-password", "-s", self.service_name, "-a", account],
            check=False,
            capture_output=True,
            text=True,
        )

    def _read_password(self, account: str) -> str | None:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", self.service_name, "-a", account, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def _write_password(self, account: str, encoded_value: str) -> None:
        proc = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service_name,
                "-a",
                account,
                "-w",
                encoded_value,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to write root key to macOS Keychain: {proc.stderr.strip() or proc.stdout.strip()}")


class OperatorPassphraseRootKeyProvider(RootKeyProvider):
    """Derive the shared vault root key from an operator-supplied passphrase."""

    provider_name = "operator_passphrase"

    def __init__(
        self,
        *,
        passphrase: str | None = None,
        passphrase_env: str = "AGENTFIRST_SECRET_PASSPHRASE",
        prompt: str = "AgentFirst secret vault passphrase: ",
        iterations: int = 600_000,
    ):
        self.passphrase = passphrase
        self.passphrase_env = passphrase_env
        self.prompt = prompt
        self.iterations = iterations

    def get_or_create_root_key(
        self,
        *,
        vault_id: str,
        provider_metadata: dict[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        del vault_id
        salt_b64 = provider_metadata.get("salt_b64")
        salt = base64.b64decode(salt_b64) if salt_b64 else os.urandom(16)
        passphrase = self._resolve_passphrase()
        root_key = hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt,
            int(provider_metadata.get("iterations") or self.iterations),
            dklen=32,
        )
        updated = {
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "iterations": int(provider_metadata.get("iterations") or self.iterations),
            "passphrase_env": self.passphrase_env,
        }
        return root_key, updated

    def describe(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "passphrase_env": self.passphrase_env,
            "iterations": self.iterations,
        }

    def _resolve_passphrase(self) -> str:
        if self.passphrase is not None:
            return self.passphrase
        env_value = os.environ.get(self.passphrase_env)
        if env_value:
            return env_value
        prompted = getpass.getpass(self.prompt)
        if not prompted:
            raise ValueError("Operator passphrase must not be empty")
        return prompted


class LocalEncryptedSecretVault:
    """Shared encrypted local vault stored outside ordinary artifacts."""

    def __init__(self, root: str | Path, root_key_provider: RootKeyProvider):
        self.root = Path(root)
        self.root_key_provider = root_key_provider
        self.metadata_path = self.root / "vault.json"
        self.records_root = self.root / "records"
        self._cached_root_key: bytes | None = None

    def initialize(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_root.mkdir(parents=True, exist_ok=True)
        metadata = self._load_metadata()
        if metadata is None:
            metadata = {
                "vault_id": self.root.name,
                "format_version": 1,
                "provider_name": self.root_key_provider.provider_name,
                "provider_metadata": {},
            }
        if metadata.get("provider_name") != self.root_key_provider.provider_name:
            raise ValueError(
                "Vault provider mismatch: existing vault uses "
                f"{metadata.get('provider_name')} but requested {self.root_key_provider.provider_name}"
            )
        root_key, provider_metadata = self.root_key_provider.get_or_create_root_key(
            vault_id=str(metadata["vault_id"]),
            provider_metadata=dict(metadata.get("provider_metadata") or {}),
        )
        metadata["provider_metadata"] = provider_metadata
        self._write_metadata(metadata)
        self._cached_root_key = root_key
        return metadata

    def put_secret(self, *, secret_id: str, version: int, plaintext: str) -> str:
        self.initialize()
        package = self._encrypt(plaintext.encode("utf-8"))
        target = self._record_path(secret_id, version)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
        return f"vault://{secret_id}/v{version}"

    def get_secret(self, *, secret_id: str, version: int) -> str:
        self.initialize()
        package = json.loads(self._record_path(secret_id, version).read_text(encoding="utf-8"))
        plaintext = self._decrypt(package)
        return plaintext.decode("utf-8")

    def contains_plaintext(self, needle: str) -> bool:
        encoded = needle.encode("utf-8")
        for path in self.root.rglob("*"):
            if path.is_file():
                try:
                    if encoded in path.read_bytes():
                        return True
                except OSError:
                    continue
        return False

    def _record_path(self, secret_id: str, version: int) -> Path:
        return self.records_root / secret_id / f"v{version}.json"

    def _encrypt(self, plaintext: bytes) -> dict[str, Any]:
        salt = os.urandom(16)
        iv = os.urandom(16)
        enc_key, mac_key = self._derive_subkeys(salt)
        proc = subprocess.run(
            [
                "openssl",
                "enc",
                "-aes-256-cbc",
                "-e",
                "-nosalt",
                "-K",
                enc_key.hex(),
                "-iv",
                iv.hex(),
            ],
            input=plaintext,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace") or "openssl encryption failed")
        ciphertext = proc.stdout
        mac = self._mac(mac_key, salt=salt, iv=iv, ciphertext=ciphertext)
        return {
            "format_version": 1,
            "algorithm": "aes-256-cbc+hmac-sha256",
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "iv_b64": base64.b64encode(iv).decode("ascii"),
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            "mac_hex": mac,
        }

    def _decrypt(self, package: dict[str, Any]) -> bytes:
        salt = base64.b64decode(package["salt_b64"])
        iv = base64.b64decode(package["iv_b64"])
        ciphertext = base64.b64decode(package["ciphertext_b64"])
        enc_key, mac_key = self._derive_subkeys(salt)
        expected_mac = self._mac(mac_key, salt=salt, iv=iv, ciphertext=ciphertext)
        if not hmac.compare_digest(expected_mac, str(package["mac_hex"])):
            raise PermissionError("Secret vault MAC verification failed")
        proc = subprocess.run(
            [
                "openssl",
                "enc",
                "-aes-256-cbc",
                "-d",
                "-nosalt",
                "-K",
                enc_key.hex(),
                "-iv",
                iv.hex(),
            ],
            input=ciphertext,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace") or "openssl decryption failed")
        return proc.stdout

    def _derive_subkeys(self, salt: bytes) -> tuple[bytes, bytes]:
        if self._cached_root_key is None:
            self.initialize()
        root_key = self._cached_root_key
        assert isinstance(root_key, bytes)
        material = hashlib.pbkdf2_hmac("sha256", root_key, salt, 200_000, dklen=64)
        return material[:32], material[32:]

    def _mac(self, mac_key: bytes, *, salt: bytes, iv: bytes, ciphertext: bytes) -> str:
        payload = b"|".join([b"agentfirst-v1-secret-vault", salt, iv, ciphertext])
        return hmac.new(mac_key, payload, hashlib.sha256).hexdigest()

    def _load_metadata(self) -> dict[str, Any] | None:
        if not self.metadata_path.exists():
            return None
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True)
class SecretReference:
    secret_id: str
    handle_uri: str
    version: int


class SecretBroker:
    """Minimal secret metadata, vault custody, and audited retrieval broker."""

    def __init__(self, store: AgentFirstStore, vault: LocalEncryptedSecretVault):
        self.store = store
        self.vault = vault

    def ingest_secret(
        self,
        *,
        plaintext: str,
        handle_name: str,
        secret_kind: str,
        integration_type: str,
        owner_type: str,
        owner_ref: str,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        display_hint: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_ref: str = "secret_broker",
    ) -> dict[str, Any]:
        self.store.initialize()
        self.vault.initialize()
        secret_id = new_id("sec")
        handle_uri = self._handle_uri(handle_name)
        version = 1
        with self.store.connect() as conn:
            existing = conn.execute("SELECT secret_id FROM secret_records WHERE handle_uri = ?", (handle_uri,)).fetchone()
            if existing is not None:
                raise ValueError(f"Secret handle already exists: {handle_uri}")
            record = self.store.insert(
                "secret_records",
                {
                    "secret_id": secret_id,
                    "handle_uri": handle_uri,
                    "owner_type": owner_type,
                    "owner_ref": owner_ref,
                    "scope_type": scope_type,
                    "scope_ref": scope_ref,
                    "integration_type": integration_type,
                    "secret_kind": secret_kind,
                    "status": "active",
                    "current_version": version,
                    "fingerprint": self._fingerprint(plaintext),
                    "display_hint": display_hint or self._display_hint(plaintext),
                    "vault_backend": "local_encrypted_v1",
                    "root_key_provider": self.vault.root_key_provider.provider_name,
                    "metadata_json": metadata or {},
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            vault_ref = self.vault.put_secret(secret_id=secret_id, version=version, plaintext=plaintext)
            record = self.store.update(
                "secret_records",
                secret_id,
                {"vault_ref": vault_ref},
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self._record_secret_event(
                conn,
                secret_id=secret_id,
                handle_uri=handle_uri,
                version=version,
                actor_type=actor_type,
                actor_ref=actor_ref,
                operation="ingest",
                purpose="secret_ingest",
                integration_type=integration_type,
                outcome="stored",
                metadata={"secret_kind": secret_kind},
            )
            conn.commit()
            return record

    def rotate_secret(
        self,
        secret_ref: str,
        *,
        plaintext: str,
        actor_type: str = "system",
        actor_ref: str = "secret_broker",
        reason: str = "rotation",
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            record = self._require_secret(conn, secret_ref)
            if record["status"] != "active":
                raise PermissionError("Only active secrets can be rotated")
            next_version = int(record["current_version"] or 0) + 1
            self.vault.put_secret(secret_id=record["secret_id"], version=next_version, plaintext=plaintext)
            updated = self.store.update(
                "secret_records",
                record["secret_id"],
                {
                    "current_version": next_version,
                    "fingerprint": self._fingerprint(plaintext),
                    "display_hint": self._display_hint(plaintext),
                    "rotated_at": _now_sql(conn),
                    "metadata_json": {
                        **record.get("metadata_json", {}),
                        "last_rotation_reason": reason,
                    },
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self._record_secret_event(
                conn,
                secret_id=record["secret_id"],
                handle_uri=record["handle_uri"],
                version=next_version,
                actor_type=actor_type,
                actor_ref=actor_ref,
                operation="rotate",
                purpose=reason,
                integration_type=record["integration_type"],
                outcome="rotated",
                metadata={},
            )
            conn.commit()
            return updated

    def revoke_secret(
        self,
        secret_ref: str,
        *,
        actor_type: str = "system",
        actor_ref: str = "secret_broker",
        reason: str = "revoked",
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            record = self._require_secret(conn, secret_ref)
            updated = self.store.update(
                "secret_records",
                record["secret_id"],
                {
                    "status": "revoked",
                    "revoked_at": _now_sql(conn),
                    "metadata_json": {
                        **record.get("metadata_json", {}),
                        "revocation_reason": reason,
                    },
                },
                conn=conn,
                emit_event=False,
                actor_type=actor_type,
                actor_ref=actor_ref,
            )
            self._record_secret_event(
                conn,
                secret_id=record["secret_id"],
                handle_uri=record["handle_uri"],
                version=int(record["current_version"]),
                actor_type=actor_type,
                actor_ref=actor_ref,
                operation="revoke",
                purpose=reason,
                integration_type=record["integration_type"],
                outcome="revoked",
                metadata={},
            )
            conn.commit()
            return updated

    def resolve_secret_text(
        self,
        secret_ref: str,
        *,
        actor_type: str,
        actor_ref: str,
        purpose: str,
        integration_type: str | None = None,
    ) -> str:
        with self.store.connect() as conn:
            record = self._require_secret(conn, secret_ref)
            version = int(record["current_version"])
            if record["status"] != "active":
                self._record_secret_event(
                    conn,
                    secret_id=record["secret_id"],
                    handle_uri=record["handle_uri"],
                    version=version,
                    actor_type=actor_type,
                    actor_ref=actor_ref,
                    operation="access",
                    purpose=purpose,
                    integration_type=integration_type or record["integration_type"],
                    outcome="denied_inactive_secret",
                    metadata={},
                )
                conn.commit()
                raise PermissionError("Secret is not active")
            plaintext = self.vault.get_secret(secret_id=record["secret_id"], version=version)
            self._record_secret_event(
                conn,
                secret_id=record["secret_id"],
                handle_uri=record["handle_uri"],
                version=version,
                actor_type=actor_type,
                actor_ref=actor_ref,
                operation="access",
                purpose=purpose,
                integration_type=integration_type or record["integration_type"],
                outcome="resolved",
                metadata={},
            )
            conn.commit()
            return plaintext

    def get_secret_record(self, secret_ref: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            return self._require_secret(conn, secret_ref)

    def list_secrets(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        self.store.initialize()
        with self.store.connect() as conn:
            sql = "SELECT * FROM secret_records"
            params: tuple[Any, ...] = ()
            if not include_inactive:
                sql += " WHERE status = 'active'"
            sql += " ORDER BY integration_type, handle_uri"
            rows = conn.execute(sql, params).fetchall()
            return [self.store._decode_row(row) for row in rows]

    def _record_secret_event(
        self,
        conn: sqlite3.Connection,
        *,
        secret_id: str,
        handle_uri: str,
        version: int,
        actor_type: str,
        actor_ref: str,
        operation: str,
        purpose: str,
        integration_type: str,
        outcome: str,
        metadata: dict[str, Any],
    ) -> None:
        event = self.store.insert(
            "secret_access_events",
            {
                "secret_access_event_id": new_id("sae"),
                "secret_id": secret_id,
                "handle_uri": handle_uri,
                "secret_version": version,
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "operation": operation,
                "purpose": purpose,
                "integration_type": integration_type,
                "outcome": outcome,
                "metadata_json": metadata,
            },
            conn=conn,
            emit_event=False,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        audit = self.store.insert(
            "audit_events",
            {
                "audit_event_id": new_id("aud"),
                "event_type": f"secret_{operation}",
                "actor_type": actor_type,
                "actor_ref": actor_ref,
                "object_type": "secret_record",
                "object_ref": secret_id,
                "action_summary": f"Secret {operation} on {handle_uri}",
                "outcome": outcome,
                "metadata_json": {
                    "handle_uri": handle_uri,
                    "secret_version": version,
                    "integration_type": integration_type,
                    "secret_access_event_id": event["secret_access_event_id"],
                },
            },
            conn=conn,
            emit_event=False,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
        self.store.append_event(
            f"secret_{operation}",
            "secret_record",
            secret_id,
            actor_type,
            actor_ref,
            {"handle_uri": handle_uri, "secret_version": version, "outcome": outcome},
            audit_event_id=audit["audit_event_id"],
            conn=conn,
        )

    def _require_secret(self, conn: sqlite3.Connection, secret_ref: str) -> dict[str, Any]:
        if secret_ref.startswith("secret://"):
            row = conn.execute("SELECT * FROM secret_records WHERE handle_uri = ?", (secret_ref,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM secret_records WHERE secret_id = ?", (secret_ref,)).fetchone()
        if row is None:
            raise ValueError(f"Secret not found: {secret_ref}")
        return self.store._decode_row(row)

    def _handle_uri(self, handle_name: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", ".", "_"} else "-" for ch in handle_name.strip())
        cleaned = cleaned.strip("-._")
        if not cleaned:
            raise ValueError("Secret handle name must not be empty")
        return f"secret://{cleaned}"

    def _fingerprint(self, plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]

    def _display_hint(self, plaintext: str) -> str:
        trimmed = plaintext.strip()
        suffix = trimmed[-4:] if len(trimmed) >= 4 else trimmed
        return f"***{suffix}" if suffix else "***"


SecretService = SecretBroker

"""Bounded local onboarding/bootstrap flow for AgentFirst V1 Feature 1."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model_routing import ModelPreferenceRequest, ModelRoutingService
from .provider_catalog import find_model, inspect_provider_readiness
from .secret_broker import SecretBroker
from .store import AgentFirstStore, new_id


CHANNEL_STATES = {"enabled", "disabled", "deferred"}
KNOWN_CHANNELS = {"local", "telegram", "bluebubbles", "google_workspace"}
SECRET_REQUIREMENTS = {
    "telegram": [{"integration": "telegram", "kind": "bot_token"}],
}


@dataclass(frozen=True)
class OnboardingSecretFile:
    """Trusted local secret file to ingest during onboarding."""

    handle: str
    kind: str
    integration: str
    path: Path
    owner_type: str = "system"
    owner_ref: str = "onboarding"


@dataclass(frozen=True)
class OnboardingRequest:
    """Inputs for the bounded local onboarding/bootstrap flow."""

    operator_display_name: str
    timezone: str
    custody_mode: str
    provider: str
    model: str
    channels: dict[str, str] = field(default_factory=dict)
    secret_files: list[OnboardingSecretFile] = field(default_factory=list)
    actor_type: str = "system"
    actor_ref: str = "onboarding"


class OnboardingService:
    """Create first-run canonical state without accepting secrets from chat."""

    def __init__(
        self,
        store: AgentFirstStore,
        *,
        secret_broker: SecretBroker,
        model_routing: ModelRoutingService | None = None,
    ):
        self.store = store
        self.secret_broker = secret_broker
        self.model_routing = model_routing or ModelRoutingService(store)

    def bootstrap(self, request: OnboardingRequest) -> dict[str, Any]:
        self._validate_request(request)
        self.store.initialize()
        operator = self.store.bootstrap_admin(request.operator_display_name, request.timezone)
        vault_metadata = self.secret_broker.vault.initialize()
        secret_results = self._ingest_secret_files(request, operator["user_id"])
        model_preference = self._ensure_model_preference(request, operator["user_id"])
        channels = self._normalize_channels(request.channels)
        readiness = self.evaluate_readiness(
            operator_user_id=operator["user_id"],
            custody_mode=request.custody_mode,
            provider=request.provider,
            model=request.model,
            channels=channels,
        )
        status = "ready" if readiness["runnable"] else "incomplete"
        record = self._record_bootstrap(
            request,
            operator["user_id"],
            vault_metadata,
            model_preference,
            channels,
            secret_results,
            readiness,
            status,
        )
        return {
            "ok": True,
            "status": status,
            "primary_operator": self._operator_summary(operator),
            "custody": {
                "mode": request.custody_mode,
                "provider_name": vault_metadata.get("provider_name"),
                "vault_id": vault_metadata.get("vault_id"),
            },
            "model_preference": {
                "model_preference_id": model_preference["model_preference_id"],
                "provider": model_preference["provider"],
                "model": model_preference["model"],
                "purpose": model_preference["purpose"],
            },
            "channels": channels,
            "secrets": secret_results,
            "readiness": readiness,
            "onboarding_bootstrap_id": record["onboarding_bootstrap_id"],
        }

    def status(self) -> dict[str, Any]:
        self.store.initialize()
        latest = self.latest_bootstrap()
        primary = self._primary_operator()
        if latest is not None:
            return {"bootstrapped": True, "latest_bootstrap": latest, "readiness": latest["readiness_json"]}
        if primary is None:
            return {
                "bootstrapped": False,
                "readiness": {
                    "runnable": False,
                    "passed": [],
                    "missing": ["primary_operator", "onboarding_bootstrap_record"],
                    "deferred": [],
                },
            }
        readiness = self.evaluate_readiness(
            operator_user_id=primary["user_id"],
            custody_mode=None,
            provider=None,
            model=None,
            channels=[],
        )
        return {"bootstrapped": False, "primary_operator": self._operator_summary(primary), "readiness": readiness}

    def latest_bootstrap(self) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM onboarding_bootstraps
                ORDER BY created_at DESC, onboarding_bootstrap_id DESC
                LIMIT 1
                """
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def evaluate_readiness(
        self,
        *,
        operator_user_id: str | None,
        custody_mode: str | None,
        provider: str | None,
        model: str | None,
        channels: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed: list[str] = []
        missing: list[str] = []
        deferred: list[str] = []

        with self.store.connect() as conn:
            if operator_user_id and self._user_exists(conn, operator_user_id):
                passed.append("primary_operator")
            else:
                missing.append("primary_operator")

            if custody_mode:
                passed.append("root_key_custody_selected")
            else:
                missing.append("root_key_custody_selected")

            if provider and model and self._has_model_preference(conn, operator_user_id, provider, model):
                passed.append("model_provider_preference")
            else:
                missing.append("model_provider_preference")

            enabled_channels = [item for item in channels if item["state"] == "enabled"]
            if enabled_channels:
                passed.append("channel_enablement_recorded")
            else:
                deferred.append("no_initial_channels_enabled")
            for channel in enabled_channels:
                channel_name = channel["channel"]
                requirements = SECRET_REQUIREMENTS.get(channel_name, [])
                unmet = [
                    f"{req['integration']}:{req['kind']}"
                    for req in requirements
                    if not self._has_active_secret(conn, req["integration"], req["kind"])
                ]
                if unmet:
                    missing.append(f"{channel_name}_required_secret")
                    channel["readiness"] = "missing_required_secret"
                    channel["missing_secret_requirements"] = unmet
                else:
                    channel["readiness"] = "ready_for_channel_enrollment" if channel_name != "local" else "ready"
                if channel_name != "local":
                    channel["note"] = "Channel enablement does not bypass enrollment or trust checks."

            for channel in channels:
                if channel["state"] == "deferred":
                    deferred.append(f"{channel['channel']}_channel")

        runnable = not missing
        return {
            "runnable": runnable,
            "runnable_scope": "bounded_local" if runnable else "not_runnable",
            "passed": passed,
            "missing": sorted(set(missing)),
            "deferred": sorted(set(deferred)),
            "model_execution": self._model_execution_readiness(provider),
            "summary": "Ready for bounded local operation." if runnable else "Onboarding state is incomplete.",
        }

    def _ingest_secret_files(self, request: OnboardingRequest, operator_user_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for secret_file in request.secret_files:
            plaintext = secret_file.path.read_text(encoding="utf-8").rstrip("\n")
            if not plaintext:
                raise ValueError(f"Secret file is empty: {secret_file.path}")
            existing = self._secret_by_handle(secret_file.handle)
            if existing is None:
                record = self.secret_broker.ingest_secret(
                    plaintext=plaintext,
                    handle_name=secret_file.handle,
                    secret_kind=secret_file.kind,
                    integration_type=secret_file.integration,
                    owner_type=secret_file.owner_type,
                    owner_ref=secret_file.owner_ref,
                    scope_type="user",
                    scope_ref=operator_user_id,
                    metadata={"ingested_by": "onboarding", "source": "trusted_local_file"},
                    actor_type=request.actor_type,
                    actor_ref=request.actor_ref,
                )
                action = "ingested"
            else:
                record = existing
                action = "already_present"
            results.append(
                {
                    "action": action,
                    "secret_id": record["secret_id"],
                    "handle_uri": record["handle_uri"],
                    "integration_type": record["integration_type"],
                    "secret_kind": record["secret_kind"],
                    "status": record["status"],
                    "display_hint": record.get("display_hint"),
                }
            )
        return results

    def _ensure_model_preference(self, request: OnboardingRequest, operator_user_id: str) -> dict[str, Any]:
        with self.store.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM model_provider_preferences
                WHERE scope_type = 'user'
                  AND scope_ref = ?
                  AND purpose = 'general'
                  AND provider = ?
                  AND model = ?
                  AND status = 'active'
                ORDER BY created_at DESC, model_preference_id DESC
                LIMIT 1
                """,
                (operator_user_id, request.provider, request.model),
            ).fetchone()
            if existing is not None:
                return self.store._decode_row(existing)
        return self.model_routing.create_preference(
            ModelPreferenceRequest(
                scope_type="user",
                scope_ref=operator_user_id,
                provider=request.provider,
                model=request.model,
                rationale_summary="Initial provider/model selected during V1 onboarding.",
                purpose="general",
                created_by_type=request.actor_type,
                created_by_ref=request.actor_ref,
            )
        )

    def _record_bootstrap(
        self,
        request: OnboardingRequest,
        operator_user_id: str,
        vault_metadata: dict[str, Any],
        model_preference: dict[str, Any],
        channels: list[dict[str, Any]],
        secrets: list[dict[str, Any]],
        readiness: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        with self.store.connect() as conn:
            record = self.store.insert(
                "onboarding_bootstraps",
                {
                    "onboarding_bootstrap_id": new_id("onb"),
                    "primary_operator_user_id": operator_user_id,
                    "custody_mode": request.custody_mode,
                    "custody_json": {
                        "provider_name": vault_metadata.get("provider_name"),
                        "vault_id": vault_metadata.get("vault_id"),
                    },
                    "model_preference_id": model_preference["model_preference_id"],
                    "provider": request.provider,
                    "model": request.model,
                    "channels_json": channels,
                    "secrets_json": secrets,
                    "readiness_json": readiness,
                    "status": status,
                    "created_by_type": request.actor_type,
                    "created_by_ref": request.actor_ref,
                },
                conn=conn,
                emit_event=False,
                actor_type=request.actor_type,
                actor_ref=request.actor_ref,
            )
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "onboarding_bootstrap_completed",
                    "actor_type": request.actor_type,
                    "actor_ref": request.actor_ref,
                    "object_type": "onboarding_bootstrap",
                    "object_ref": record["onboarding_bootstrap_id"],
                    "action_summary": "V1 onboarding bootstrap completed",
                    "outcome": status,
                    "metadata_json": {
                        "primary_operator_user_id": operator_user_id,
                        "custody_mode": request.custody_mode,
                        "provider": request.provider,
                        "model": request.model,
                        "runnable": readiness["runnable"],
                    },
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "onboarding_bootstrap_completed",
                "onboarding_bootstrap",
                record["onboarding_bootstrap_id"],
                request.actor_type,
                request.actor_ref,
                {"audit_event_id": audit["audit_event_id"], "status": status, "runnable": readiness["runnable"]},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            conn.commit()
            return record

    def _normalize_channels(self, channels: dict[str, str]) -> list[dict[str, Any]]:
        normalized = []
        requested = channels or {"local": "enabled"}
        for channel, state in sorted(requested.items()):
            normalized.append({"channel": channel, "state": state})
        return normalized

    def _validate_request(self, request: OnboardingRequest) -> None:
        if not request.operator_display_name.strip():
            raise ValueError("operator display name is required")
        if request.custody_mode not in {"operator_passphrase", "macos_keychain"}:
            raise ValueError("custody_mode must be operator_passphrase or macos_keychain")
        if find_model(request.provider, request.model) is None:
            raise ValueError(f"provider/model is outside the bounded V1 set: {request.provider}:{request.model}")
        for channel, state in request.channels.items():
            if channel not in KNOWN_CHANNELS:
                raise ValueError(f"unsupported onboarding channel: {channel}")
            if state not in CHANNEL_STATES:
                raise ValueError(f"channel state must be enabled, disabled, or deferred: {channel}")
        for secret_file in request.secret_files:
            if not secret_file.path.exists() or not secret_file.path.is_file():
                raise ValueError(f"secret file not found: {secret_file.path}")

    def _secret_by_handle(self, handle_name: str) -> dict[str, Any] | None:
        handle_uri = handle_name if handle_name.startswith("secret://") else f"secret://{handle_name}"
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM secret_records WHERE handle_uri = ?", (handle_uri,)).fetchone()
            return self.store._decode_row(row) if row else None

    def _primary_operator(self) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE primary_user_flag = 1").fetchone()
            return self.store._decode_row(row) if row else None

    def _operator_summary(self, operator: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": operator["user_id"],
            "display_name": operator["display_name"],
            "authority_tier": operator["authority_tier"],
            "primary_user_flag": operator["primary_user_flag"],
            "default_timezone": operator["default_timezone"],
        }

    def _user_exists(self, conn: sqlite3.Connection, user_id: str | None) -> bool:
        if not user_id:
            return False
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ? AND status = 'active'", (user_id,)).fetchone()
        return row is not None

    def _has_model_preference(
        self,
        conn: sqlite3.Connection,
        user_id: str | None,
        provider: str | None,
        model: str | None,
    ) -> bool:
        if not user_id or not provider or not model:
            return False
        row = conn.execute(
            """
            SELECT model_preference_id FROM model_provider_preferences
            WHERE scope_type = 'user'
              AND scope_ref = ?
              AND purpose = 'general'
              AND provider = ?
              AND model = ?
              AND status = 'active'
            LIMIT 1
            """,
            (user_id, provider, model),
        ).fetchone()
        return row is not None

    def _has_active_secret(self, conn: sqlite3.Connection, integration: str, kind: str) -> bool:
        row = conn.execute(
            """
            SELECT secret_id FROM secret_records
            WHERE integration_type = ?
              AND secret_kind = ?
              AND status = 'active'
            LIMIT 1
            """,
            (integration, kind),
        ).fetchone()
        return row is not None

    def _model_execution_readiness(self, provider: str | None) -> dict[str, Any] | None:
        if not provider:
            return None
        readiness = inspect_provider_readiness(self.store, provider=provider)
        return readiness["providers"][0] if readiness["providers"] else None

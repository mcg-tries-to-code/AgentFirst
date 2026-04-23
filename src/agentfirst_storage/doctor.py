"""Bounded local doctor and narrow repair flow for AgentFirst V1 Feature 2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .onboarding import SECRET_REQUIREMENTS
from .provider_catalog import inspect_provider_readiness
from .store import AgentFirstStore, new_id


@dataclass(frozen=True)
class DoctorFinding:
    check: str
    classification: str
    status: str
    summary: str
    detail: str | None = None
    fixable: bool = False
    fixed: bool = False
    action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "check": self.check,
            "classification": self.classification,
            "status": self.status,
            "summary": self.summary,
            "fixable": self.fixable,
            "fixed": self.fixed,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.action:
            payload["action"] = self.action
        return payload


class DoctorService:
    """Inspect local bootstrap health and repair only mechanical local drift."""

    def __init__(self, store: AgentFirstStore, *, secret_root: str | Path):
        self.store = store
        self.secret_root = Path(secret_root)

    def run(self, *, fix: bool = False) -> dict[str, Any]:
        findings: list[DoctorFinding] = []
        actions: list[dict[str, Any]] = []

        initialized = self.store.db_path.exists()
        if not initialized:
            findings.append(
                self._maybe_fix_directory(
                    check="database",
                    path=self.store.db_path.parent,
                    fix=fix,
                    summary="SQLite database is not initialized.",
                    action_label="created database parent directory",
                    detail="Run onboarding bootstrap to create canonical first-run state.",
                )
            )
            if fix:
                self.store.initialize()
                actions.append({"action": "initialized_schema", "target": str(self.store.db_path)})
                findings.append(
                    DoctorFinding(
                        check="database_schema",
                        classification="fixable",
                        status="fixed",
                        summary="Initialized local schema.",
                        fixable=True,
                        fixed=True,
                        action="store.initialize",
                    )
                )
                initialized = True
            else:
                findings.append(
                    DoctorFinding(
                        check="database_schema",
                        classification="fixable",
                        status="fixable",
                        summary="Schema can be initialized locally with --fix.",
                        fixable=True,
                    )
                )

        findings.append(
            self._maybe_fix_directory(
                check="artifact_root",
                path=self.store.artifact_root,
                fix=fix,
                summary="Artifact root is missing.",
                action_label="created artifact root",
            )
        )
        findings.append(
            self._maybe_fix_directory(
                check="secret_root",
                path=self.secret_root,
                fix=fix,
                summary="Secret vault root is missing.",
                action_label="created secret vault root",
                detail="Directory creation does not create or reveal secret material.",
            )
        )
        findings.append(
            self._maybe_fix_directory(
                check="secret_records_root",
                path=self.secret_root / "records",
                fix=fix,
                summary="Secret vault records directory is missing.",
                action_label="created secret vault records directory",
                detail="Directory creation does not create or reveal secret payload files.",
            )
        )

        if initialized:
            self.store.initialize()
            state_findings, state_actions = self._inspect_canonical_state(fix=fix)
            findings.extend(state_findings)
            actions.extend(state_actions)

        if fix and actions:
            self._record_doctor_audit(actions)

        counts = {
            "informational": sum(1 for item in findings if item.classification == "informational"),
            "fixable": sum(1 for item in findings if item.classification == "fixable" and not item.fixed),
            "fixed": sum(1 for item in findings if item.fixed),
            "blocked": sum(1 for item in findings if item.classification == "blocked"),
        }
        runnable = counts["blocked"] == 0 and counts["fixable"] == 0
        return {
            "ok": True,
            "mode": "fix" if fix else "inspect",
            "runnable": runnable,
            "summary": "Doctor found no blocking local issues." if runnable else "Doctor found local issues requiring attention.",
            "counts": counts,
            "actions": actions,
            "findings": [item.as_dict() for item in findings],
        }

    def _inspect_canonical_state(self, *, fix: bool) -> tuple[list[DoctorFinding], list[dict[str, Any]]]:
        findings: list[DoctorFinding] = []
        actions: list[dict[str, Any]] = []
        latest = self._latest_bootstrap()
        primary = self._primary_operator()
        active_secrets = self._active_secrets()

        if primary is None:
            findings.append(
                DoctorFinding(
                    check="primary_operator",
                    classification="blocked",
                    status="blocked",
                    summary="No primary operator exists.",
                    detail="Doctor cannot choose or create operator identity; run onboarding bootstrap.",
                )
            )
        else:
            findings.append(
                DoctorFinding(
                    check="primary_operator",
                    classification="informational",
                    status="pass",
                    summary="Primary operator exists.",
                    detail=f"user_id={primary['user_id']}",
                )
            )

        if latest is None:
            findings.append(
                DoctorFinding(
                    check="onboarding_bootstrap",
                    classification="blocked",
                    status="blocked",
                    summary="No onboarding bootstrap record exists.",
                    detail="Doctor will not invent custody, provider, or channel choices; run onboarding bootstrap.",
                )
            )
            return findings + self._inspect_vault(active_secrets, latest), actions

        findings.append(
            DoctorFinding(
                check="onboarding_bootstrap",
                classification="informational",
                status="pass",
                summary="Latest onboarding bootstrap record exists.",
                detail=f"onboarding_bootstrap_id={latest['onboarding_bootstrap_id']}",
            )
        )
        findings.extend(self._inspect_model_preference(latest, fix=fix, actions=actions))
        findings.extend(self._inspect_model_execution_readiness(latest))
        findings.extend(self._inspect_channels(latest))
        findings.extend(self._inspect_vault(active_secrets, latest))
        findings.extend(self._inspect_onboarding_readiness(latest, fix=fix, actions=actions))
        return findings, actions

    def _inspect_model_preference(
        self,
        latest: dict[str, Any],
        *,
        fix: bool,
        actions: list[dict[str, Any]],
    ) -> list[DoctorFinding]:
        model_preference_id = latest.get("model_preference_id")
        if model_preference_id and self._active_model_preference_by_id(model_preference_id):
            return [
                DoctorFinding(
                    check="model_provider_preference",
                    classification="informational",
                    status="pass",
                    summary="Bootstrap model/provider preference is active.",
                    detail=f"model_preference_id={model_preference_id}",
                )
            ]

        equivalent = self._equivalent_active_model_preference(latest)
        if equivalent is not None:
            if fix:
                self.store.update(
                    "onboarding_bootstraps",
                    latest["onboarding_bootstrap_id"],
                    {"model_preference_id": equivalent["model_preference_id"]},
                    emit_event=False,
                    actor_type="system",
                    actor_ref="doctor",
                )
                latest["model_preference_id"] = equivalent["model_preference_id"]
                actions.append(
                    {
                        "action": "relinked_model_preference",
                        "onboarding_bootstrap_id": latest["onboarding_bootstrap_id"],
                        "model_preference_id": equivalent["model_preference_id"],
                    }
                )
                return [
                    DoctorFinding(
                        check="model_provider_preference",
                        classification="fixable",
                        status="fixed",
                        summary="Relinked bootstrap to an equivalent active model/provider preference.",
                        fixable=True,
                        fixed=True,
                        action="updated onboarding_bootstraps.model_preference_id",
                    )
                ]
            return [
                DoctorFinding(
                    check="model_provider_preference",
                    classification="fixable",
                    status="fixable",
                    summary="Bootstrap model preference link is stale but an equivalent active preference exists.",
                    fixable=True,
                    detail="Run doctor --fix to relink metadata; no new provider trust is created.",
                )
            ]

        return [
            DoctorFinding(
                check="model_provider_preference",
                classification="blocked",
                status="blocked",
                summary="No active model/provider preference matches latest onboarding state.",
                detail="Doctor will not choose or create model-provider authority.",
            )
        ]

    def _inspect_model_execution_readiness(self, latest: dict[str, Any]) -> list[DoctorFinding]:
        provider = latest.get("provider")
        if not provider:
            return [
                DoctorFinding(
                    check="model_provider_execution",
                    classification="informational",
                    status="info",
                    summary="No provider is recorded for model execution readiness checks.",
                )
            ]
        readiness = inspect_provider_readiness(self.store, provider=str(provider))
        providers = readiness.get("providers") or []
        if not providers:
            return [
                DoctorFinding(
                    check="model_provider_execution",
                    classification="informational",
                    status="info",
                    summary=f"Provider is not in the current bounded execution catalog: {provider}.",
                    detail=readiness.get("disclosure"),
                )
            ]
        provider_readiness = providers[0]
        if provider_readiness.get("ready_for_live_attempt"):
            lanes = [
                item["lane"]
                for item in provider_readiness.get("lanes", [])
                if item.get("ready_for_live_attempt")
            ]
            return [
                DoctorFinding(
                    check="model_provider_execution",
                    classification="informational",
                    status="pass",
                    summary=f"At least one {provider} execution lane has local prerequisites for a live attempt.",
                    detail=f"ready_lanes={lanes}; live_proven=false",
                )
            ]
        missing = [
            {"lane": item.get("lane"), "missing": item.get("missing"), "status": item.get("status")}
            for item in provider_readiness.get("lanes", [])
        ]
        return [
            DoctorFinding(
                check="model_provider_execution",
                classification="informational",
                status="info",
                summary=f"No {provider} execution lane has all local prerequisites for a live attempt.",
                detail=f"missing={missing}",
            )
        ]

    def _inspect_channels(self, latest: dict[str, Any]) -> list[DoctorFinding]:
        findings: list[DoctorFinding] = []
        channels = latest.get("channels_json") or []
        enabled_channels = [item for item in channels if item.get("state") == "enabled"]
        if not channels:
            findings.append(
                DoctorFinding(
                    check="channel_enablement",
                    classification="blocked",
                    status="blocked",
                    summary="No channel choices are recorded in onboarding state.",
                    detail="Doctor will not invent enabled or deferred channels.",
                )
            )
            return findings

        findings.append(
            DoctorFinding(
                check="channel_enablement",
                classification="informational",
                status="pass",
                summary="Channel choices are recorded.",
                detail=", ".join(f"{item.get('channel')}={item.get('state')}" for item in channels),
            )
        )
        if not enabled_channels:
            findings.append(
                DoctorFinding(
                    check="channel_runtime",
                    classification="informational",
                    status="info",
                    summary="No initial channels are enabled.",
                    detail="This can be intentional; doctor treats it as not runnable for channel operation only.",
                )
            )
        for channel in enabled_channels:
            channel_name = str(channel.get("channel"))
            for requirement in SECRET_REQUIREMENTS.get(channel_name, []):
                if self._has_active_secret(str(requirement["integration"]), str(requirement["kind"])):
                    findings.append(
                        DoctorFinding(
                            check=f"{channel_name}_required_secret",
                            classification="informational",
                            status="pass",
                            summary=f"{channel_name} required secret handle is present.",
                            detail=f"{requirement['integration']}:{requirement['kind']}",
                        )
                    )
                else:
                    findings.append(
                        DoctorFinding(
                            check=f"{channel_name}_required_secret",
                            classification="blocked",
                            status="blocked",
                            summary=f"{channel_name} is enabled but a required secret handle is missing.",
                            detail="Doctor will not fabricate or ingest secrets; use trusted local secret onboarding.",
                        )
                    )
            if channel_name != "local":
                findings.append(
                    DoctorFinding(
                        check=f"{channel_name}_enrollment",
                        classification="informational",
                        status="info",
                        summary=f"{channel_name} enablement does not bypass enrollment or trust controls.",
                    )
                )
        return findings

    def _inspect_vault(self, active_secrets: list[dict[str, Any]], latest: dict[str, Any] | None) -> list[DoctorFinding]:
        findings: list[DoctorFinding] = []
        metadata_path = self.secret_root / "vault.json"
        if not active_secrets and not metadata_path.exists():
            findings.append(
                DoctorFinding(
                    check="vault_metadata",
                    classification="informational",
                    status="info",
                    summary="No vault metadata exists and no active secret records require it.",
                )
            )
            return findings
        if not metadata_path.exists():
            findings.append(
                DoctorFinding(
                    check="vault_metadata",
                    classification="blocked",
                    status="blocked",
                    summary="Vault metadata is missing while active secret records exist.",
                    detail="Doctor will not create new root-key metadata that could strand existing secrets.",
                )
            )
            return findings

        try:
            metadata = self._read_json_file(metadata_path)
        except ValueError as exc:
            findings.append(
                DoctorFinding(
                    check="vault_metadata",
                    classification="blocked",
                    status="blocked",
                    summary="Vault metadata is not valid JSON.",
                    detail=str(exc),
                )
            )
            return findings

        provider = metadata.get("provider_name")
        expected_providers = {item.get("root_key_provider") for item in active_secrets if item.get("root_key_provider")}
        if latest and latest.get("custody_mode"):
            expected_providers.add(latest["custody_mode"])
        if provider and expected_providers and provider not in expected_providers:
            findings.append(
                DoctorFinding(
                    check="vault_provider",
                    classification="blocked",
                    status="blocked",
                    summary="Vault provider metadata does not match canonical custody state.",
                    detail=f"vault={provider}; canonical={sorted(expected_providers)}",
                )
            )
        else:
            findings.append(
                DoctorFinding(
                    check="vault_metadata",
                    classification="informational",
                    status="pass",
                    summary="Vault metadata is present.",
                    detail=f"provider_name={provider}",
                )
            )

        for secret in active_secrets:
            findings.extend(self._inspect_secret_payload(secret))
        return findings

    def _inspect_secret_payload(self, secret: dict[str, Any]) -> list[DoctorFinding]:
        vault_ref = secret.get("vault_ref")
        if not vault_ref:
            return [
                DoctorFinding(
                    check="secret_payload",
                    classification="blocked",
                    status="blocked",
                    summary="Active secret record has no vault payload reference.",
                    detail=f"secret_id={secret['secret_id']}; handle_uri={secret['handle_uri']}",
                )
            ]
        payload_path = self._vault_ref_path(str(vault_ref))
        if payload_path is None or not payload_path.exists():
            return [
                DoctorFinding(
                    check="secret_payload",
                    classification="blocked",
                    status="blocked",
                    summary="Active secret record points to a missing vault payload.",
                    detail=f"secret_id={secret['secret_id']}; vault_ref={vault_ref}",
                )
            ]
        return [
            DoctorFinding(
                check="secret_payload",
                classification="informational",
                status="pass",
                summary="Active secret payload file exists.",
                detail=f"secret_id={secret['secret_id']}; version={secret['current_version']}",
            )
        ]

    def _inspect_onboarding_readiness(
        self,
        latest: dict[str, Any],
        *,
        fix: bool,
        actions: list[dict[str, Any]],
    ) -> list[DoctorFinding]:
        computed = self._compute_readiness(latest)
        expected_status = "ready" if computed["runnable"] else "incomplete"
        if latest.get("readiness_json") == computed and latest.get("status") == expected_status:
            return [
                DoctorFinding(
                    check="onboarding_readiness",
                    classification="informational",
                    status="pass",
                    summary="Stored onboarding readiness matches current canonical state.",
                )
            ]

        if fix:
            self.store.update(
                "onboarding_bootstraps",
                latest["onboarding_bootstrap_id"],
                {"readiness_json": computed, "status": expected_status},
                emit_event=False,
                actor_type="system",
                actor_ref="doctor",
            )
            latest["readiness_json"] = computed
            latest["status"] = expected_status
            actions.append(
                {
                    "action": "refreshed_onboarding_readiness",
                    "onboarding_bootstrap_id": latest["onboarding_bootstrap_id"],
                    "status": expected_status,
                    "runnable": computed["runnable"],
                }
            )
            return [
                DoctorFinding(
                    check="onboarding_readiness",
                    classification="fixable",
                    status="fixed",
                    summary="Refreshed stale onboarding readiness metadata.",
                    fixable=True,
                    fixed=True,
                    action="updated onboarding_bootstraps.readiness_json/status",
                )
            ]

        return [
            DoctorFinding(
                check="onboarding_readiness",
                classification="fixable",
                status="fixable",
                summary="Stored onboarding readiness is stale relative to current canonical state.",
                detail="Run doctor --fix to refresh metadata only.",
                fixable=True,
            )
        ]

    def _compute_readiness(self, latest: dict[str, Any]) -> dict[str, Any]:
        passed: list[str] = []
        missing: list[str] = []
        deferred: list[str] = []
        primary_user_id = latest.get("primary_operator_user_id")
        channels = [dict(item) for item in (latest.get("channels_json") or [])]

        if primary_user_id and self._active_user_exists(primary_user_id):
            passed.append("primary_operator")
        else:
            missing.append("primary_operator")

        if latest.get("custody_mode"):
            passed.append("root_key_custody_selected")
        else:
            missing.append("root_key_custody_selected")

        if latest.get("provider") and latest.get("model") and self._has_equivalent_active_model_preference(latest):
            passed.append("model_provider_preference")
        else:
            missing.append("model_provider_preference")

        enabled_channels = [item for item in channels if item.get("state") == "enabled"]
        if enabled_channels:
            passed.append("channel_enablement_recorded")
        else:
            deferred.append("no_initial_channels_enabled")
        for channel in enabled_channels:
            channel_name = str(channel.get("channel"))
            requirements = SECRET_REQUIREMENTS.get(channel_name, [])
            unmet = [
                f"{req['integration']}:{req['kind']}"
                for req in requirements
                if not self._has_active_secret(str(req["integration"]), str(req["kind"]))
            ]
            if unmet:
                missing.append(f"{channel_name}_required_secret")
            if channel_name != "local":
                channel["note"] = "Channel enablement does not bypass enrollment or trust checks."
        for channel in channels:
            if channel.get("state") == "deferred":
                deferred.append(f"{channel['channel']}_channel")

        runnable = not missing
        return {
            "runnable": runnable,
            "runnable_scope": "bounded_local" if runnable else "not_runnable",
            "passed": passed,
            "missing": sorted(set(missing)),
            "deferred": sorted(set(deferred)),
            "model_execution": self._computed_model_execution_readiness(latest.get("provider")),
            "summary": "Ready for bounded local operation." if runnable else "Onboarding state is incomplete.",
        }

    def _computed_model_execution_readiness(self, provider: Any) -> dict[str, Any] | None:
        if not provider:
            return None
        readiness = inspect_provider_readiness(self.store, provider=str(provider))
        return readiness["providers"][0] if readiness.get("providers") else None

    def _maybe_fix_directory(
        self,
        *,
        check: str,
        path: Path,
        fix: bool,
        summary: str,
        action_label: str,
        detail: str | None = None,
    ) -> DoctorFinding:
        if path.exists() and path.is_dir():
            return DoctorFinding(
                check=check,
                classification="informational",
                status="pass",
                summary=f"{check} exists.",
                detail=str(path),
            )
        if path.exists() and not path.is_dir():
            return DoctorFinding(
                check=check,
                classification="blocked",
                status="blocked",
                summary=f"{check} path exists but is not a directory.",
                detail=str(path),
            )
        if fix:
            path.mkdir(parents=True, exist_ok=True)
            return DoctorFinding(
                check=check,
                classification="fixable",
                status="fixed",
                summary=summary,
                detail=detail or str(path),
                fixable=True,
                fixed=True,
                action=action_label,
            )
        return DoctorFinding(
            check=check,
            classification="fixable",
            status="fixable",
            summary=summary,
            detail=detail or str(path),
            fixable=True,
        )

    def _record_doctor_audit(self, actions: list[dict[str, Any]]) -> None:
        with self.store.connect() as conn:
            audit = self.store.insert(
                "audit_events",
                {
                    "audit_event_id": new_id("aud"),
                    "event_type": "doctor_fix_applied",
                    "actor_type": "system",
                    "actor_ref": "doctor",
                    "object_type": "local_installation",
                    "object_ref": str(self.store.db_path),
                    "action_summary": "AgentFirst doctor applied bounded local fixes",
                    "outcome": "fixed",
                    "metadata_json": {"actions": actions},
                },
                conn=conn,
                emit_event=False,
            )
            self.store.append_event(
                "doctor_fix_applied",
                "local_installation",
                str(self.store.db_path),
                "system",
                "doctor",
                {"audit_event_id": audit["audit_event_id"], "actions": actions},
                audit_event_id=audit["audit_event_id"],
                conn=conn,
            )
            conn.commit()

    def _latest_bootstrap(self) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM onboarding_bootstraps
                ORDER BY created_at DESC, onboarding_bootstrap_id DESC
                LIMIT 1
                """
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _primary_operator(self) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE primary_user_flag = 1 AND status = 'active'").fetchone()
            return self.store._decode_row(row) if row else None

    def _active_user_exists(self, user_id: str) -> bool:
        with self.store.connect() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ? AND status = 'active'", (user_id,)).fetchone()
            return row is not None

    def _active_model_preference_by_id(self, model_preference_id: str) -> bool:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT model_preference_id FROM model_provider_preferences
                WHERE model_preference_id = ? AND status = 'active'
                """,
                (model_preference_id,),
            ).fetchone()
            return row is not None

    def _equivalent_active_model_preference(self, latest: dict[str, Any]) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM model_provider_preferences
                WHERE scope_type = 'user'
                  AND scope_ref = ?
                  AND purpose = 'general'
                  AND provider = ?
                  AND model = ?
                  AND status = 'active'
                ORDER BY priority ASC, created_at DESC, model_preference_id DESC
                LIMIT 1
                """,
                (latest.get("primary_operator_user_id"), latest.get("provider"), latest.get("model")),
            ).fetchone()
            return self.store._decode_row(row) if row else None

    def _has_equivalent_active_model_preference(self, latest: dict[str, Any]) -> bool:
        return self._equivalent_active_model_preference(latest) is not None

    def _has_active_secret(self, integration: str, kind: str) -> bool:
        with self.store.connect() as conn:
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

    def _active_secrets(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM secret_records
                WHERE status = 'active'
                ORDER BY integration_type, secret_kind, handle_uri
                """
            ).fetchall()
            return [self.store._decode_row(row) for row in rows]

    def _vault_ref_path(self, vault_ref: str) -> Path | None:
        if not vault_ref.startswith("vault://"):
            return None
        parts = vault_ref.removeprefix("vault://").split("/")
        if len(parts) != 2 or not parts[1].startswith("v"):
            return None
        secret_id = parts[0]
        version = parts[1][1:]
        if not secret_id or not version.isdigit():
            return None
        return self.secret_root / "records" / secret_id / f"v{version}.json"

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        try:
            import json

            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - surface parse/read failure in doctor output.
            raise ValueError(f"{path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: expected JSON object")
        return loaded

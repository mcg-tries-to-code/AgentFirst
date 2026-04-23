"""Point-in-time model provider catalog and local lane readiness checks."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import AgentFirstStore


CATALOG_SNAPSHOT_VERSION = "2026-04-22"
CATALOG_DISCLOSURE = (
    "Provider model availability is a bounded point-in-time snapshot. Refresh this catalog "
    "against provider docs and account entitlements before treating it as current."
)


@dataclass(frozen=True)
class ProviderLane:
    lane: str
    transport: str
    secret_kind: str | None = None
    default_secret_handle: str | None = None
    binary_names: tuple[str, ...] = ()
    status: str = "structural"
    note: str = ""


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    model: str
    family: str
    notes: str = ""


@dataclass(frozen=True)
class ProviderCatalogEntry:
    provider: str
    display_name: str
    destination_identity: str
    trust_tier: int
    local: bool
    models: tuple[ProviderModel, ...]
    lanes: tuple[ProviderLane, ...]
    notes: str = ""


PROVIDER_CATALOG: tuple[ProviderCatalogEntry, ...] = (
    ProviderCatalogEntry(
        provider="openai",
        display_name="OpenAI",
        destination_identity="openai",
        trust_tier=1,
        local=False,
        notes="OpenAI execution is implemented for API-key and Codex CLI lanes.",
        models=(
            ProviderModel("openai", "gpt-5.4", "gpt-5", "Primary configured OpenAI model for this AgentFirst slice."),
            ProviderModel("openai", "gpt-5.2", "gpt-5", "Modern OpenAI GPT-5 line snapshot entry."),
            ProviderModel("openai", "gpt-5.1", "gpt-5", "Modern OpenAI GPT-5 line snapshot entry."),
            ProviderModel("openai", "gpt-4.1", "gpt-4.1", "General text/code model snapshot entry."),
            ProviderModel("openai", "o3", "reasoning", "Reasoning model snapshot entry."),
            ProviderModel("openai", "o4-mini", "reasoning", "Smaller reasoning model snapshot entry."),
        ),
        lanes=(
            ProviderLane(
                lane="api",
                transport="openai_responses_api",
                secret_kind="api_key",
                default_secret_handle="secret://openai.api_key",
                status="implemented",
                note="Uses the OpenAI Responses API with an API key from the secret broker.",
            ),
            ProviderLane(
                lane="codex_cli",
                transport="codex_cli_exec",
                binary_names=("codex",),
                status="implemented",
                note="Uses local Codex CLI subscription-backed execution when installed and configured.",
            ),
        ),
    ),
    ProviderCatalogEntry(
        provider="anthropic",
        display_name="Anthropic",
        destination_identity="anthropic",
        trust_tier=1,
        local=False,
        notes="Structural readiness only in this slice; live execution is not exercised.",
        models=(
            ProviderModel("anthropic", "claude-opus-4-5", "claude", "Point-in-time Claude Opus line snapshot entry."),
            ProviderModel("anthropic", "claude-sonnet-4-5", "claude", "Point-in-time Claude Sonnet line snapshot entry."),
            ProviderModel("anthropic", "claude-haiku-4-5", "claude", "Point-in-time Claude Haiku line snapshot entry."),
        ),
        lanes=(
            ProviderLane(
                lane="api",
                transport="anthropic_api",
                secret_kind="api_key",
                default_secret_handle="secret://anthropic.api_key",
                status="scaffold",
                note="Secret requirement and lane shape are recorded; live adapter is not implemented in this slice.",
            ),
            ProviderLane(
                lane="claude_code_cli",
                transport="claude_code_cli",
                binary_names=("claude",),
                status="scaffold",
                note="CLI readiness is checked by binary presence; live adapter is not implemented in this slice.",
            ),
        ),
    ),
    ProviderCatalogEntry(
        provider="google",
        display_name="Google",
        destination_identity="google",
        trust_tier=1,
        local=False,
        notes="Structural readiness only in this slice; live execution is not exercised.",
        models=(
            ProviderModel("google", "gemini-3-pro", "gemini", "Point-in-time Gemini Pro line snapshot entry."),
            ProviderModel("google", "gemini-2.5-pro", "gemini", "Gemini 2.5 Pro snapshot entry."),
            ProviderModel("google", "gemini-2.5-flash", "gemini", "Gemini 2.5 Flash snapshot entry."),
            ProviderModel("google", "gemini-2.5-flash-lite", "gemini", "Gemini 2.5 Flash Lite snapshot entry."),
        ),
        lanes=(
            ProviderLane(
                lane="api",
                transport="google_ai_api",
                secret_kind="api_credential",
                default_secret_handle="secret://google.ai.api_credential",
                status="scaffold",
                note="Credential requirement and lane shape are recorded; live adapter is not implemented in this slice.",
            ),
            ProviderLane(
                lane="antigravity_cli",
                transport="antigravity_cli",
                binary_names=("antigravity",),
                status="scaffold",
                note="CLI readiness is checked by binary presence; live adapter is not implemented in this slice.",
            ),
        ),
    ),
    ProviderCatalogEntry(
        provider="local",
        display_name="Local CLI",
        destination_identity="local",
        trust_tier=0,
        local=True,
        notes="Local route remains a governance fallback placeholder; no llama.cpp live adapter is implemented.",
        models=(ProviderModel("local", "llama.cpp-default", "local", "Existing bounded fallback placeholder."),),
        lanes=(),
    ),
)


def bounded_model_providers() -> list[dict[str, Any]]:
    """Flatten the catalog into the legacy provider/model shape used by routing."""
    rows: list[dict[str, Any]] = []
    for entry in PROVIDER_CATALOG:
        for model in entry.models:
            rows.append(
                {
                    "provider": entry.provider,
                    "model": model.model,
                    "destination_identity": entry.destination_identity,
                    "trust_tier": entry.trust_tier,
                    "local": entry.local,
                    "catalog_snapshot_version": CATALOG_SNAPSHOT_VERSION,
                    "catalog_disclosure": CATALOG_DISCLOSURE,
                }
            )
    return rows


def provider_catalog_as_dict() -> dict[str, Any]:
    return {
        "snapshot_version": CATALOG_SNAPSHOT_VERSION,
        "disclosure": CATALOG_DISCLOSURE,
        "providers": [
            {
                "provider": entry.provider,
                "display_name": entry.display_name,
                "destination_identity": entry.destination_identity,
                "trust_tier": entry.trust_tier,
                "local": entry.local,
                "notes": entry.notes,
                "models": [model.__dict__ for model in entry.models],
                "lanes": [
                    {
                        "lane": lane.lane,
                        "transport": lane.transport,
                        "secret_kind": lane.secret_kind,
                        "default_secret_handle": lane.default_secret_handle,
                        "binary_names": list(lane.binary_names),
                        "status": lane.status,
                        "note": lane.note,
                    }
                    for lane in entry.lanes
                ],
            }
            for entry in PROVIDER_CATALOG
        ],
    }


def find_provider(provider: str) -> ProviderCatalogEntry | None:
    return next((entry for entry in PROVIDER_CATALOG if entry.provider == provider), None)


def find_model(provider: str, model: str) -> ProviderModel | None:
    entry = find_provider(provider)
    if entry is None:
        return None
    return next((item for item in entry.models if item.model == model), None)


def provider_secret_requirements() -> dict[str, list[dict[str, str]]]:
    requirements: dict[str, list[dict[str, str]]] = {}
    for entry in PROVIDER_CATALOG:
        for lane in entry.lanes:
            if lane.secret_kind:
                requirements.setdefault(entry.provider, []).append(
                    {
                        "integration": "model_provider",
                        "provider": entry.provider,
                        "kind": lane.secret_kind,
                        "handle": lane.default_secret_handle or "",
                        "lane": lane.lane,
                    }
                )
    return requirements


def inspect_provider_readiness(
    store: AgentFirstStore,
    *,
    provider: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Report local lane readiness without reading or printing secret plaintext."""
    providers = [find_provider(provider)] if provider else list(PROVIDER_CATALOG)
    home = home or Path.home()
    results = []
    for entry in [item for item in providers if item is not None]:
        lane_results = []
        for lane in entry.lanes:
            lane_results.append(_inspect_lane(store, entry, lane, home=home))
        ready_lanes = [item for item in lane_results if item["ready_for_live_attempt"]]
        results.append(
            {
                "provider": entry.provider,
                "display_name": entry.display_name,
                "snapshot_version": CATALOG_SNAPSHOT_VERSION,
                "models": [item.model for item in entry.models],
                "lanes": lane_results,
                "ready_for_live_attempt": bool(ready_lanes),
                "live_proven": False,
                "disclosure": (
                    "At least one lane has local prerequisites for a live attempt; execution still records "
                    "actual success/failure."
                    if ready_lanes
                    else "No lane currently has all local prerequisites for a live attempt."
                ),
            }
        )
    return {"snapshot_version": CATALOG_SNAPSHOT_VERSION, "disclosure": CATALOG_DISCLOSURE, "providers": results}


def _inspect_lane(
    store: AgentFirstStore,
    entry: ProviderCatalogEntry,
    lane: ProviderLane,
    *,
    home: Path,
) -> dict[str, Any]:
    checks: list[str] = []
    missing: list[str] = []
    secret_present = None
    binary_path = None
    config_marker = None

    if lane.secret_kind:
        secret_present = _has_provider_secret(store, entry.provider, lane.secret_kind, lane.default_secret_handle)
        if secret_present:
            checks.append("secret_handle_present")
        else:
            missing.append(f"secret:{lane.default_secret_handle or lane.secret_kind}")

    if lane.binary_names:
        for binary in lane.binary_names:
            binary_path = shutil.which(binary)
            if binary_path:
                break
        if binary_path:
            checks.append(f"binary_present:{Path(binary_path).name}")
        else:
            missing.append(f"binary:{'/'.join(lane.binary_names)}")
        if lane.lane == "codex_cli":
            marker_paths = [home / ".codex" / "auth.json", home / ".codex" / "config.toml"]
            config_marker = next((str(path) for path in marker_paths if path.exists()), None)
            if config_marker:
                checks.append("configuration_marker_present")
            else:
                missing.append("codex_cli_configuration_marker")

    implemented = lane.status == "implemented"
    ready = implemented and not missing
    return {
        "lane": lane.lane,
        "transport": lane.transport,
        "status": lane.status,
        "implemented": implemented,
        "ready_for_live_attempt": ready,
        "secret_present": secret_present,
        "binary_path": binary_path,
        "configuration_marker": config_marker,
        "checks": checks,
        "missing": missing,
        "note": lane.note,
    }


def _has_provider_secret(
    store: AgentFirstStore,
    provider: str,
    secret_kind: str,
    default_handle: str | None,
) -> bool:
    store.initialize()
    with store.connect() as conn:
        params: list[Any] = ["model_provider", secret_kind, provider]
        row = conn.execute(
            """
            SELECT secret_id FROM secret_records
            WHERE integration_type = ?
              AND secret_kind = ?
              AND status = 'active'
              AND json_extract(metadata_json, '$.provider') = ?
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is not None:
            return True
        if default_handle:
            row = conn.execute(
                """
                SELECT secret_id FROM secret_records
                WHERE handle_uri = ?
                  AND integration_type = 'model_provider'
                  AND status = 'active'
                LIMIT 1
                """,
                (default_handle,),
            ).fetchone()
            return row is not None
        return False

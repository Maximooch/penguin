#!/usr/bin/env python3
"""Read the authenticated Codex model catalog without making inference requests.

Run from the repository: uv run python scripts/probe_codex_service_tiers.py
Use --auth-file ~/.codex/auth.json to choose a credential store explicitly.
Missing tier metadata means unknown, not proof that a tier is unsupported.
Credentials and raw response bodies are never included in the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

CATALOG_URL = "https://chatgpt.com/backend-api/codex/models"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

__all__ = ["load_credentials", "main", "query_catalog", "summarize_catalog"]


def load_credentials(auth_file: Path | None = None) -> tuple[str, str | None]:
    """Read OAuth credentials without refreshing or modifying their store.

    Environment OAuth credentials take precedence unless a file is specified.
    API keys are deliberately not used for this ChatGPT-backed endpoint.
    """
    if auth_file is None:
        access = os.getenv("OPENAI_OAUTH_ACCESS_TOKEN", "").strip()
        if access:
            return access, os.getenv("OPENAI_ACCOUNT_ID") or None
        explicit = os.getenv("PENGUIN_PROVIDER_CREDENTIALS_STORE") or os.getenv(
            "PENGUIN_PROVIDER_AUTH_STORE"
        )
        paths = (
            [Path(explicit).expanduser()]
            if explicit
            else [
                Path.home() / ".config/penguin/providers/credentials.json",
                Path.home() / ".config/penguin/provider_auth.json",
                Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
                / "auth.json",
            ]
        )
    else:
        paths = [auth_file.expanduser()]
    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Cannot read credential JSON; check the auth file."
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("Credential JSON must be an object.")
        providers = payload.get("providers")
        record = providers.get("openai") if isinstance(providers, dict) else None
        if isinstance(record, dict) and record.get("type") == "oauth":
            access, account = record.get("access"), record.get("accountId")
        else:
            tokens = payload.get("tokens")
            if not isinstance(tokens, dict):
                continue
            access, account = tokens.get("access_token"), tokens.get("account_id")
        if isinstance(access, str) and access.strip():
            return access.strip(), (
                account.strip()
                if isinstance(account, str) and account.strip()
                else None
            )
    raise ValueError("No OAuth credentials found. Sign in with Penguin or Codex first.")


def _tier_ids(value: Any) -> list[str]:
    """Extract native catalog tier IDs, including legacy string entries."""
    if not isinstance(value, list):
        return []
    ids = []
    for item in value:
        tier = item.get("id") if isinstance(item, dict) else item
        if isinstance(tier, str) and tier.strip():
            normalized = tier.strip().lower()
            if normalized not in ids:
                ids.append(normalized)
    return ids


def summarize_catalog(payload: Any) -> list[dict[str, Any]]:
    """Allowlist model metadata and classify advertisement, not entitlement."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("Catalog response lacks a models list.")
    result = []
    for model in payload["models"]:
        if not isinstance(model, dict):
            raise ValueError("Catalog contains a non-object model entry.")
        model_id = model.get("slug") or model.get("id") or model.get("model")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("Catalog model is missing an identifier.")
        tiers = _tier_ids(model.get("service_tiers"))
        legacy = _tier_ids(model.get("additional_speed_tiers"))
        default = model.get("default_service_tier")
        default = default if isinstance(default, str) else None
        advertised = (
            "ultrafast" in tiers
            or "ultrafast" in legacy
            or (default is not None and default.strip().lower() == "ultrafast")
        )
        metadata_present = (
            any(
                isinstance(model.get(key), list)
                for key in ("service_tiers", "additional_speed_tiers")
            )
            or default is not None
        )
        name = model.get("display_name")
        result.append(
            {
                "model": model_id,
                "display_name": name if isinstance(name, str) else model_id,
                "service_tiers": tiers,
                "additional_speed_tiers": legacy,
                "default_service_tier": default,
                "ultrafast": (
                    "advertised"
                    if advertised
                    else "not_advertised" if metadata_present else "unknown"
                ),
            }
        )
    return sorted(result, key=lambda item: item["model"])


def query_catalog(
    access: str,
    account: str | None,
    *,
    client_version: str = "1.0.0",
    timeout: float = 20.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """GET the fixed official host; refuse redirects and bound response size.

    This uses the same endpoint and client_version query as Penguin discovery.
    An absent advertisement does not prove inference would reject the tier.
    """
    headers = {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
        "User-Agent": "penguin-service-tier-probe/1.0",
    }
    if account:
        headers["ChatGPT-Account-ID"] = account
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            with client.stream(
                "GET",
                CATALOG_URL,
                headers=headers,
                params={"client_version": client_version},
            ) as response:
                if response.status_code != 200:
                    hint = (
                        " Sign in again; this script does not refresh tokens."
                        if response.status_code == 401
                        else ""
                    )
                    raise ValueError(
                        f"Catalog HTTP {response.status_code}.{hint} "
                        "No response body logged."
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("Catalog response exceeded the size limit.")
                    body.extend(chunk)
        return summarize_catalog(json.loads(body))
    except httpx.HTTPError as exc:
        raise ValueError("Catalog network request failed; check connectivity.") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Catalog returned invalid JSON; no response body logged."
        ) from exc


def main(argv: list[str] | None = None) -> int:
    """Print an account-safe report; return nonzero for discovery failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-file", type=Path, help="Penguin or Codex OAuth JSON")
    parser.add_argument(
        "--client-version",
        default="1.0.0",
        help="Catalog gating version (Penguin default: 1.0.0)",
    )
    parser.add_argument(
        "--model", help="Case-insensitive model/name filter, e.g. astra"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print only allowlisted report JSON"
    )
    args = parser.parse_args(argv)
    try:
        access, account = load_credentials(args.auth_file)
        models = query_catalog(access, account, client_version=args.client_version)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    filtered = [
        m
        for m in models
        if not args.model
        or args.model.lower() in (m["model"] + " " + m["display_name"]).lower()
    ]
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "client_version": args.client_version,
        "catalog_model_count": len(models),
        "models": filtered,
        "note": (
            "Catalog advertisement only; " "no inference or entitlement test performed."
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Codex catalog: {len(models)} models "
            f"(client_version={args.client_version})"
        )
        for model in filtered:
            tiers = (
                ", ".join(model["service_tiers"] + model["additional_speed_tiers"])
                or "none listed"
            )
            print(
                f"{model['model']}: ultrafast={model['ultrafast']}; "
                f"tiers={tiers}; "
                f"default={model['default_service_tier'] or 'unset'}"
            )
        if not filtered:
            print("No matching models returned by the catalog.")
        print(report["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

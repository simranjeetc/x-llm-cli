"""x — GitHub Copilot SSO auth.

Device flow  →  GitHub OAuth token  →  Copilot bearer token  →  store.
Auto-refresh the ~30-min Copilot bearer using the stored GitHub token.
"""

from __future__ import annotations

import sys
import time
from typing import Any

import httpx

from x.auth import store

_GH_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_DEVICE_CODE_URL = "https://github.com/login/device/code"
_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_REFRESH_BUFFER = 5 * 60  # refresh if within 5 minutes of expiry


_COPILOT_HEADERS = {
    "Accept": "application/json",
    "editor-version": "vscode/1.95.0",
    "editor-plugin-version": "copilot/1.245.0",
    "User-Agent": "GithubCopilot/1.245.0",
    "Copilot-Integration-Id": "vscode-chat",
}


def _exchange_copilot_token(github_token: str) -> dict[str, Any]:
    """Exchange a GitHub token for a Copilot bearer token."""
    resp = httpx.get(
        _COPILOT_TOKEN_URL,
        headers={**_COPILOT_HEADERS, "Authorization": f"token {github_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def login() -> None:
    """Run GitHub device flow, exchange for Copilot token, persist to store."""
    # Step 1: request device code
    resp = httpx.post(
        _DEVICE_CODE_URL,
        data={"client_id": _GH_CLIENT_ID, "scope": "read:user"},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    device = resp.json()

    print(f"\nOpen: {device['verification_uri']}", file=sys.stderr)
    print(f"Code: {device['user_code']}\n", file=sys.stderr)
    print("Waiting for authorization...", file=sys.stderr)

    interval = int(device.get("interval", 5))
    expires_in = int(device.get("expires_in", 900))
    deadline = time.time() + expires_in

    # Step 2: poll until authorized or expired
    github_token: str | None = None
    while time.time() < deadline:
        time.sleep(interval)
        poll = httpx.post(
            _OAUTH_TOKEN_URL,
            data={
                "client_id": _GH_CLIENT_ID,
                "device_code": device["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        poll.raise_for_status()
        payload = poll.json()
        err = payload.get("error")
        if err == "authorization_pending":
            continue
        elif err == "slow_down":
            interval += 5
            continue
        elif err == "expired_token":
            print("error: device code expired, run `x login copilot` again", file=sys.stderr)
            sys.exit(1)
        elif err:
            print(f"error: {payload.get('error_description', err)}", file=sys.stderr)
            sys.exit(1)
        github_token = payload["access_token"]
        break

    if not github_token:
        print("error: authorization timed out", file=sys.stderr)
        sys.exit(1)

    # Step 3: exchange for Copilot token
    copilot_data = _exchange_copilot_token(github_token)
    copilot_token = copilot_data.get("token") or copilot_data.get("access_token", "")
    expires_at = int(copilot_data.get("expires_at", time.time() + 1800))

    store.save("copilot", {
        "github_token": github_token,
        "copilot_token": copilot_token,
        "expires_at": expires_at,
    })
    print("Copilot login successful.", file=sys.stderr)


def get_token() -> str:
    """Return a valid Copilot bearer token, refreshing if near expiry."""
    data = store.load("copilot")
    if not data:
        print("error: not logged in to Copilot — run `x login copilot`", file=sys.stderr)
        sys.exit(1)

    if time.time() >= data["expires_at"] - _REFRESH_BUFFER:
        # Refresh via stored GitHub token
        copilot_data = _exchange_copilot_token(data["github_token"])
        data["copilot_token"] = copilot_data.get("token") or copilot_data.get("access_token", "")
        data["expires_at"] = int(copilot_data.get("expires_at", time.time() + 1800))
        store.save("copilot", data)

    return data["copilot_token"]


def logout() -> None:
    store.delete("copilot")
    print("Logged out of Copilot.", file=sys.stderr)

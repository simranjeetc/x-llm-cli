"""x — ChatGPT Plus SSO auth (PKCE flow).

Isolated custom path — does NOT use LiteLLM because the ChatGPT backend
endpoints are not OpenAI-compatible.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import httpx

from x.auth import store

# Codex CLI public client — no iOS preauth/DeviceCheck required.
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_REDIRECT_URI = "http://localhost:1455/auth/callback"
_CALLBACK_PORT = 1455
_AUTH_URL = "https://auth.openai.com/oauth/authorize"   # note: /oauth/ prefix
_TOKEN_URL = "https://auth.openai.com/oauth/token"
_SCOPE = "openid profile email offline_access"
_CHAT_URL = "https://chatgpt.com/backend-api/conversation"
_REFRESH_BUFFER = 5 * 60


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def login() -> None:
    """PKCE OAuth flow for ChatGPT Plus using Codex CLI client (no preauth cookie needed)."""
    code_verifier = _b64url(secrets.token_bytes(48))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
    state = secrets.token_urlsafe(16)

    params = {
        "response_type": "code",
        "client_id": _CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{_AUTH_URL}?{urlencode(params)}"

    # Local callback server — captures code without user having to paste a URL.
    received: dict[str, str] = {}
    done = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass  # silence request logs

        def do_GET(self) -> None:
            qs = parse_qs(urlparse(self.path).query)
            received["code"] = (qs.get("code") or [""])[0]
            received["state"] = (qs.get("state") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Login successful &#10003; You may close this tab.</h2>")
            done.set()

    server = HTTPServer(("127.0.0.1", _CALLBACK_PORT), _Handler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    print("\nOpen this URL in your browser to log in:", file=sys.stderr)
    print(auth_url, file=sys.stderr)
    print("\nWaiting for browser callback on localhost:1455 ...", file=sys.stderr)

    done.wait(timeout=300)
    server.server_close()

    code = received.get("code", "")
    if not code:
        print("error: no authorization code received (timed out or cancelled)", file=sys.stderr)
        sys.exit(1)
    if received.get("state") != state:
        print("error: state mismatch — possible CSRF", file=sys.stderr)
        sys.exit(1)

    # Exchange code for tokens — must be form-encoded, not JSON.
    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": _CLIENT_ID,
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()

    expires_at = int(time.time()) + int(tokens.get("expires_in", 3600))
    store.save("chatgpt", {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "id_token": tokens.get("id_token", ""),
        "expires_at": expires_at,
    })
    print("ChatGPT login successful.", file=sys.stderr)


def get_token() -> str:
    """Return a valid ChatGPT access token, refreshing if near expiry."""
    data = store.load("chatgpt")
    if not data:
        print("error: not logged in to ChatGPT — run `x login chatgpt`", file=sys.stderr)
        sys.exit(1)

    if time.time() >= data["expires_at"] - _REFRESH_BUFFER:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": _CLIENT_ID,
                "refresh_token": data["refresh_token"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        tokens = resp.json()
        data["access_token"] = tokens["access_token"]
        data["refresh_token"] = tokens.get("refresh_token", data["refresh_token"])
        data["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
        store.save("chatgpt", data)

    return data["access_token"]


def logout() -> None:
    store.delete("chatgpt")
    print("Logged out of ChatGPT.", file=sys.stderr)


def _build_body(prompt: str, model: str) -> dict:
    return {
        "action": "next",
        "messages": [
            {
                "id": str(uuid4()),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            }
        ],
        "model": model,
        "parent_message_id": str(uuid4()),
    }


def stream_complete(prompt: str, model: str):
    """Yield text chunks from ChatGPT backend SSE stream.

    ChatGPT sends cumulative content in each event, so we compute
    the delta by diffing against the previous snapshot.
    """
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    prev = ""
    with httpx.stream(
        "POST",
        _CHAT_URL,
        json=_build_body(prompt, model),
        headers=headers,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw.strip() == "[DONE]":
                break
            try:
                obj = json.loads(raw)
                parts = (
                    obj.get("message", {})
                    .get("content", {})
                    .get("parts", [])
                )
                if parts and isinstance(parts[0], str):
                    current = parts[0]
                    delta = current[len(prev):]
                    if delta:
                        yield delta
                    prev = current
            except (json.JSONDecodeError, KeyError):
                continue


def complete(prompt: str, model: str) -> str:
    """Return full buffered response from ChatGPT backend."""
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    last_content = ""
    with httpx.stream(
        "POST",
        _CHAT_URL,
        json=_build_body(prompt, model),
        headers=headers,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw.strip() == "[DONE]":
                break
            try:
                obj = json.loads(raw)
                parts = (
                    obj.get("message", {})
                    .get("content", {})
                    .get("parts", [])
                )
                if parts and isinstance(parts[0], str):
                    last_content = parts[0]
            except (json.JSONDecodeError, KeyError):
                continue
    return last_content

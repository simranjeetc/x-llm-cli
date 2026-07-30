"""x — completion core.

Provides:
  stream_completion() — generator yielding text chunks (LiteLLM or custom path)
  complete()          — blocking, returns full response string

Routing:
  copilot/<model>  → LiteLLM with Copilot bearer injected
  chatgpt/<model>  → custom httpx path (non-LiteLLM)
  anything else    → LiteLLM default (API key from env)
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import litellm


def _is_copilot(model: str) -> bool:
    return model.startswith("copilot/")


def _is_chatgpt(model: str) -> bool:
    return model.startswith("chatgpt/")


def _copilot_kwargs(model: str) -> dict[str, Any]:
    from x.auth.copilot import get_token
    token = get_token()
    inner = model[len("copilot/"):]
    return {
        "model": f"openai/{inner}",
        "api_base": "https://api.githubcopilot.com",
        "api_key": token,
        "extra_headers": {
            "Editor-Version": "vscode/1.95.0",
            "Editor-Plugin-Version": "copilot/1.245.0",
            "User-Agent": "GithubCopilot/1.245.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    }


def stream_completion(
    prompt: str,
    model: str,
    temperature: float = 0.0,
    timeout: int = 60,
) -> Generator[str, None, None]:
    """Yield text chunks streamed from the model.

    Routes copilot/* and chatgpt/* to their respective SSO paths.
    Raises any exception to the caller — no stderr writes here.
    """
    if _is_chatgpt(model):
        from x.auth.chatgpt import stream_complete
        inner = model[len("chatgpt/"):]
        yield from stream_complete(prompt, inner)
        return

    extra: dict[str, Any] = {}
    if _is_copilot(model):
        extra = _copilot_kwargs(model)
        litellm_model = extra.pop("model")
    else:
        litellm_model = model

    response = litellm.completion(
        model=litellm_model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        temperature=temperature,
        timeout=timeout,
        **extra,
    )

    for chunk in response:
        try:
            content: str | None = chunk.choices[0].delta.content  # type: ignore[union-attr]
        except (AttributeError, IndexError):
            continue
        if content:
            yield content


def complete(
    prompt: str,
    model: str,
    temperature: float = 0.0,
    timeout: int = 60,
) -> str:
    """Return the full model response as a string (non-streaming)."""
    if _is_chatgpt(model):
        from x.auth.chatgpt import complete as chatgpt_complete
        inner = model[len("chatgpt/"):]
        return chatgpt_complete(prompt, inner)

    extra: dict[str, Any] = {}
    if _is_copilot(model):
        extra = _copilot_kwargs(model)
        litellm_model = extra.pop("model")
    else:
        litellm_model = model

    response = litellm.completion(
        model=litellm_model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        temperature=temperature,
        timeout=timeout,
        **extra,
    )
    return response.choices[0].message.content or ""

# x — provider-agnostic LLM CLI

One command for LLM questions from the terminal, over providers you already
have: GitHub Copilot (SSO), ChatGPT Plus (SSO), or any API-key provider via
LiteLLM.

> Installs as `llm` (`[project.scripts] llm = "x.cli:main"`). Examples below
> use `x` for brevity — same command.

## Usage

```bash
x "what is 2+2"                    # one-shot, streams answer to stdout
cat notes.md | x "explain this"    # stdin merged as context (arg first, stdin appended)
x                                  # no-arg on TTY: read prompt until Ctrl-D
x -m copilot/gpt-4o "..."          # Copilot SSO
x -m chatgpt/gpt-4o "..."          # ChatGPT Plus SSO
x --no-stream --json "..."         # buffered JSON: {model, response}
```

## Auth (SSO — no API keys)

| Provider | Command | Flow |
|---|---|---|
| GitHub Copilot | `x login copilot` | GitHub device flow → Copilot bearer (~30 min expiry, auto-refreshed from stored GitHub token) |
| ChatGPT | `x login chatgpt` | PKCE via Codex CLI public client; local callback server on `localhost:1455` |

`x login --list` lists authenticated providers. `x logout <provider>` removes
stored credentials. Credentials live in `~/.config/x/auth.json` (chmod 600).

## Model routing

| Model string | Path |
|---|---|
| `copilot/<model>` | LiteLLM against `api.githubcopilot.com`, Copilot bearer injected |
| `chatgpt/<model>` | custom httpx path against the ChatGPT backend (not OpenAI-compatible) |
| anything else | LiteLLM default — API key from environment (e.g. `OPENAI_API_KEY`) |

## Configuration

Precedence per setting: **CLI flag > env var > config file > default**.

- Config file: `~/.config/x/config.toml` (`model`, `temperature`, `timeout`)
- Env vars: `X_MODEL`, `X_TEMPERATURE`, `X_TIMEOUT`
- Defaults: `gpt-4o`, temperature `0.0`, timeout `60s`

## Output discipline

Answer → stdout. Errors/diagnostics → stderr. Exit 0 on success, non-zero on
any API or config error. Safe for piping (`cat file | x "explain" | pbcopy`).

## Install

Python ≥ 3.11. Dependencies: `litellm`, `httpx` — nothing else.

```bash
pip install .        # or: pipx install .
```

## Layout

```
x/
├── cli.py            # argparse entrypoint, prompt assembly, login/logout subcommands
├── core.py           # stream_completion() / complete(); copilot+chatgpt routing
├── config.py         # flag > env > file > default resolution
└── auth/
    ├── copilot.py    # GitHub device flow → Copilot bearer + auto-refresh
    ├── chatgpt.py    # PKCE OAuth + ChatGPT backend streaming
    └── store.py      # ~/.config/x/auth.json, chmod 600
```

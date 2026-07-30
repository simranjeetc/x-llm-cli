"""x — CLI entrypoint.

Usage:
    x "question"                    one-shot, streams answer to stdout
    cat file | x "explain this"     stdin merged as context (arg first, stdin appended)
    x                               no-arg on TTY: read stdin until Ctrl-D
    x -m copilot/gpt-4o "..."       use Copilot SSO
    x --no-stream --json "..."      buffered JSON output
    x login copilot                 GitHub device flow login
    x login chatgpt                 ChatGPT PKCE login
    x login --list                  list authenticated providers
    x logout copilot                remove stored Copilot credentials
    x logout chatgpt                remove stored ChatGPT credentials

Output discipline:
    answer  → stdout
    errors  → stderr
    exit 0  on success; non-zero on any API or config error
"""

from __future__ import annotations

import argparse
import json
import sys

import litellm

# Silence litellm's own stderr chatter.
litellm.suppress_debug_info = True
litellm.set_verbose = False

from x.config import load_config
from x.core import complete, stream_completion


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _assemble_prompt(arg_prompt: str | None, stdin_text: str | None) -> str:
    parts: list[str] = []
    if arg_prompt:
        parts.append(arg_prompt)
    if stdin_text:
        parts.append(stdin_text)
    return "\n".join(parts)


def _read_stdin_if_available() -> str | None:
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return None


def _read_stdin_interactive() -> str:
    print("Enter prompt (Ctrl-D to submit):", file=sys.stderr)
    return sys.stdin.read()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x",
        description="Personal provider-agnostic LLM CLI. Streams the answer to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  x \"what is 2+2\"\n"
            "  cat notes.md | x \"explain this\"\n"
            "  x --no-stream --json \"what is 2+2\"\n"
            "  x login copilot\n"
            "  x login --list\n"
            "  x logout copilot\n"
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Question or instruction to send to the model.",
    )
    parser.add_argument(
        "-m", "--model",
        default=None,
        metavar="MODEL",
        help="Model to use for this request (overrides config default).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Sampling temperature (overrides config default).",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        dest="no_stream",
        help="Buffer the full response and print it all at once.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit a single JSON object {model, response}. Requires --no-stream.",
    )
    return parser


def _build_login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="x login")
    parser.add_argument(
        "provider",
        nargs="?",
        choices=["copilot", "chatgpt"],
        help="Provider to authenticate.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_providers",
        help="List authenticated providers.",
    )
    return parser


def _build_logout_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="x logout")
    parser.add_argument(
        "provider",
        choices=["copilot", "chatgpt"],
        help="Provider to log out of.",
    )
    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _handle_login(args: argparse.Namespace) -> None:
    if args.list_providers:
        from x.auth.store import list_providers
        providers = list_providers()
        if providers:
            for p in providers:
                print(p)
        else:
            print("(no authenticated providers)", file=sys.stderr)
        return

    if not args.provider:
        print("error: specify a provider or --list", file=sys.stderr)
        sys.exit(1)

    if args.provider == "copilot":
        from x.auth.copilot import login
        login()
    elif args.provider == "chatgpt":
        from x.auth.chatgpt import login
        login()


def _handle_logout(args: argparse.Namespace) -> None:
    if args.provider == "copilot":
        from x.auth.copilot import logout
        logout()
    elif args.provider == "chatgpt":
        from x.auth.chatgpt import logout
        logout()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Manual dispatch: route login/logout before main argparse
    argv = sys.argv[1:]
    if argv and argv[0] == "login":
        args = _build_login_parser().parse_args(argv[1:])
        _handle_login(args)
        return
    if argv and argv[0] == "logout":
        args = _build_logout_parser().parse_args(argv[1:])
        _handle_logout(args)
        return

    parser = _build_main_parser()
    args = parser.parse_args(argv)

    # --- Validation ---
    if args.json_output and not args.no_stream:
        print("error: --json requires --no-stream", file=sys.stderr)
        sys.exit(1)

    # --- Prompt assembly ---
    stdin_text = _read_stdin_if_available()

    if args.prompt is None and stdin_text is None:
        if sys.stdin.isatty():
            stdin_text = _read_stdin_interactive()

    prompt = _assemble_prompt(args.prompt, stdin_text)

    if not prompt.strip():
        print("error: no prompt provided", file=sys.stderr)
        sys.exit(1)

    # --- Config + CLI flag overrides (flag > env > config > default) ---
    cfg = load_config()
    model = args.model if args.model is not None else cfg.model
    temperature = args.temperature if args.temperature is not None else cfg.temperature
    timeout = cfg.timeout

    # --- Execute ---
    try:
        if args.no_stream:
            response = complete(prompt=prompt, model=model, temperature=temperature, timeout=timeout)
            if args.json_output:
                print(json.dumps({"model": model, "response": response}))
            else:
                print(response)
        else:
            for chunk in stream_completion(prompt=prompt, model=model, temperature=temperature, timeout=timeout):
                print(chunk, end="", flush=True)
            print()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

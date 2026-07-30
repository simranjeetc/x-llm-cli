"""x — configuration loader.

Precedence (per setting): CLI flag > env var > config file > built-in default.
This module handles the config-file and built-in-default layers.
The CLI layer (highest priority) is applied by cli.py after loading this.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Built-in defaults
_DEFAULT_MODEL = "gpt-4o"
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 60

_CONFIG_PATH = Path.home() / ".config" / "x" / "config.toml"


@dataclass
class Config:
    model: str = _DEFAULT_MODEL
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: int = _DEFAULT_TIMEOUT


def load_config() -> Config:
    """Load config from file + env vars, returning a Config with resolved values.

    Env vars override config file values; both are overridden by CLI flags
    (applied later in cli.py).
    """
    cfg = Config()

    # Layer 1: config file
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            print(f"error: config parse failed: {exc}", file=sys.stderr)
            sys.exit(1)

        if "model" in data:
            cfg.model = str(data["model"])
        if "temperature" in data:
            cfg.temperature = float(data["temperature"])
        if "timeout" in data:
            cfg.timeout = int(data["timeout"])

    # Layer 2: env vars (override config file)
    if env_model := os.environ.get("X_MODEL"):
        cfg.model = env_model
    if env_temp := os.environ.get("X_TEMPERATURE"):
        try:
            cfg.temperature = float(env_temp)
        except ValueError:
            print(
                f"error: X_TEMPERATURE env var is not a valid float: {env_temp!r}",
                file=sys.stderr,
            )
            sys.exit(1)
    if env_timeout := os.environ.get("X_TIMEOUT"):
        try:
            cfg.timeout = int(env_timeout)
        except ValueError:
            print(
                f"error: X_TIMEOUT env var is not a valid integer: {env_timeout!r}",
                file=sys.stderr,
            )
            sys.exit(1)

    return cfg

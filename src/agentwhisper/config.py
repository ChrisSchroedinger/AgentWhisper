"""Configuration: TOML file at ~/.config/agentwhisper/config.toml.

Loading is strict: unknown keys and invalid values are collected and
reported together, so a typo'd config never half-applies silently.
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "agentwhisper" / "config.toml"

# v1 is English-only, so only the English-optimized models are offered.
# Multilingual support is a designed-for future step (see DESIGN.md).
MODELS = ["tiny.en", "base.en", "small.en", "medium.en"]
MODES = ["hold", "toggle"]

DEFAULT_CONFIG_TOML = """\
# AgentWhisper configuration. Every key is optional; these are the defaults.

[whisper]
model = "base.en"        # tiny.en, base.en, small.en, medium.en
device = "cpu"           # cpu or cuda
compute_type = "int8"    # int8 for cpu, float16 for cuda

[hotkey]
key = "f12"              # f12, scroll_lock, pause, ...
mode = "hold"            # hold = push-to-talk, toggle = tap to start/stop

[output]
auto_type = true         # type the transcript into the focused window
notifications = true     # desktop notifications for state changes

[limits]
max_record_seconds = 60  # hard cap; a stuck key cannot record forever
"""


class ConfigError(Exception):
    """Raised with a message listing every problem found in the config."""


@dataclass
class Config:
    model: str = "base.en"
    device: str = "cpu"
    compute_type: str = "int8"
    hotkey: str = "f12"
    mode: str = "hold"
    auto_type: bool = True
    notifications: bool = True
    max_record_seconds: int = 60

    def validate(self) -> list[str]:
        problems = []
        if self.model not in MODELS:
            problems.append(f"whisper.model {self.model!r} is not one of {', '.join(MODELS)}")
        if self.device not in ("cpu", "cuda"):
            problems.append(f"whisper.device {self.device!r} is not 'cpu' or 'cuda'")
        if self.mode not in MODES:
            problems.append(f"hotkey.mode {self.mode!r} is not one of {', '.join(MODES)}")
        if not isinstance(self.max_record_seconds, int) or self.max_record_seconds < 1:
            problems.append("limits.max_record_seconds must be a positive integer")
        return problems


# Maps [section][key] in the TOML file to Config field names.
_SCHEMA: dict[str, dict[str, str]] = {
    "whisper": {"model": "model", "device": "device", "compute_type": "compute_type"},
    "hotkey": {"key": "hotkey", "mode": "mode"},
    "output": {"auto_type": "auto_type", "notifications": "notifications"},
    "limits": {"max_record_seconds": "max_record_seconds"},
}


def load(path: Path = CONFIG_PATH) -> Config:
    """Load and validate the config; raise ConfigError listing all problems.

    A missing file is fine (all defaults); a broken one is not.
    """
    if not path.exists():
        return Config()

    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: not valid TOML: {e}") from e

    problems: list[str] = []
    values: dict[str, object] = {}
    field_types = {f.name: f.type for f in dataclasses.fields(Config)}

    for section, entries in data.items():
        if section not in _SCHEMA:
            problems.append(f"unknown section [{section}]")
            continue
        if not isinstance(entries, dict):
            problems.append(f"[{section}] must be a section, not a value")
            continue
        for key, value in entries.items():
            field = _SCHEMA[section].get(key)
            if field is None:
                problems.append(f"unknown key {key!r} in [{section}]")
                continue
            expected = field_types[field]
            if expected == "bool" and not isinstance(value, bool):
                problems.append(f"{section}.{key} must be true or false")
                continue
            if expected == "int" and (isinstance(value, bool) or not isinstance(value, int)):
                problems.append(f"{section}.{key} must be an integer")
                continue
            if expected == "str" and not isinstance(value, str):
                problems.append(f"{section}.{key} must be a string")
                continue
            values[field] = value

    config = Config(**values)  # type: ignore[arg-type]
    problems.extend(config.validate())
    if problems:
        raise ConfigError(f"{path}:\n  - " + "\n  - ".join(problems))
    return config


def write_default(path: Path = CONFIG_PATH) -> None:
    """Write the commented default config if none exists."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TOML)


def save(config: Config, path: Path = CONFIG_PATH) -> None:
    """Persist the config (used when settings change via the tray menu).

    Rewrites the file in the default template's structure; custom
    comments in a hand-edited file are not preserved.
    """
    problems = config.validate()
    if problems:
        raise ConfigError("refusing to save invalid config:\n  - " + "\n  - ".join(problems))
    text = (
        "# AgentWhisper configuration. Managed by the app; edits are kept,\n"
        "# comments are not.\n"
        "\n[whisper]\n"
        f'model = "{config.model}"\n'
        f'device = "{config.device}"\n'
        f'compute_type = "{config.compute_type}"\n'
        "\n[hotkey]\n"
        f'key = "{config.hotkey}"\n'
        f'mode = "{config.mode}"\n'
        "\n[output]\n"
        f"auto_type = {str(config.auto_type).lower()}\n"
        f"notifications = {str(config.notifications).lower()}\n"
        "\n[limits]\n"
        f"max_record_seconds = {config.max_record_seconds}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

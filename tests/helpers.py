"""Helpers shared across the test modules."""

import tempfile
from pathlib import Path

from agentwhisper.config import Config
from agentwhisper.settings import Settings


def make_settings(values: Config | None = None) -> Settings:
    """Settings backed by a throwaway file.

    Constructing a Daemon means constructing Settings, and a test that
    changes one must not land in the developer's real config.toml.
    """
    directory = Path(tempfile.mkdtemp(prefix="agentwhisper-test-"))
    return Settings(values if values is not None else Config(),
                    directory / "config.toml")

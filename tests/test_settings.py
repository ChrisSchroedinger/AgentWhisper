"""Settings: one owner for validation, persistence and notification.

The point of every test here is the same promise — a change either
happens completely (memory, disk, subscribers) or not at all.
"""

import os

import pytest

from agentwhisper.config import Config, ConfigError, load
from agentwhisper.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(Config(), tmp_path / "config.toml")


class TestChange:
    def test_applies_and_persists(self, settings, tmp_path):
        settings.change(mode="toggle", max_record_seconds=120)
        assert settings.values.mode == "toggle"
        assert load(tmp_path / "config.toml").max_record_seconds == 120

    def test_the_written_file_keeps_its_explanations(self, settings, tmp_path):
        settings.change(model="small")
        assert "# The speech recognition model" in (tmp_path / "config.toml").read_text()

    def test_an_invalid_value_changes_nothing(self, settings, tmp_path):
        with pytest.raises(ConfigError, match="hold, toggle"):
            settings.change(mode="press")
        assert settings.values.mode == "hold"
        assert not (tmp_path / "config.toml").exists()

    def test_a_rejected_batch_does_not_apply_its_good_half(self, settings):
        """The whole config is validated with the change applied, so
        there is no window where half of it landed."""
        with pytest.raises(ConfigError):
            settings.change(model="small", mode="press")
        assert settings.values.model == "base"

    def test_unknown_setting_is_refused(self, settings):
        with pytest.raises(ConfigError, match="unknown setting"):
            settings.change(volume=11)

    def test_values_are_replaced_not_mutated(self, settings):
        """Callers hold on to `values`; a change must not rewrite the
        object under them, or a comparison against it always matches."""
        before = settings.values
        settings.change(mode="toggle")
        assert before.mode == "hold"
        assert settings.values is not before


class TestAtomicWrite:
    def test_a_failed_write_leaves_the_previous_file_intact(self, tmp_path):
        path = tmp_path / "config.toml"
        settings = Settings(Config(), path)
        settings.change(model="small")

        # Read-only directory: the temporary file cannot be created.
        os.chmod(tmp_path, 0o500)
        try:
            with pytest.raises(ConfigError, match="could not write"):
                settings.change(model="medium")
        finally:
            os.chmod(tmp_path, 0o700)

        assert settings.values.model == "small"     # memory did not move
        assert load(path).model == "small"          # nor did the file

    def test_no_temporary_files_are_left_behind(self, settings, tmp_path):
        settings.change(model="small")
        settings.change(model="medium")
        assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]

    def test_the_directory_is_created_if_missing(self, tmp_path):
        path = tmp_path / "nested" / "config.toml"
        Settings(Config(), path).change(mode="toggle")
        assert load(path).mode == "toggle"


class TestSubscribers:
    def test_called_with_the_new_values_after_a_change(self, settings):
        seen = []
        settings.subscribe(seen.append)
        settings.change(mode="toggle")
        assert [v.mode for v in seen] == ["toggle"]

    def test_not_called_when_the_change_was_refused(self, settings):
        seen = []
        settings.subscribe(seen.append)
        with pytest.raises(ConfigError):
            settings.change(mode="press")
        assert seen == []

    def test_a_subscriber_may_read_the_settings_without_deadlocking(self, settings):
        """Subscribers run outside the lock: one that calls back into
        Settings — as the daemon's does, indirectly — must not hang."""
        seen = []
        settings.subscribe(lambda _values: seen.append(settings.values.mode))
        settings.change(mode="toggle")
        assert seen == ["toggle"]

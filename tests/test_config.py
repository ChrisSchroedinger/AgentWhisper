import pytest

from agentwhisper.config import Config, ConfigError, load, write_default


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_missing_file_gives_defaults(tmp_path):
    config = load(tmp_path / "nope.toml")
    assert config == Config()


def test_valid_config_loads(tmp_path):
    p = write(tmp_path, """
[whisper]
model = "small"

[hotkey]
mode = "toggle"

[output]
auto_type = false
""")
    config = load(p)
    assert config.model == "small"
    assert config.mode == "toggle"
    assert config.auto_type is False
    assert config.notifications is True  # untouched default


@pytest.mark.parametrize("model", ["tiny", "base", "small", "medium",
                                   "large-v3", "large-v3-turbo"])
def test_general_models_are_accepted(tmp_path, model):
    p = write(tmp_path, f'[whisper]\nmodel = "{model}"\n')
    assert load(p).model == model


@pytest.mark.parametrize("old, new", [("tiny.en", "tiny"), ("base.en", "base"),
                                      ("small.en", "small"), ("medium.en", "medium")])
def test_legacy_en_models_are_normalized(tmp_path, old, new):
    """Configs from before 0.4.1 keep working: *.en → the general model."""
    p = write(tmp_path, f'[whisper]\nmodel = "{old}"\n')
    assert load(p).model == new


@pytest.mark.parametrize("seconds", [29, 601, 0])
def test_out_of_range_limit_is_rejected(tmp_path, seconds):
    p = write(tmp_path, f"[limits]\nmax_record_seconds = {seconds}\n")
    with pytest.raises(ConfigError, match="between 30 and 600"):
        load(p)


@pytest.mark.parametrize("seconds", [30, 600])
def test_limit_range_bounds_are_accepted(tmp_path, seconds):
    p = write(tmp_path, f"[limits]\nmax_record_seconds = {seconds}\n")
    assert load(p).max_record_seconds == seconds


def test_all_problems_reported_at_once(tmp_path):
    p = write(tmp_path, """
[whisper]
model = "bogus"
device = "gpu"

[hotkey]
mode = "press"

[typo_section]
x = 1
""")
    with pytest.raises(ConfigError) as exc:
        load(p)
    message = str(exc.value)
    for fragment in ("bogus", "gpu", "press", "typo_section"):
        assert fragment in message


def test_unknown_key_is_rejected(tmp_path):
    p = write(tmp_path, "[output]\nautotype = true\n")
    with pytest.raises(ConfigError, match="autotype"):
        load(p)


def test_wrong_type_is_rejected(tmp_path):
    p = write(tmp_path, '[output]\nauto_type = "yes"\n')
    with pytest.raises(ConfigError, match="auto_type"):
        load(p)


def test_invalid_toml_is_rejected(tmp_path):
    p = write(tmp_path, "not [ toml ===")
    with pytest.raises(ConfigError, match="TOML"):
        load(p)


def test_save_roundtrips(tmp_path):
    from agentwhisper.config import save

    p = tmp_path / "config.toml"
    original = Config(model="small", mode="toggle", auto_type=False,
                      max_record_seconds=90)
    save(original, p)
    assert load(p) == original


def test_save_refuses_invalid(tmp_path):
    from agentwhisper.config import save

    with pytest.raises(ConfigError):
        save(Config(mode="press"), tmp_path / "config.toml")


def test_write_default_roundtrips(tmp_path):
    p = tmp_path / "sub" / "config.toml"
    write_default(p)
    assert load(p) == Config()
    # Does not clobber an existing file.
    p.write_text("[hotkey]\nmode = \"toggle\"\n")
    write_default(p)
    assert load(p).mode == "toggle"

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
model = "small.en"

[hotkey]
mode = "toggle"

[output]
auto_type = false
""")
    config = load(p)
    assert config.model == "small.en"
    assert config.mode == "toggle"
    assert config.auto_type is False
    assert config.notifications is True  # untouched default


def test_multilingual_model_is_rejected_in_v1(tmp_path):
    """v1 is English-only; multilingual models are a future step."""
    p = write(tmp_path, '[whisper]\nmodel = "large-v3"\n')
    with pytest.raises(ConfigError, match="large-v3"):
        load(p)


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
    original = Config(model="small.en", mode="toggle", auto_type=False,
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

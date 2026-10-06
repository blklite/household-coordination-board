"""Loading and checking household.toml."""
import os

import pytest

from conftest import ROOT

from hcb import config


def load_text(tmp_path, text):
    path = tmp_path / "household.toml"
    path.write_text(text, encoding="utf-8")
    return config.load(path)


def errors_of(tmp_path, text):
    with pytest.raises(config.ConfigError) as caught:
        load_text(tmp_path, text)
    return caught.value.errors


def test_the_example_loads():
    household = config.load(ROOT / "household.example.toml")
    assert household.kid_names == ("Theo", "Maya", "Leo", "Ivy")
    assert household.children["Theo"] == {"status": "home"}
    assert household.children["Leo"] == {"status": "custody", "calendar": "Custody"}
    assert household.kitchen.practice == "eat together"
    assert household.calendars[0]["pill"] == "p-coral"


def test_a_missing_file_says_what_to_do(tmp_path):
    with pytest.raises(config.ConfigError) as caught:
        config.load(tmp_path / "household.toml")
    assert "copy household.example.toml" in caught.value.errors[0]


def test_an_address_in_the_file_is_refused(tmp_path):
    errors = errors_of(tmp_path, """
[[adults]]
name = "A"
[[calendars]]
name = "https://calendar.example.test/x.ics"
env = "HCB_X"
""")
    assert "calendars #1: name holds a web address; put addresses in the env file" in errors


def test_a_custody_calendar_must_be_required(tmp_path):
    errors = errors_of(tmp_path, """
[[adults]]
name = "A"
[[kids]]
name = "K"
custody = "r"
[custody.r]
calendar = "C"
other_parent = "B"
home = ["A"]
away = ["B"]
[[calendars]]
name = "C"
env = "HCB_C"
""")
    assert "calendar C: a custody rule reads it, so it must be required = true" in errors


def test_an_unknown_rule_and_adult_are_named(tmp_path):
    errors = errors_of(tmp_path, """
[[adults]]
name = "A"
[[kids]]
name = "K"
custody = "nope"
after_school_with = "Z"
""")
    assert "kid K: the custody rule nope is not defined" in errors
    assert "kid K: after_school_with is not an adult" in errors


def test_overlapping_bypass_rules_are_refused(tmp_path):
    errors = errors_of(tmp_path, """
[[adults]]
name = "A"
[[kids]]
name = "K"
[[bypass]]
kid = "K"
status = "off"
start = 2026-10-01
[[bypass]]
kid = "K"
status = "home"
start = 2026-10-05
end = 2026-10-06
""")
    assert "bypass: 2 rules of K overlap" in errors


def test_read_env_skips_comments_and_quotes(tmp_path):
    path = tmp_path / "household.env"
    path.write_text('# a comment\nexport HCB_A="https://x.test/a.ics"\nHCB_B=\n', encoding="utf-8")
    path.chmod(0o600)
    assert config.read_env(path) == {"HCB_A": "https://x.test/a.ics"}


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")
def test_read_env_refuses_a_file_others_can_read(tmp_path):
    path = tmp_path / "household.env"
    path.write_text("HCB_A=https://x.test/a.ics\n", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(config.ConfigError):
        config.read_env(path)


def test_describe_names_no_address():
    text = config.describe(config.load(ROOT / "household.example.toml"))
    assert "Maya: custody shared with Jordan" in text
    assert "Leo and Ivy: custody shared with Chris" in text
    assert "Theo: always home." in text
    assert "://" not in text

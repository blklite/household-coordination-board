"""The stylesheet defines every color variable that the season drawings use."""
import re
from importlib import resources

from hcb import season_art


def test_each_season_variable_is_defined():
    css = resources.files("hcb").joinpath("assets/page.css").read_text(encoding="utf-8")
    source = resources.files("hcb").joinpath("season_art.py").read_text(encoding="utf-8")
    used = set(re.findall(r"var\((--[a-z-]+)", source))
    assert used
    assert [v for v in sorted(used) if f"{v}:" not in css] == []


def test_each_theme_renders():
    import datetime as dt
    for theme in ("fall", "halloween", "thanksgiving", "christmas", "winter"):
        art = season_art.markup(theme, dt.date(2026, 10, 12),
                                [dt.date(2026, 10, 12) + dt.timedelta(days=i) for i in range(14)])
        assert art

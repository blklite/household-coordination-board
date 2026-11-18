"""Each stylesheet defines every color variable that the season drawings of its page use."""
import re
from importlib import resources

import pytest

from hcb import art, season_art

SHEETS = {"whiteboard": "page.css", "menu": "menu.css", "groceries": "groceries.css"}


@pytest.mark.parametrize("page", sorted(SHEETS))
def test_each_season_variable_is_defined(page):
    css = resources.files("hcb").joinpath(f"assets/{SHEETS[page]}").read_text(encoding="utf-8")
    used = set(re.findall(r"var\((--[a-z0-9-]+)", " ".join(art.COLORS[page].values())))
    assert used
    assert [v for v in sorted(used) if f"{v}:" not in css] == []


def test_each_theme_renders():
    import datetime as dt
    for theme in ("fall", "halloween", "thanksgiving", "christmas", "winter"):
        art = season_art.markup(theme, dt.date(2026, 10, 12),
                                [dt.date(2026, 10, 12) + dt.timedelta(days=i) for i in range(14)])
        assert art

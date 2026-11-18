"""The 3 pages: the order of the dinner plan, the diet boxes, the row of pill buttons,
the seasonal icons of the menu pages, and the faded kid chip in Dark."""
import datetime as dt
import re
from importlib import resources

import pytest
from conftest import MONDAY, NOW, STAPLES, FakeRunner, plan_for

from hcb import cli, jobs, menu_art, pages, plan_step, season, season_art, seats
from hcb import week as weekmod

HEADING = re.compile(r"^  <h3>(.*)</h3>$", re.M)
BOX = re.compile(r'^<div class="([a-z]+)">$', re.M)


def css(name):
    return resources.files("hcb").joinpath(f"assets/{name}").read_text(encoding="utf-8")


@pytest.fixture
def lines(household):
    week = weekmod.build_week([], MONDAY, weekmod.Notes(), household)
    return seats.table_lines(week, household, jobs.read_kitchen(household, MONDAY))


def plan(**changes):
    found = plan_step.validate(plan_for(MONDAY, STAPLES), plan_step.SCHEMA)
    found.update(changes)
    return found


def menu(lines, household, theme=None, **changes):
    return pages.render_menu(plan(**changes), lines, MONDAY - dt.timedelta(days=1),
                             household.kitchen.diets, theme=theme)


def groceries(lines, household, theme=None, **changes):
    return pages.render_groceries(plan(**changes), lines, MONDAY - dt.timedelta(days=1),
                                  household.kitchen.diets, theme=theme)


# --- the dinner plan: the days first, the rules and the diet box last --------------------------

def test_the_menu_has_the_days_first_and_the_rules_and_the_diet_box_last(lines, household):
    page = menu(lines, household)
    boxes = BOX.findall(page)
    assert boxes[0] == "gh"
    assert boxes.index("day") < boxes.index("sect") < boxes.index("rule") < boxes.index("gfbox")
    assert boxes[-2:] == ["rule", "gfbox"]
    assert HEADING.findall(page) == ["Practice-day snack shelf", "Assumptions",
                                     "⚑ The rules this week", "⚑ GF — Sam"]
    assert pages.guard_menu(page) == []


def test_a_menu_with_0_rules_has_no_rules_box(lines, household):
    page = menu(lines, household, week_rules=[])
    assert '<div class="rule">' not in page and pages.guard_menu(page) == []
    assert HEADING.findall(page)[-1] == "⚑ GF — Sam"


def test_the_moved_boxes_take_the_gap_above_them(lines):
    sheet = css("menu.css")
    for box in (".rule", ".gfbox"):
        rule = re.search(rf"#hh-menu-page \{box}\{{([^}}]*)\}}", sheet).group(1)
        assert "margin-top:14px" in rule and "margin-bottom" not in rule


@pytest.mark.parametrize("render", [menu, groceries])
def test_the_note_lines_keep_their_words_and_hold_no_link(lines, household, render):
    page = render(lines, household)
    note = next(line for line in page.split("\n") if line.startswith('<div class="gnote">'))
    assert "<a " not in note and "whiteboard" in note
    # The row of links still links the other 2 pages.
    assert page.count("<a href=") == 2


# --- the groceries diet box: only the swaps and the labels -------------------------------------

def test_the_groceries_diet_box_holds_only_the_swap_nights_and_the_labels(lines, household):
    page = groceries(lines, household)
    box = page[page.index('<div class="gfsect">'):]
    box = box[:box.index("</div>")]
    assert "<h3>⚑ GF — Sam</h3>" in box
    assert "<b>Swap nights:</b> Fri: swap the bun." in box
    assert "<b>Read in the store:</b> BBQ sauce." in box
    assert "Friday is the bun swap" not in page          # the model's note is on the menu only
    assert "Friday is the bun swap" in menu(lines, household)


def test_a_groceries_diet_box_with_nothing_left_is_left_out(lines, household):
    dinners = plan()["dinners"]
    for dinner in dinners:
        dinner["diet"] = {"kind": "as built", "detail": ""}
    shopping = [dict(item, read_label=False) for item in plan()["shopping"]]
    page = groceries(lines, household, dinners=dinners, shopping=shopping)
    assert '<div class="gfsect">' not in page and pages.guard_groceries(page) == []


# --- the row of pill buttons ---------------------------------------------------------------------

@pytest.mark.parametrize("sheet, wrapper", [("page.css", "#hh-whiteboard-page"),
                                            ("menu.css", "#hh-menu-page"),
                                            ("groceries.css", "#hh-groceries-page")])
def test_the_row_of_page_links_is_a_row_of_pill_buttons(sheet, wrapper):
    text = " ".join(css(sheet).split())
    pills = re.search(rf"{wrapper} \.pagelinks a,{wrapper} \.pagelinks span\{{([^}}]*)\}}",
                      text).group(1)
    assert "border-radius:999px" in pills and "border:1px solid var(--link)" in pills
    assert "text-decoration:none" in pills and "padding:3px 11px" in pills
    current = re.search(rf"\}} ?{wrapper} \.pagelinks span\{{([^}}]*)\}}", text).group(1)
    assert "font-weight:600" in current and "border-color:" in current


# --- the seasonal icons of the menu pages --------------------------------------------------------

@pytest.mark.parametrize("theme", ["fall", "halloween", "thanksgiving", "christmas", "winter"])
def test_the_menu_pages_get_the_icons_of_the_theme(lines, household, theme):
    page = menu(lines, household, theme)
    assert '<svg class="hm hm-garland" aria-hidden="true">' in page
    assert '<div class="gtitle"><svg class="hm hm-title"' in page
    days, _, _ = season_art.mix(MONDAY)
    assert page.count('  <svg class="hm hm-corner"') == len(days)
    assert pages.guard_menu(page) == []
    page = groceries(lines, household, theme)
    assert '<svg class="hg hg-garland" aria-hidden="true">' in page
    assert 1 <= page.count('  <svg class="hg hg-corner"') <= len(days)
    assert pages.guard_groceries(page) == []


def test_the_icons_use_their_own_sprite_ids_and_hold_no_text(lines, household):
    for page_name, prefix in (("menu", "hm"), ("groceries", "hg")):
        art = menu_art.markup(page_name, "fall", MONDAY)
        markup = "\n".join([*art["head"], art["title"], *art["corners"].values()])
        ids = set(re.findall(r'id="([^"]+)"', markup))
        assert ids and all(i.startswith(f"{prefix}-") for i in ids)
        assert "sn-" not in markup and "<!--" not in markup
        assert all(line.startswith(("<", "  ")) for line in markup.split("\n"))
        assert re.sub(r"<[^>]*>", "", markup.split("</style>")[1]).strip() == ""


def test_without_a_theme_the_pages_have_no_icons(lines, household):
    assert "<svg" not in menu(lines, household) and "<svg" not in groceries(lines, household)


def test_a_menu_run_writes_the_icons_of_the_monday(home, fetch):
    runner = FakeRunner(plan_for(MONDAY, STAPLES), plan_step.LAST_LINE)
    out = []
    assert cli.main(["-c", str(home / "household.toml"), "menu"], now=lambda: NOW,
                    out=out.append, fetch=fetch, runner=runner) == 0, out
    assert season.theme_of(MONDAY) == "fall"
    for name, prefix in (("menu", "hm"), ("groceries", "hg")):
        page = (home / "out" / f"{name}.html").read_text(encoding="utf-8")
        assert f'id="{prefix}-garland-fall"' in page


def test_a_page_past_the_size_limit_with_the_icons_is_written_without_them(home, fetch,
                                                                         monkeypatch):
    real = pages.render_menu

    def big(plan_, lines_, built_on, diets=(), theme=None):
        page = real(plan_, lines_, built_on, diets, theme=theme)
        return page + "<!-- -->" * 8000 if theme else page
    monkeypatch.setattr(pages, "render_menu", big)
    runner = FakeRunner(plan_for(MONDAY, STAPLES), plan_step.LAST_LINE)
    out = []
    assert cli.main(["-c", str(home / "household.toml"), "menu"], now=lambda: NOW,
                    out=out.append, fetch=fetch, runner=runner) == 0, out
    assert "hm-garland" not in (home / "out" / "menu.html").read_text(encoding="utf-8")
    assert "hg-garland" in (home / "out" / "groceries.html").read_text(encoding="utf-8")


# --- the faded kid chip in Dark ------------------------------------------------------------------

def _rules(sheet):
    """``{selector: {property: value}}`` of a style sheet (the @media block unwrapped)."""
    sheet = re.sub(r"@media[^{]*\{(.*?\})\s*\}", r"\1", sheet, flags=re.S)
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
        props = dict(part.split(":", 1) for part in (p.strip() for p in body.split(";"))
                     if ":" in part)
        for selector in selectors.split(","):
            found.setdefault(" ".join(selector.split()), {}).update(
                {k.strip(): v.strip() for k, v in props.items()})
    return found


def _rgb(color):
    return [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def _contrast(a, b):
    def lum(rgb):
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(top, under, alpha):
    return [alpha * t + (1 - alpha) * u for t, u in zip(top, under)]


W = "#hh-whiteboard-page"
DARK = ("html:not([data-theme]) #hh-whiteboard-page",
        'html[data-theme="dark"] #hh-whiteboard-page')


def _faded(variables, row, text):
    """The contrast of the text of a faded kid chip on a day row."""
    fade, under = float(variables["--away"]), _rgb(variables[row])
    return _contrast(_blend(_rgb(variables[text]), under, fade),
                     _blend(_rgb(variables["--card2"]), under, fade))


def test_a_faded_kid_chip_in_dark_is_at_least_as_readable_as_in_light():
    rules = _rules(css("page.css"))
    light = rules[W]
    for dark_rule in DARK:
        dark = {**light, **rules[dark_rule]}
        for row in ("--card", "--weekend"):              # .day and .day.weekend
            for text in ("--kid-tx", "--tx"):            # .kid and .kid b
                ratio, floor = _faded(dark, row, text), _faded(light, row, text) - 0.01
                assert ratio >= max(floor, 3), (dark_rule, row, text, round(ratio, 2))

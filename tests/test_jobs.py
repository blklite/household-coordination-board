"""End-to-end runs of the 3 commands on the example household."""
import datetime as dt
import json

from conftest import NOTES, NOW, STAPLES, URLS, FakeRunner, plan_for, MONDAY

from hcb import cli, jobs, notes_step, plan_step


def run(command, home, fetch, runner=None, extra=()):
    lines = []
    hooks = {"fetch": fetch}
    if runner is not None:
        hooks["runner"] = runner
    code = cli.main(["-c", str(home / "household.toml"), command, *extra], now=lambda: NOW,
                    out=lines.append, **hooks)
    return code, lines


def test_check_prints_each_calendar_kid_and_night(home, fetch):
    code, lines = run("check", home, fetch)
    assert code == 0, lines
    assert "calendar Maya's Schedule: ical, required, ok, 3 events" in lines
    assert any(line.startswith("calendar Leo Soccer: ical, optional, ok") for line in lines)
    assert "kid Theo: home" in lines
    assert "kid Maya: follows Maya's Schedule" in lines
    assert any(line.startswith("Practice nights: eat together") for line in lines)
    assert sum(line.startswith(("Mon ", "Tue ", "Wed ", "Thu ", "Fri ", "Sat ", "Sun "))
               for line in lines) == 7


def test_whiteboard_writes_the_page(home, fetch):
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    code, lines = run("whiteboard", home, fetch, runner)
    assert code == 0, lines
    page = (home / "out" / "whiteboard.html").read_text(encoding="utf-8")
    assert "<!doctype html>" in page
    assert "Rivera-Park Whiteboard" in page
    assert "Wednesday is the crunch" in page
    assert "Maya → <b>Jordan overnights</b> Wed–Thu" in page
    assert "Lunch: pack" not in page                       # hidden by prefix
    assert "Soccer practice" in page                       # title_replace
    for url in URLS.values():
        assert url.split("://")[1] not in page
    prompt = runner.prompts[0]
    assert "Maya: custody shared with Jordan" in prompt
    assert "cal.example.test" not in prompt


def test_whiteboard_without_notes_still_writes(home, fetch):
    runner = FakeRunner("not json", notes_step.LAST_LINE)
    code, lines = run("whiteboard", home, fetch, runner)
    assert code == 0, lines
    page = (home / "out" / "whiteboard.html").read_text(encoding="utf-8")
    assert "The notes for this week are missing." in page
    assert any("notes are missing" in line for line in lines)


def test_menu_writes_both_pages_and_saves_the_plan(home, fetch):
    runner = FakeRunner(plan_for(MONDAY, STAPLES), plan_step.LAST_LINE)
    code, lines = run("menu", home, fetch, runner)
    assert code == 0, lines
    menu = (home / "out" / "menu.html").read_text(encoding="utf-8")
    groceries = (home / "out" / "groceries.html").read_text(encoding="utf-8")
    assert "Dinner Plan" in menu and "⚑ GF — Sam" in menu
    assert "GF: swap the bun" in menu
    assert "Read in the store:</b> BBQ sauce" in groceries
    saved = json.loads((home / "state" / jobs.LAST_PLAN).read_text(encoding="utf-8"))
    assert saved["monday"] == "2026-10-12"
    assert "Sam: Gluten-free" in runner.prompts[0] or '"person": "Sam"' in runner.prompts[0]


def test_menu_fails_when_a_staple_is_missing(home, fetch):
    runner = FakeRunner(plan_for(MONDAY, STAPLES[:-1]), plan_step.LAST_LINE)
    code, lines = run("menu", home, fetch, runner)
    assert code == 1
    assert any("no list item has the staple name Coffee" in line for line in lines)
    assert not (home / "out" / "menu.html").exists()


def test_menu_without_diets_has_no_diet_box(home, fetch):
    toml = home / "household.toml"
    text = toml.read_text(encoding="utf-8")
    start = text.index("[[kitchen.diets]]")
    toml.write_text(text[:start] + text[text.index("# --- Files"):], encoding="utf-8")
    runner = FakeRunner(plan_for(MONDAY, STAPLES), plan_step.LAST_LINE)
    code, lines = run("menu", home, fetch, runner)
    assert code == 0, lines
    menu = (home / "out" / "menu.html").read_text(encoding="utf-8")
    assert '<div class="gfbox">' not in menu
    assert "swap the bun" not in menu


def test_a_required_calendar_that_fails_fails_the_run(home, fetch):
    del fetch.served[URLS["HCB_ICAL_CUSTODY"]]
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    code, lines = run("whiteboard", home, fetch, runner)
    assert code == 1
    assert any("step calendars: Custody: fetch failed (KeyError)" in line for line in lines)


def test_an_optional_calendar_that_fails_is_named(home, fetch):
    del fetch.served[URLS["HCB_ICAL_FAMILY"]]
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    code, lines = run("whiteboard", home, fetch, runner)
    assert code == 0, lines
    page = (home / "out" / "whiteboard.html").read_text(encoding="utf-8")
    assert "Not on this page: Family." in page


def test_this_week_builds_the_current_week(home, fetch):
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    wednesday = dt.datetime(2026, 10, 14, 17, 0, tzinfo=dt.timezone.utc)
    lines = []
    code = cli.main(["-c", str(home / "household.toml"), "whiteboard", "--this-week"],
                    now=lambda: wednesday, out=lines.append, fetch=fetch, runner=runner)
    assert code == 0, lines
    page = (home / "out" / "whiteboard.html").read_text(encoding="utf-8")
    assert "Mon Oct 12 – Sun Oct 18, 2026 · rebuilt Wed Oct 14" in page


def test_a_config_error_is_exit_2(home, fetch):
    (home / "household.toml").write_text('[household]\ntimezone = "Mars/Base"\n',
                                         encoding="utf-8")
    code, lines = run("check", home, fetch)
    assert code == 2
    assert "config: household: timezone is not a known zone, such as America/Chicago" in lines

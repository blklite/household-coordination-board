"""The 2 jobs and the check.

``whiteboard(household, ...)``: reads the calendars for 14 days, builds the
week, runs the notes step (1 model call; a failure leaves the notes out),
renders the page, guards it, and writes ``whiteboard.html``.

``menu(household, ...)``: reads the kitchen notes and the calendars for 7
days, computes the table line of each night, runs the plan step (1 model
call, and 1 retry with the failure texts when code rejects the reply; a
failure fails the run), renders both pages with the seasonal icons of the
week, guards them, and writes ``menu.html`` and ``groceries.html``. The plan
of a good run is saved as the last good plan and in the plan history
(``state/history/plan-<monday>.json``; the 12 newest files stay).

Each model call writes 1 line in ``state/cost.log``: a call that is followed
by a retry writes ``status=retry``. A good run whose cost line, last good
plan or history file can not be written exits 1, with the pages written.

``check(household, ...)``: reads each calendar for the coming week and
prints 1 line for each, then the rule of each kid, then the table line of
each night. It writes no page and makes no model call.

The week of a run: on a Sunday, the next Monday to Sunday. With
``this_week``, from Monday to Saturday, the week of the day of the run.

No calendar address and no credential reaches a printed line, the run
folder, a page or the model step: the addresses are read from the env file
into a dict (never into os.environ), and every calendar error carries a
fixed reason only.
"""
import datetime as dt
import json
import os
import traceback
from importlib import resources
from pathlib import Path

from . import (calendars, config, gcal, kitchen, notes_step, pages, plan_step, render, season,
               seats)
from . import week as weekmod
from .output import HtmlFolder

LAST_PLAN = "plan-last-good.json"
HISTORY = "history"             # plan-<monday>.json of each good menu run
HISTORY_WEEKS = 12              # the 12 newest files of the history stay
REPEAT_WEEKS = 1                # no dinner title of the week before


class Failed(Exception):
    """The run failed at ``step``. ``detail`` is safe to print."""

    def __init__(self, step, detail):
        super().__init__(f"{step}: {detail}")
        self.step, self.detail = step, detail


def _asset(name):
    return resources.files("hcb").joinpath(f"assets/{name}").read_text(encoding="utf-8")


def run_monday(today, this_week=False):
    """The Monday of the week that a run builds.

    The default: the Monday after ``today`` (on a Sunday, tomorrow).
    ``this_week``: the Monday of ``today``'s week from Monday to Saturday,
    and on a Sunday the next Monday.
    """
    if this_week and today.weekday() != 6:
        return today - dt.timedelta(days=today.weekday())
    return weekmod.next_monday(today)


# --- the calendars -----------------------------------------------------------------

def check_libraries(household):
    if calendars.MISSING_LIBRARY:
        raise Failed("config", f"the iCal library {calendars.MISSING_LIBRARY} is not installed "
                               "(pip install -e .)")
    if gcal.MISSING_LIBRARY and any(c["source"] == "gcal" for c in household.calendars):
        raise Failed("config", f"the signing library {gcal.MISSING_LIBRARY} is not installed "
                               '(pip install -e ".[google]")')


def sources(household, entries):
    """``(urls, account, skipped)`` for the calendar ``entries``.

    ``urls`` maps the ``env`` key of each ``ical`` calendar that can be read
    to its address (``webcal://`` read as ``https://``). ``account`` is the
    Google service account, or None. ``skipped`` lists ``(name, fixed
    reason)`` for each optional calendar that can not be read. A required
    calendar with such a fault fails the step ``config``.
    """
    check_libraries(household)
    try:
        env = config.read_env(household.env_file)
    except config.ConfigError as err:
        raise Failed("config", str(err)) from None
    urls, skipped = {}, []
    for entry in (c for c in entries if c["source"] == "ical"):
        address = env.get(entry["env"]) or os.environ.get(entry["env"])
        url = calendars.https_address(address) if address else None
        if url is None:
            reason = "no address" if not address else "the address is not https:// or webcal://"
            if calendars.required(entry):
                raise Failed("config", f"{entry['name']}: {reason} "
                                       f"(set {entry['env']} in {household.env_file.name})")
            skipped.append((entry["name"], reason))
            continue
        urls[entry["env"]] = url
    account = None
    google = [c for c in entries if c["source"] == "gcal"]
    if google:
        try:
            if household.google_key_file is None:
                raise gcal.KeyFileError("no [google] key_file in household.toml")
            account = gcal.load_account(household.google_key_file)
        except gcal.KeyFileError as err:
            if any(calendars.required(c) for c in google):
                raise Failed("config", str(err)) from None
            skipped += [(c["name"], str(err)) for c in google]
    order = [c["name"] for c in entries]
    skipped.sort(key=lambda item: order.index(item[0]))
    return urls, account, skipped


def custody_copy(household):
    """The test of the copy that ``calendars.dedupe`` keeps of an event on 2 calendars.

    True for a custody event with at least 1 label on its own calendar (a
    title on a calendar that ``household.rules_on`` names, or a tag), so that a
    custody event that is also on another calendar keeps its label, and an
    ``ignore`` title (no label) keeps the other copy and its pill. Each day of
    the event must be inside the dates of its calendar: else the copy would be
    dropped after dedupe, so the other copy is kept.
    """
    by_name = {c["name"]: c for c in household.calendars}

    def custody(event):
        calendar = by_name.get(event.calendar, {})
        return (bool(weekmod.custody_labels(event, household))
                and all(weekmod.in_dates(calendar, d) for d in event.days))
    return custody


def read_events(household, monday, days, fetch=calendars.fetch, google_fetch=None):
    """``(events, missing)`` of the calendars for ``days`` days from ``monday``.

    A calendar whose dates hold none of the days is not read. A required
    calendar that gives no valid reply fails the step ``calendars``; an
    optional one is left out and named in ``missing``.
    """
    entries = weekmod.in_window(household.calendars, monday, days)
    urls, account, skipped = sources(household, entries)
    left_out = {name for name, _ in skipped}
    google = gcal.Reader(account, google_fetch or gcal.fetch) if account else None
    missing = list(skipped)
    try:
        events = calendars.read_all([c for c in entries if c["name"] not in left_out], urls,
                                    monday, monday + dt.timedelta(days=days),
                                    fetch=fetch, google=google, missing=missing,
                                    prefer=custody_copy(household))
    except calendars.CalendarError as err:
        raise Failed("calendars", str(err)) from None
    order = [c["name"] for c in entries]
    missing.sort(key=lambda item: order.index(item[0]))
    return events, missing


def build(household, monday, days, fetch, google_fetch):
    """The ``Week`` and the notes of the run."""
    events, missing = read_events(household, monday, days, fetch, google_fetch)
    notes = weekmod.read_notes(household.notes_file, monday, household.kid_aliases())
    week = weekmod.build_week(events, monday, notes, household, missing)
    if not week.custody_found and week.follows_calendar:
        raise Failed("guard", "no custody label this week on any custody calendar")
    return week, notes


def _run_folder(household, job, when):
    return household.state_folder / "runs" / job / when.astimezone(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def _cost_line(household, job, when, result, status, out):
    """Append 1 line to ``state/cost.log``. Returns False (and prints 1 line) when it fails."""
    line = (f"{when.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} job={job} "
            f"tokens_in={result.tokens_in} tokens_out={result.tokens_out} "
            f"seconds={result.seconds:.1f} usd={result.usd:.4f} status={status}")
    try:
        household.state_folder.mkdir(parents=True, exist_ok=True)
        with open(household.state_folder / "cost.log", "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as err:
        out(f"cost.log not written ({type(err).__name__})")
        return False
    return True


def _failure(err, out):
    if isinstance(err, Failed):
        return err
    # A defect. The frames are printed, never the message: the text of an
    # exception can carry a calendar address.
    out("".join(traceback.format_tb(err.__traceback__)).rstrip())
    return Failed("internal", f"unexpected {type(err).__name__}")


# --- the whiteboard ------------------------------------------------------------------

def whiteboard(household, now, out, runner=None, fetch=calendars.fetch, google_fetch=None,
               this_week=False, writer=None):
    """1 whiteboard run. Returns the exit code: 0 a good run, 1 a failed run."""
    calendars.set_timezone(household.timezone)
    when = now()
    today = when.astimezone(calendars.TZ).date()
    writer = writer or HtmlFolder(household.output_folder)
    runner = runner or notes_step.runner_for(household, household.notes_budget)
    result = notes_step.RunResult()
    try:
        monday = run_monday(today, this_week)
        week, notes = build(household, monday, 14, fetch, google_fetch)
        prompt = notes_step.prompt_text(_asset("notes_prompt.md"), config.describe(household))
        outcome = notes_step.run_notes_step(runner, _run_folder(household, "whiteboard", when),
                                            prompt, weekmod.model_input(week, notes, today))
        result = outcome.result
        body = render.render(week, outcome.notes, today, household, rebuilt=this_week)
        if len(body.encode("utf-8")) > render.MAX_BYTES:
            body = render.render(week, outcome.notes, today, household, rebuilt=this_week,
                                 theme=None)
        problems = render.guard(body, [render.day_kids(d, household) for d in week.this_week],
                                household)
        if problems:
            raise Failed("guard", "; ".join(problems))
        path = writer.write("whiteboard", f"{household.name} Whiteboard", body)
    except Exception as err:  # noqa: BLE001 - every failure is reported the same way
        failure = _failure(err, out)
        out(f"whiteboard failed at the step {failure.step}: {failure.detail}")
        _cost_line(household, "whiteboard", when, result, f"failed:{failure.step}", out)
        return 1
    code = 0 if _cost_line(household, "whiteboard", when, result, "ok", out) else 1
    out(f"whiteboard written: {path}")
    if outcome.notes is None:
        out(f"notes are missing this week ({outcome.reason})")
    points = list(week.open_points) + [f"Flag: {f}" for f in (outcome.notes or {}).get(
        "flags", [])] + list((outcome.notes or {}).get("open_points", []))
    for point in points:
        out(f"- {weekmod.plain(point, 320)}")
    for point in week.config_points:
        out(f"- {weekmod.plain(point, 320)}")
    return code


# --- the menu -----------------------------------------------------------------------

def load_last_plan(household):
    try:
        return json.loads((household.state_folder / LAST_PLAN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(path, data):
    """``data`` as JSON at ``path``: a temporary file, then a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def save_last_plan(household, monday, plan):
    """Save the plan of a good run as the last good plan."""
    _save(household.state_folder / LAST_PLAN, {"monday": monday.isoformat(), "plan": plan})


def save_history(household, monday, plan):
    """``history/plan-<monday>.json`` of a good run; the ``HISTORY_WEEKS`` newest files stay.

    A rerun of the same week replaces its file.
    """
    folder = household.state_folder / HISTORY
    _save(folder / f"plan-{monday.isoformat()}.json", {"monday": monday.isoformat(), "plan": plan})
    for old in sorted(folder.glob("plan-*.json"))[:-HISTORY_WEEKS]:
        old.unlink()


def earlier_dinners(household, monday, saved):
    """The dinners ``{date, title}`` of the weeks before ``monday`` in the repeat window.

    Each week from its history file; the last good plan ``saved`` stands in for
    a week with no history file. A plan of ``monday`` itself is never used.
    """
    dinners = []
    for weeks in range(REPEAT_WEEKS, 0, -1):
        week = (monday - dt.timedelta(weeks=weeks)).isoformat()
        try:
            data = json.loads((household.state_folder / HISTORY / f"plan-{week}.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = saved
        try:
            if data["monday"] == week:
                dinners += [{"date": d["date"], "title": d["title"]}
                            for d in data["plan"]["dinners"]]
        except (TypeError, KeyError):
            pass
    return dinners


def retried(outcome):
    """The reason of the last call of the plan step, with ``after 1 retry`` after a retry."""
    return outcome.reason + (", after 1 retry" if outcome.first is not None else "")


def read_kitchen(household, monday):
    notes, errors = kitchen.read(household.kitchen_file, monday, household.kitchen)
    if errors:
        raise Failed("kitchen-notes", "; ".join(errors))
    return notes


def menu(household, now, out, runner=None, fetch=calendars.fetch, google_fetch=None,
         this_week=False, writer=None):
    """1 menu run. Returns the exit code: 0 a good run, 1 a failed run."""
    calendars.set_timezone(household.timezone)
    when = now()
    today = when.astimezone(calendars.TZ).date()
    writer = writer or HtmlFolder(household.output_folder)
    runner = runner or notes_step.runner_for(household, household.plan_budget)
    result = notes_step.RunResult()
    try:
        monday = run_monday(today, this_week)
        kitchen_notes = read_kitchen(household, monday)
        week, _ = build(household, monday, 7, fetch, google_fetch)
        lines = seats.table_lines(week, household, kitchen_notes)
        prompt = notes_step.prompt_text(_asset("plan_prompt.md"), config.describe(household))
        saved = load_last_plan(household)
        outcome = plan_step.run_plan_step(
            runner, _run_folder(household, "menu", when), prompt,
            plan_step.model_input(week, lines, kitchen_notes, plan_step.last_plan_input(saved),
                                  today, earlier_dinners(household, monday, saved)),
            monday, kitchen_notes.staples)
        if outcome.first is not None:       # the first call of a retried step is paid too
            _cost_line(household, "menu", when, outcome.first, "retry", out)
        result = outcome.result
        if outcome.plan is None:
            raise Failed("plan", retried(outcome))
        plan = outcome.plan
        diets = household.kitchen.diets
        # The seasonal icons of the week's Monday; a page that passes the size
        # limit with them is written without them.
        renders = {"menu": pages.render_menu, "groceries": pages.render_groceries}
        theme = season.theme_of(monday)
        bodies = {name: render_(plan, lines, today, diets, theme=theme)
                  for name, render_ in renders.items()}
        for name, render_ in renders.items():
            if len(bodies[name].encode("utf-8")) > pages.MAX_BYTES:
                bodies[name] = render_(plan, lines, today, diets)
        for name, guard in (("menu", pages.guard_menu), ("groceries", pages.guard_groceries)):
            problems = guard(bodies[name])
            if problems:
                raise Failed("guard", f"{name}: " + "; ".join(problems))
        paths = [writer.write("menu", f"{household.name} Dinner Plan", bodies["menu"]),
                 writer.write("groceries", f"{household.name} Groceries", bodies["groceries"])]
    except Exception as err:  # noqa: BLE001 - every failure is reported the same way
        failure = _failure(err, out)
        out(f"menu failed at the step {failure.step}: {failure.detail}")
        _cost_line(household, "menu", when, result, f"failed:{failure.step}", out)
        return 1
    code = 0
    try:
        save_last_plan(household, monday, plan)
    except OSError as err:
        out(f"{LAST_PLAN} not written ({type(err).__name__})")
        code = 1
    try:
        save_history(household, monday, plan)
    except OSError as err:
        out(f"{HISTORY} not written ({type(err).__name__})")
        code = 1
    if not _cost_line(household, "menu", when, result, "ok", out):
        code = 1
    for path in paths:
        out(f"written: {path}")
    for a in plan["assumptions"]:
        out(f"- assumption, {a['day']}: {weekmod.plain(a['text'], 300)}")
    for q in plan["open_questions"]:
        out(f"- question: {weekmod.plain(q['question'] + ' ' + q['why'], 300)}")
    return code


# --- the check ----------------------------------------------------------------------

def kid_line(kid, household, monday):
    """``Theo: home``, or with a part for each rule of the week."""
    parts = []
    for day in (monday + dt.timedelta(days=i) for i in range(7)):
        rule = weekmod.rule_on(kid, day, household.children, household.bypass)
        text = f"{weekmod.status_text(rule)}" + (" (bypass rule)" if "kid" in rule else "")
        if parts and parts[-1][0] == text:
            parts[-1][2] = day
        else:
            parts.append([text, day, day])
    if len(parts) == 1:
        return f"kid {kid}: {parts[0][0]}"
    return f"kid {kid}: " + "; ".join(
        f"{text} {weekmod.day_name(first)}" + (f" to {weekmod.day_name(last)}" if last != first
                                              else "")
        for text, first, last in parts)


def check(household, now, out, fetch=calendars.fetch, google_fetch=None, this_week=False):
    """Read each calendar for the coming week and print 1 line each. Returns 0 or 1."""
    calendars.set_timezone(household.timezone)
    monday = run_monday(now().astimezone(calendars.TZ).date(), this_week)
    out(f"household: {household.name}, week of {weekmod.day_name(monday)}")
    try:
        urls, account, skipped = sources(household, household.calendars)
    except Failed as err:
        out(f"config: failed, {err.detail}")
        return 1
    google = gcal.Reader(account, google_fetch or gcal.fetch) if account else None
    left_out = dict(skipped)
    code = 0
    for entry in household.calendars:
        name = entry["name"]
        need = "required" if calendars.required(entry) else "optional"
        failure = left_out.get(name)
        if failure is None:
            try:
                found = calendars.read_one(entry, urls, monday, monday + dt.timedelta(days=7),
                                           fetch=fetch, google=google)
            except calendars.CalendarError as err:
                failure = calendars.reason_for(err, name)
            except Exception as err:  # noqa: BLE001 - a defect; never its text
                failure = f"unexpected {type(err).__name__}"
        if failure is None:
            out(f"calendar {name}: {entry['source']}, {need}, ok, {len(found)} events")
            continue
        out(f"calendar {name}: {entry['source']}, {need}, failed, {failure}")
        if calendars.required(entry):
            code = 1
    for kid in household.kid_names:
        out(kid_line(kid, household, monday))
    if code:
        return code
    try:
        notes = read_kitchen(household, monday)
        week, _ = build(household, monday, 7, fetch, google_fetch)
    except Failed as err:
        out(f"{err.step}: failed, {err.detail}")
        return 1
    if notes.missing:
        out(f"kitchen notes: {household.kitchen_file.name} is missing; the menu plans from "
            "the settings alone")
    lines = seats.table_lines(week, household, notes)
    out(seats.mode_line(notes, lines))
    for line in lines:
        out(f"{weekmod.day_name(line.date)}: {line.text}")
    for point in week.open_points:
        out(f"- {weekmod.plain(point, 320)}")
    return 0


def resolve_paths(path):
    """The household file: ``path``, else ``HCB_CONFIG``, else ``household.toml``."""
    return Path(path or os.environ.get("HCB_CONFIG") or "household.toml")

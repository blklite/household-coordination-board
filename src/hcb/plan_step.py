"""The plan step: 1 model call through the runner adapter of notes_step.py.

``run_plan_step`` writes the input (``input.json``) and the prompt file (the
prompt plus the input as JSON) into the run folder, runs the runner, reads
its reply and checks it:

- against the schema: exactly the keys of ``SCHEMA`` at each level, plain
  text with length limits and no web address (as written, and as the pages
  show it, HTML entities decoded), the diet kinds and the tags of a fixed set,
  at most 5 assumptions and 5 open questions;
- by the checks of the plan: 7 dinners for the 7 dates; each list item has a
  known section and names a day of the week, ``staples`` or ``snack shelf``;
  each staple line of the kitchen notes is the staple name of a list item
  (same text, any case); a carry-over goes to a later day of the plan or the
  Monday after it.

Case and spaces are normalized before each check: a fixed value is stored in
its own spelling. Unlike the notes step of the whiteboard, a failed step is a
failed run: the caller fails at the step ``plan``.

The input holds the week (events, kid states, the dinner time and the table
line of each night), the kitchen settings and notes, the diet rules, the
dinners of the last good plan, and what that plan carries into this Monday
(``carried_in``); no calendar address, calendar ID or key.
"""
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from . import notes_step
from . import week as weekmod
from .kitchen import STAPLE_CHARS, clock

LAST_LINE = "END-OF-PLAN"
TIME_LIMIT_SECONDS = 600

DIET_KINDS = ("as built", "check", "swap")
TAGS = ("holds", "crock", "fresh", "one pan", "easy", "no cook", "reheat")
SECTIONS = ("Meat & protein", "Produce", "Pantry & dry", "Dairy & cold", "Frozen",
            "Standing notes")
USES = weekmod.WEEKDAYS + ("staples", "snack shelf")
ASSUMPTION_DAYS = weekmod.WEEKDAYS + ("week",)


def text(low, high):
    return ("text", low, high)


def enum(values):
    return ("enum", values)


def listof(spec, low, high):
    return ("list", spec, low, high)


def obj(fields):
    return ("object", fields)


BOOL = ("bool",)
LEAD_TEXT = obj({"lead": text(1, 120), "text": text(0, 400)})
SCHEMA = obj({
    "lead": text(1, 200),
    "week_rules": listof(LEAD_TEXT, 1, 5),
    "diet_note": listof(LEAD_TEXT, 0, 4),
    "dinners": listof(obj({
        "date": text(10, 10),
        "title": text(1, 90),
        "lead": text(1, 140),
        "cook": text(1, 700),
        "diet": obj({"kind": enum(DIET_KINDS), "detail": text(0, 40)}),
        "tags": listof(enum(TAGS), 1, 2),
        "carries": listof(obj({"to": text(10, 10), "what": text(1, 80)}), 0, 2),
    }), 7, 7),
    "snack_shelf": listof(obj({"item": text(1, 80), "note": text(0, 120)}), 1, 8),
    "assumptions": listof(obj({"day": enum(ASSUMPTION_DAYS), "text": text(1, 200)}), 0, 5),
    "open_questions": listof(obj({"question": text(1, 140), "why": text(0, 200)}), 0, 5),
    "shopping": listof(obj({
        "section": text(1, 30),          # its fixed set is a check of the plan
        "item": text(1, 70),
        "quantity": text(1, 40),
        "days": listof(text(1, 12), 1, 9),   # each a day, staples or snack shelf
        "note": text(0, 140),
        "staple": text(0, STAPLE_CHARS),
        "check_first": BOOL,
        "read_label": BOOL,
        "freeze": BOOL,
    }), 1, 80),
})


class PlanError(Exception):
    """The reply does not fit. ``str()`` names the place and a fixed reason, never model text."""


@dataclass
class PlanOutcome:
    plan: object            # the checked plan, or None
    reason: str             # why there is no plan; "" when there is
    result: notes_step.RunResult


def norm(value):
    """``value`` with its spaces collapsed and its case folded: the form of each comparison."""
    return " ".join(value.split()).casefold()


def _fixed(value, values):
    """The spelling in ``values`` of ``value`` (any case, any spaces), or None."""
    return next((v for v in values if norm(v) == norm(value)), None)


def validate(value, spec, path="plan"):
    """``value`` checked against ``spec`` and cleaned (spaces collapsed, fixed spellings)."""
    kind = spec[0]
    if kind == "object":
        fields = spec[1]
        if not isinstance(value, dict):
            raise PlanError(f"{path} is not an object")
        if set(value) != set(fields):
            extra, missing = set(value) - set(fields), sorted(set(fields) - set(value))
            # The extra keys are model text: only their count is named.
            raise PlanError(f"{path} has the wrong keys (missing {missing}, {len(extra)} extra)")
        return {key: validate(value[key], sub, f"{path}.{key}") for key, sub in fields.items()}
    if kind == "list":
        _, sub, low, high = spec
        if not isinstance(value, list) or not low <= len(value) <= high:
            raise PlanError(f"{path} is not a list of {low} to {high}")
        return [validate(item, sub, f"{path}[{i}]") for i, item in enumerate(value)]
    if kind == "bool":
        if not isinstance(value, bool):
            raise PlanError(f"{path} is not true or false")
        return value
    if not isinstance(value, str):
        raise PlanError(f"{path} is not text")
    clean = " ".join(value.split())
    if notes_step.holds_web_address(clean):
        raise PlanError(f"{path} holds a web address")
    if kind == "enum":
        fixed = _fixed(clean, spec[1])
        if fixed is None:
            raise PlanError(f"{path} is not one of: {', '.join(spec[1])}")
        return fixed
    _, low, high = spec
    if not low <= len(clean) <= high:
        raise PlanError(f"{path} is not {low} to {high} characters")
    return clean


def _date(value):
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def check_plan(plan, monday, staples):
    """The checks of the plan on a plan that fits the schema. Returns ``(plan, errors)``.

    The returned plan has its dinners in date order, and each section and
    day of use in its fixed spelling.
    """
    dates = [monday + dt.timedelta(days=i) for i in range(7)]
    errors = []
    if sorted(dinner["date"] for dinner in plan["dinners"]) != [d.isoformat() for d in dates]:
        errors.append(f"the 7 dinners are not 1 for each date from {dates[0]} to {dates[-1]}")
    for i, item in enumerate(plan["shopping"]):
        section = _fixed(item["section"], SECTIONS)
        if section is None:
            errors.append(f"shopping[{i}].section is not one of: {', '.join(SECTIONS)}")
        uses = [_fixed(day, USES) for day in item["days"]]
        if None in uses:
            errors.append(f"shopping[{i}].days names no day of the week, staples or snack shelf")
        item["section"], item["days"] = section or item["section"], [
            use or day for use, day in zip(uses, item["days"])]
    carried = {norm(item["staple"]) for item in plan["shopping"] if item["staple"]}
    errors += [f"no list item has the staple name {weekmod.plain(staple, 40)}"
               for staple in staples if norm(staple) not in carried]
    after = dates[-1] + dt.timedelta(days=1)
    for dinner in plan["dinners"]:
        day = _date(dinner["date"])
        for carry in dinner["carries"]:
            to = _date(carry["to"])
            if day is None or to is None or not day < to <= after:
                errors.append(f"the carry-over of {dinner['date']} does not go to a later day "
                              "of the plan or the Monday after it")
    plan["dinners"].sort(key=lambda dinner: dinner["date"])
    return plan, errors


def check(obj_, monday, staples):
    """``(plan, "")`` when the reply fits the schema and passes the checks, else ``(None, reason)``."""
    try:
        plan = validate(obj_, SCHEMA)
    except PlanError as err:
        return None, f"the reply does not fit the schema: {err}"
    plan, errors = check_plan(plan, monday, staples)
    if errors:
        more = f", and {len(errors) - 3} more" if len(errors) > 3 else ""
        return None, f"the plan failed a check: {'; '.join(errors[:3])}{more}"
    return plan, ""


# --- the input -----------------------------------------------------------------------------

def last_plan_input(saved):
    """The dinners of the last good plan for the input, or None. ``saved``: the saved file."""
    try:
        return {"monday": saved["monday"],
                "dinners": [{"date": d["date"], "title": d["title"], "carries": d["carries"]}
                            for d in saved["plan"]["dinners"]]}
    except (TypeError, KeyError):
        return None


def carried_in(last_plan, monday):
    """What the last good plan carries into ``monday``: ``[{"from", "what"}]``, [] for none."""
    try:
        return [{"from": dinner["date"], "what": carry["what"]}
                for dinner in last_plan["dinners"] for carry in dinner["carries"]
                if carry["to"] == monday.isoformat()]
    except (TypeError, KeyError):
        return []


def model_input(week, seats, kitchen, last_plan, built_on):
    """The JSON of the plan step. It holds no calendar address and no calendar ID."""
    def day_json(day, line):
        return {
            "date": day.date.isoformat(),
            "weekday": weekmod.WEEKDAYS[day.date.weekday()],
            "events": [{"time": p.time, "title": p.title, "calendar": p.event.calendar,
                        "location": p.location,
                        "description": weekmod.plain(p.event.description,
                                                     weekmod.DESCRIPTION_LIMIT)}
                       for p in day.pills],
            "custody_changes": ["".join(t) for t in day.transitions],
            "kids": {k: {"state": s.state, "label": s.label} for k, s in day.kids.items()
                     if s.state != "off"},
            # The dinner time of this night: with eat together, moved to 15 minutes
            # after the last person in dinner_waits_for comes in.
            "dinner_time": clock(line.dinner),
            "dinner_waits_for": [{"name": name, "after": end} for name, end in line.waits],
            "table": line.as_json(),
        }
    monday = week.this_week[0].date
    return {
        "built_on": built_on.isoformat(),
        "monday": monday.isoformat(),
        "monday_after": (monday + dt.timedelta(days=7)).isoformat(),
        "days": [day_json(day, line) for day, line in zip(week.this_week, seats)],
        "missing_calendars": [name for name, _ in week.missing],
        "kitchen_notes": {
            "dinner_time": clock(kitchen.dinner),
            "snack_time": clock(kitchen.snack),
            "practice_nights": kitchen.practice,
            "diets": [{"person": d.person, "rule": d.rule, "tag": d.tag}
                      for d in kitchen.diets],
            "standing_rules": kitchen.rules,
            "dinners_we_like": kitchen.dinners,
            "staples": kitchen.staples,
            "this_week": kitchen.this_week,
        },
        "last_plan": last_plan,
        "carried_in": carried_in(last_plan, monday),
    }


# --- the step ------------------------------------------------------------------------------

def run_plan_step(runner, folder, prompt, input_json, monday, staples,
                  time_limit=TIME_LIMIT_SECONDS):
    """Run the plan step in ``folder``. Never raises; ``plan`` is None after a failure."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "input.json").write_text(
            json.dumps(input_json, indent=1, ensure_ascii=False), encoding="utf-8")
        prompt_file = folder / "prompt.md"
        prompt_file.write_text(
            f"{prompt.rstrip()}\n\n<input>\n"
            f"{json.dumps(input_json, ensure_ascii=False)}\n</input>\n", encoding="utf-8")
    except OSError as err:
        return PlanOutcome(None, f"run folder not written ({type(err).__name__})",
                           notes_step.RunResult())
    try:
        result = runner.run(folder, prompt_file, time_limit)
    except Exception as err:  # noqa: BLE001 - a broken runner is a failed step, reported
        return PlanOutcome(None, f"runner failed ({type(err).__name__})", notes_step.RunResult())
    if result.error:
        return PlanOutcome(None, result.error, result)
    if result.last_line != LAST_LINE:
        return PlanOutcome(None, "the reply has no fixed last line", result)
    try:
        obj_ = notes_step.json_in((folder / "reply.txt").read_text(encoding="utf-8"), LAST_LINE)
    except (OSError, ValueError):
        return PlanOutcome(None, "the reply holds no JSON object", result)
    plan, reason = check(obj_, monday, staples)
    if plan is None:
        return PlanOutcome(None, reason, result)
    (folder / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    return PlanOutcome(plan, "", result)

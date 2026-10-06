"""The kitchen of the menu job: the settings of household.toml plus the kitchen notes file.

The settings (``[kitchen]`` in household.toml): the dinner time, the snack
time, the practice-night setting (``eat together`` or ``held plates``; see
seats.py), the latest dinner and the diet rules.

The kitchen notes file (``kitchen-notes.md`` by default) is what the model
plans from. People change it at any time; the job reads it and never writes
it. It has up to 4 sections, each with ``- `` items; only the items are read.
A section that is missing is empty.

- ``Standing rules``: the household's kitchen rules;
- ``Dinners we like``;
- ``Staples``: 1 staple for each line, which the shopping list must carry;
  the plan writes its name in a field of at most 60 characters with no web
  address, so a longer line, or 1 with a web address, is an error here;
- ``This week``: a line with ``until YYYY-MM-DD`` before the Monday of the
  run is left out.

A missing file is no error: the plan then has only the settings.
"""
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from . import week as weekmod
from .notes_step import holds_web_address

SECTIONS = ("Standing rules", "Dinners we like", "Staples", "This week")
STAPLE_CHARS = 60           # the limit of the staple name in the plan's schema (plan_step)
EAT_TOGETHER, HELD_PLATES = "eat together", "held plates"


@dataclass
class Kitchen:
    dinner: dt.time
    snack: dt.time
    practice: str                                   # EAT_TOGETHER or HELD_PLATES
    latest_dinner: dt.time = dt.time(20, 0)
    diets: tuple = ()                               # config.Diet
    rules: list = field(default_factory=list)
    dinners: list = field(default_factory=list)
    staples: list = field(default_factory=list)
    this_week: list = field(default_factory=list)
    missing: bool = False                           # no kitchen notes file


def clock(moment):
    """``6:00p``, ``4:15p``, ``11:30a``: the way the pages write a time."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}{'a' if moment.hour < 12 else 'p'}"


def items(lines):
    """The ``- `` (or ``* ``) items of a section, as 1 line each; other lines are not read."""
    found = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            text = " ".join(stripped[2:].split())
            if text:
                found.append(text)
    return found


def _kept(line, monday):
    """False for a line with ``until YYYY-MM-DD`` before ``monday``."""
    until = weekmod.UNTIL.search(line)
    if not until:
        return True
    try:
        return dt.date.fromisoformat(until.group(1)) >= monday
    except ValueError:
        return True


def staple_errors(staples):
    """1 error for each staple line that the plan can not carry.

    The error names the line by its number: its text is not echoed.
    """
    errors = []
    for number, staple in enumerate(staples, 1):
        if len(staple) > STAPLE_CHARS:
            errors.append(f"Staples line {number} is longer than {STAPLE_CHARS} characters")
        if holds_web_address(staple):
            errors.append(f"Staples line {number} holds a web address")
    return errors


def parse(text, monday, settings):
    """``(Kitchen, [])``, or ``(None, errors)`` when a staple line is not valid."""
    sections = weekmod.page_sections(text)
    staples = items(sections.get("staples", []))
    errors = staple_errors(staples)
    if errors:
        return None, errors
    return Kitchen(dinner=settings.dinner, snack=settings.snack, practice=settings.practice,
                   latest_dinner=settings.latest_dinner, diets=settings.diets,
                   rules=items(sections.get("standing rules", [])),
                   dinners=items(sections.get("dinners we like", [])),
                   staples=staples,
                   this_week=[line for line in items(sections.get("this week", []))
                              if _kept(line, monday)]), []


def read(path, monday, settings):
    """``parse`` of the file on disk; a missing file gives the settings alone."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        kitchen, _ = parse("", monday, settings)
        kitchen.missing = True
        return kitchen, []
    except (OSError, ValueError):
        return None, [f"the kitchen notes file {Path(path).name} is unreadable"]
    return parse(text, monday, settings)

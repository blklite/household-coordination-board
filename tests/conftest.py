"""Shared fixtures: the example household, synthetic calendars, and a fake model runner.

Every calendar here is made up. The tests make no network call and no model
call: ``fetch`` serves the synthetic iCal bodies, and ``FakeRunner`` writes a
canned reply.
"""
import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from hcb import config, notes_step

ROOT = Path(__file__).resolve().parent.parent
MONDAY = dt.date(2026, 10, 12)
# Sunday Oct 11, 2026, 12:00 in Chicago: the run builds the week of Mon Oct 12.
NOW = dt.datetime(2026, 10, 11, 17, 0, tzinfo=dt.timezone.utc)
URLS = {"HCB_ICAL_FAMILY": "https://cal.example.test/family.ics",
        "HCB_ICAL_ALEX": "https://cal.example.test/alex.ics",
        "HCB_ICAL_MAYA": "https://cal.example.test/maya.ics",
        "HCB_ICAL_CUSTODY": "https://cal.example.test/custody.ics",
        "HCB_ICAL_LEO_SOCCER": "webcal://cal.example.test/soccer.ics"}


def _day(offset):
    return (MONDAY + dt.timedelta(days=offset)).strftime("%Y%m%d")


def all_day(uid, title, first, days=1, description=""):
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{title}\r\nDTSTART;VALUE=DATE:{_day(first)}"
            f"\r\nDTEND;VALUE=DATE:{_day(first + days)}\r\nDESCRIPTION:{description}"
            "\r\nEND:VEVENT\r\n")


def timed(uid, title, offset, start, end, location="", description=""):
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{title}\r\n"
            f"DTSTART;TZID=America/Chicago:{_day(offset)}T{start}00\r\n"
            f"DTEND;TZID=America/Chicago:{_day(offset)}T{end}00\r\n"
            f"LOCATION:{location}\r\nDESCRIPTION:{description}\r\nEND:VEVENT\r\n")


def calendar(*events):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//hcb tests//EN\r\n"
            + "".join(events) + "END:VCALENDAR\r\n").encode("utf-8")


def bodies():
    """The iCal body of each calendar, for 14 days from MONDAY."""
    maya = []
    # Maya: Alex Mon-Tue, Jordan Wed-Thu, Alex weekend Fri-Sun; then the same the next week.
    for week in (0, 7):
        maya += [all_day(f"m{week}a", "Alex Night", week, 2),
                 all_day(f"m{week}b", "Jordan Night", week + 2, 2),
                 all_day(f"m{week}c", "Alex Weekend" if week == 0 else "Jordan Weekend",
                         week + 4, 3)]
    custody = [all_day("c1", "Sam", 0, 3), all_day("c2", "Chris", 3, 4),
               all_day("c3", "Shift Night", 1), all_day("c4", "Sam", 7, 7)]
    soccer = [timed("s1", "Leo Soccer U11 Blue practice", 1, "1700", "1900", "Field 3, Park"),
              timed("s2", "Leo Soccer U11 Blue practice", 3, "1700", "1900", "Field 3, Park"),
              timed("s3", "Leo Soccer U11 Blue game", 5, "1000", "1130", "Field 1")]
    family = [timed("f1", "Dentist: Theo", 2, "1530", "1630", "Main St Dental"),
              all_day("f2", "No school", 4),
              timed("f3", "Lunch: pack", 0, "1200", "1230")]
    alex = [timed("a1", "Work trip", 2, "1700", "2130"),
            timed("a2", "Parent meeting", 2, "1600", "1700")]
    return {URLS["HCB_ICAL_FAMILY"]: calendar(*family),
            URLS["HCB_ICAL_ALEX"]: calendar(*alex),
            URLS["HCB_ICAL_MAYA"]: calendar(*maya),
            URLS["HCB_ICAL_CUSTODY"]: calendar(*custody),
            URLS["HCB_ICAL_LEO_SOCCER"].replace("webcal://", "https://"): calendar(*soccer)}


@pytest.fixture
def fetch():
    served = bodies()

    def fake(url, *args, **kwargs):
        return served[url]
    fake.served = served
    return fake


@pytest.fixture
def home(tmp_path):
    """A folder with household.toml (the example), household.env and both notes files."""
    shutil.copy(ROOT / "household.example.toml", tmp_path / "household.toml")
    shutil.copy(ROOT / "kitchen-notes.example.md", tmp_path / "kitchen-notes.md")
    shutil.copy(ROOT / "whiteboard-notes.example.md", tmp_path / "whiteboard-notes.md")
    env = tmp_path / "household.env"
    env.write_text("".join(f"{k}={v}\n" for k, v in URLS.items()), encoding="utf-8")
    env.chmod(0o600)
    return tmp_path


@pytest.fixture
def household(home):
    return config.load(home / "household.toml")


class FakeRunner:
    """A runner that answers with ``reply`` (a dict or text) and records the prompt."""

    name = "fake"

    def __init__(self, reply, last_line):
        self.reply, self.last_line, self.prompts = reply, last_line, []

    def run(self, folder, prompt_file, time_limit):
        self.prompts.append(Path(prompt_file).read_text(encoding="utf-8"))
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        (Path(folder) / "reply.txt").write_text(f"{text}\n{self.last_line}\n", encoding="utf-8")
        return notes_step.RunResult(last_line=self.last_line, tokens_in=10, tokens_out=20,
                                    seconds=1.0, usd=0.01)


NOTES = {"standing_note": "Sam drives Tuesday and Thursday soccer; Alex has Wednesday.",
         "headline": "Wednesday is the crunch",
         "flags": ["Wed: Alex is away 5-9:30p, and Theo has the dentist at 3:30p."],
         "open_points": ["Who takes Leo to Saturday's 10:00 game?"]}


def plan_for(monday, staples):
    """A valid plan for the week of ``monday`` that carries each staple."""
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    dinners = [{"date": d.isoformat(), "title": f"Dinner {i + 1}", "lead": "A simple night.",
                "cook": "Into the oven at 5:00, out at 5:45.",
                "diet": {"kind": "swap" if i == 4 else "as built",
                         "detail": "the bun" if i == 4 else ""},
                "tags": ["easy"], "carries": []} for i, d in enumerate(days)]
    dinners[0]["carries"] = [{"to": days[1].isoformat(), "what": "Half the chicken"}]
    shopping = [{"section": "Produce", "item": "Broccoli", "quantity": "2 heads",
                 "days": ["Mon"], "note": "", "staple": "", "check_first": False,
                 "read_label": False, "freeze": False},
                {"section": "Meat & protein", "item": "Chicken thighs", "quantity": "5 lb",
                 "days": ["Mon", "Tue"], "note": "", "staple": "", "check_first": False,
                 "read_label": False, "freeze": True},
                {"section": "Pantry & dry", "item": "BBQ sauce", "quantity": "1 bottle",
                 "days": ["Sun"], "note": "", "staple": "", "check_first": True,
                 "read_label": True, "freeze": False}]
    shopping += [{"section": "Dairy & cold", "item": s, "quantity": "1", "days": ["staples"],
                  "note": "", "staple": s, "check_first": True, "read_label": False,
                  "freeze": False} for s in staples]
    return {"lead": "Monday feeds Tuesday.",
            "week_rules": [{"lead": "Tuesday and Thursday eat together late", "text": ""}],
            "diet_note": [{"lead": "Friday is the bun swap", "text": "Read the BBQ sauce."}],
            "dinners": dinners,
            "snack_shelf": [{"item": "Apples", "note": ""}],
            "assumptions": [{"day": "Wed", "text": "Alex eats on the trip."}],
            "open_questions": [],
            "shopping": shopping}


STAPLES = ["Milk (2 gal)", "Eggs (2 dozen)", "Bananas", "Bread", "Coffee"]

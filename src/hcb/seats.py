"""The table line of each night, by code.

For each night of the week, at the dinner time of the kitchen settings:

- at the table: each adult and each kid at home;
- late: a person of a timed event that covers the dinner time of that night
  (it starts before it or at it, and ends after it) and ends by the latest
  dinner time of that night. The event may have started on an earlier day of
  the week: each night is tested against every timed event of the week;
- not here: a person of such an event that ends after the latest dinner
  time, or on a later day (``Sam out until Sun 6:00p``); a kid away. A kid
  with ``after_school_with`` who is away on a school night (Monday to Friday)
  gets a snack line: that kid is home after school;
- unsure: a kid whose state is unsure, marked.

The setting ``practice_nights`` decides what a late person means:

- ``eat together``: on a night with a late person, dinner moves to 15
  minutes after the last such end, and every person who eats here is at the
  table; no plate is held. A night with no late person keeps the dinner time;
- ``held plates``: dinner stays at the dinner time, and the line names each
  late person with the end time (``Late after 7:00p: Leo``).

The kid states are those of the whiteboard code (``week.build_week``), and
the people of an event are those of the whiteboard code too
(``week.people_of``). Only the people of the household count; away wins over
late, and not here wins over late. An all-day event changes nothing: only the
model can read an all-day absence.

The model gets these lines and can not change them: the pages show them as
code made them.
"""
import datetime as dt
from dataclasses import dataclass, field

from . import calendars
from . import week as weekmod
from .kitchen import EAT_TOGETHER, clock

WAIT = dt.timedelta(minutes=15)        # eat together: dinner 15 minutes after the last end


@dataclass
class Seats:
    date: dt.date
    dinner: dt.time                                 # the dinner time of this night
    table: list = field(default_factory=list)       # names
    late: list = field(default_factory=list)        # held plates: (name, end time as "7:00p")
    snack: list = field(default_factory=list)       # (name, snack time, where after)
    away: list = field(default_factory=list)        # (name, where)
    unsure: list = field(default_factory=list)      # names
    waits: list = field(default_factory=list)       # eat together: (name, end time) to wait for

    @property
    def count(self):
        """The plates of the night: the table, the late plates and the unsure kids."""
        return len(self.table) + len(self.late) + len(self.unsure)

    def parts(self):
        """``[(kind, text)]`` of the line; kind is table, late, snack, unsure or away."""
        table = ", ".join(self.table) if self.table else "nobody"
        found = [("table", f"Table ~{clock(self.dinner)}: {table} ({len(self.table)})")]
        ends = {}
        for name, end in self.late:
            ends.setdefault(end, []).append(name)
        found += [("late", f"Late after {end}: {', '.join(names)}") for end, names in ends.items()]
        found += [("snack", f"{name}: {at} snack, {where}") for name, at, where in self.snack]
        if self.unsure:
            found.append(("unsure", f"Unsure: {', '.join(self.unsure)}"))
        places = {}
        for name, where in self.away:
            places.setdefault(where, []).append(name)
        found += [("away", f"{weekmod.join_names(names)} {where}")
                  for where, names in places.items()]
        return found

    @property
    def text(self):
        return " · ".join(text for _, text in self.parts())

    def as_json(self):
        return {"at_table": list(self.table),
                "late": [{"name": name, "after": end} for name, end in self.late],
                "snack": [{"name": name, "at": at, "then": where}
                          for name, at, where in self.snack],
                "unsure": list(self.unsure),
                "not_here": [{"name": name, "where": where} for name, where in self.away],
                "plates": self.count,
                "line": self.text}


def _where(name, state, household):
    """Where a kid that is away eats: by the override's reason, else the other parent."""
    if state.override:
        return f"away ({weekmod.plain(state.override, 40)})"
    rule = household.rule_of(name)
    return f"at {rule.other_parent}'s" if rule else "away"


def _until(end, date):
    """``out until 9:30p`` on ``date``, else with the day: ``out until Sun 6:00p``."""
    if end.date() == date:
        return f"out until {clock(end)}"
    return f"out until {weekmod.WEEKDAYS[end.weekday()]} {clock(end)}"


def held_at(date, events, household, kitchen):
    """``(late, out)``, each ``{name: end}``: the diners of a timed event that covers the
    dinner time of ``date``. Late: the event ends by the latest dinner time of that night;
    out: it ends later, or on a later day. The latest end of a kind wins."""
    config = household.week_config()
    calendars_by_name = {c["name"]: c for c in config["calendars"]}
    diners = household.adult_names + household.kid_names
    at = dt.datetime.combine(date, kitchen.dinner, tzinfo=calendars.TZ)
    limit = dt.datetime.combine(date, kitchen.latest_dinner, tzinfo=calendars.TZ)
    late, out = {}, {}
    for event in events:
        if event.all_day or not event.start <= at < event.end:
            continue
        found = out if event.end > limit else late
        for name in weekmod.people_of(event, calendars_by_name.get(event.calendar, {}), config):
            if name in diners and (name not in found or event.end > found[name]):
                found[name] = event.end
    return late, out


def seats_for(day, household, kitchen, events=None):
    """The ``Seats`` of 1 day of the week.

    ``events``: the events of the whole week (``table_lines`` gives them), so
    that an event of an earlier day marks this night too; by default the
    events of ``day`` itself.
    """
    if events is None:
        events = [pill.event for pill in day.pills]
    late, out = held_at(day.date, events, household, kitchen)
    seats = Seats(day.date, kitchen.dinner)
    diners = household.adult_names + household.kid_names
    for name in diners:
        state = day.kids.get(name)
        if state is not None and state.state == "off":
            continue
        if state is not None and state.state == "away":
            kid = household.kid(name)
            if kid.after_school_with and day.date.weekday() < 5:
                rule = household.rule_of(name)
                where = ("then " + _where(name, state, household) if state.override or not rule
                         else f"dinner at {rule.other_parent}'s")
                seats.snack.append((name, clock(kitchen.snack), where))
            else:
                seats.away.append((name, _where(name, state, household)))
        elif state is not None and state.state == "unsure":
            seats.unsure.append(name)
        elif name in out:                       # out wins over late
            seats.away.append((name, _until(out[name], day.date)))
        elif name in late:
            seats.late.append((name, late[name]))
        else:
            seats.table.append(name)
    if kitchen.practice == EAT_TOGETHER and seats.late:
        # The house waits for the last person and eats together; no plate is held.
        seats.dinner = (max(end for _, end in seats.late) + WAIT).time()
        seats.waits = [(name, clock(end)) for name, end in seats.late]
        waiting = {name for name, _ in seats.late}
        seats.table = [name for name in diners if name in seats.table or name in waiting]
        seats.late = []
    else:
        seats.late = [(name, clock(end)) for name, end in seats.late]
    return seats


def table_lines(week, household, kitchen):
    """The ``Seats`` of the 7 nights of ``week``, Monday to Sunday.

    Each night is tested against every timed event of the week.
    """
    events = [pill.event for day in week.this_week for pill in day.pills]
    return [seats_for(day, household, kitchen, events) for day in week.this_week]


def mode_line(kitchen, seats):
    """``Practice nights: eat together (dinner 6:00p; moved: Mon 7:15p, Sat 6:45p)``, or
    ``Practice nights: held plates (dinner 6:00p)``."""
    text = f"Practice nights: {kitchen.practice} (dinner {clock(kitchen.dinner)}"
    if kitchen.practice == EAT_TOGETHER:
        moved = [f"{weekmod.WEEKDAYS[s.date.weekday()]} {clock(s.dinner)}" for s in seats
                 if s.dinner != kitchen.dinner]
        text += f"; moved: {', '.join(moved) if moved else 'none'}"
    return text + ")"

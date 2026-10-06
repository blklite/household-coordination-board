"""The household week: kid states, event pills and conflict candidates.

Code decides every event, time and kid state on the page; the notes step
only writes notes. ``build_week`` turns the calendar events, the notes file
and the household configuration into a ``Week`` of 14 ``Day`` (this week,
then the next), and the open points that code found.

Kid states. Each kid with a custody rule follows the all-day events of the
rule's calendar (``household.toml``, ``[custody.<id>]``):

- A ``custody:<word>`` tag in an event description is read first, on every
  calendar: a word of ``tag_home`` is home, a word of ``tag_away`` is away.
- Else the title, on the rule's calendar only: a title of ``home`` is home, a
  title of ``away`` is away (any case, exact). A title of ``ignore`` is a
  custody event with no label: it does not change the day.
- A title that starts with ``trade_prefix`` (as written, then a word
  boundary) replaces the base label of its day. Its side comes from the words
  of ``trade_home`` and ``trade_away`` in it.
- A line of the Overrides list of the notes file replaces the state of its
  day and is an open point.
- A day with no label, or with labels that disagree, is "unsure" and is an
  open point.

A kid with no custody rule is always home. A bypass rule
(``[[bypass]]``) replaces the base rule of a kid on each day of its period,
and an Overrides line of the notes file wins over both.
"""
import datetime as dt
import html
import itertools
import re
from dataclasses import dataclass, field, replace

TAG = re.compile(r"custody:([a-z0-9_-]+)\b", re.I)
DESCRIPTION_LIMIT = 600
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --- dates and times ---------------------------------------------------------

def next_monday(today):
    """The Monday after ``today`` (a Monday gives the Monday 7 days later)."""
    return today + dt.timedelta(days=7 - today.weekday())


def day_name(day):
    """``Sat Oct 3``."""
    return f"{WEEKDAYS[day.weekday()]} {MONTHS[day.month - 1]} {day.day}"


def _clock(moment):
    hour = moment.hour % 12 or 12
    return f"{hour}" if moment.minute == 0 else f"{hour}:{moment.minute:02d}"


def _half(moment):
    return "a" if moment.hour < 12 else "p"


def time_range(start, end):
    """``5–7p``, ``5:30–7p``, ``6:30a–6:30p``; ``9a`` for an event with no length."""
    if end <= start:
        return f"{_clock(start)}{_half(start)}"
    if _half(start) == _half(end) and start.date() == end.date():
        return f"{_clock(start)}–{_clock(end)}{_half(end)}"
    return f"{_clock(start)}{_half(start)}–{_clock(end)}{_half(end)}"


def _span(days):
    first, last = WEEKDAYS[days[0].weekday()], WEEKDAYS[days[-1].weekday()]
    return first if len(days) == 1 else f"{first}–{last}"


def plain(text, limit=None):
    """Text from a calendar or a note as 1 line of plain text: tags out, spaces collapsed."""
    text = html.unescape(re.sub(r"<[^>]*>", " ", text or ""))
    text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def join_names(names):
    """``Theo``, ``Leo and Ivy``, ``Theo, Leo and Ivy``."""
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


# --- the notes file ----------------------------------------------------------

@dataclass(frozen=True)
class Override:
    day: dt.date
    kid: str
    state: str
    reason: str


@dataclass
class Notes:
    standing: str = ""
    overrides: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    missing: bool = False


HEADING = re.compile(r"^##\s+(.*?)\s*$")
UNTIL = re.compile(r"\buntil (\d{4}-\d{2}-\d{2})\b", re.I)
OVERRIDE = re.compile(
    r"^[-*]\s+(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*(home|away)\s*\|\s*(\S.*?)\s*$",
    re.I)


def page_sections(text):
    """``{heading (casefolded): [lines]}`` of the file's ``## `` sections."""
    sections, current = {}, None
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.rstrip()
        match = HEADING.match(line)
        if match:
            current = match.group(1).casefold()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def parse_notes(text, monday, kid_names):
    """The standing notes (text for the notes step) and the Overrides list.

    ``kid_names`` maps each casefolded kid name or alias to the kid. A
    standing-note line with ``until YYYY-MM-DD`` before ``monday`` is
    dropped. An Overrides line that does not parse is not applied and is an
    open point.
    """
    sections = page_sections(text)
    notes = Notes()
    kept = []
    for line in sections.get("standing notes", []):
        until = UNTIL.search(line)
        if until:
            try:
                if dt.date.fromisoformat(until.group(1)) < monday:
                    continue
            except ValueError:
                pass
        kept.append(line)
    notes.standing = "\n".join(kept).strip()
    for line in sections.get("overrides", []):
        stripped = line.strip()
        if not stripped.startswith(("- ", "* ")):
            continue
        match = OVERRIDE.match(stripped)
        kid = kid_names.get(match.group(2).strip().casefold()) if match else None
        try:
            day = dt.date.fromisoformat(match.group(1)) if match else None
        except ValueError:
            day = None
        if not (match and kid and day):
            notes.problems.append("Notes file: an Overrides line does not parse: "
                                  f"{plain(stripped, 80)}")
            continue
        notes.overrides.append(Override(day, kid, match.group(3).lower(),
                                        plain(match.group(4), 80)))
    return notes


def read_notes(path, monday, kid_names):
    """``parse_notes`` of the file on disk. A missing file is no failure: empty notes."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Notes(missing=True)
    return parse_notes(text, monday, kid_names)


# --- custody labels ----------------------------------------------------------

@dataclass(frozen=True)
class Label:
    rule: str              # the id of the custody rule
    state: object          # "home", "away", or None when a trade names no side
    trade: bool
    weekend: bool
    event: object


def _trade(title, rule):
    return bool(rule.trade_prefix) and bool(re.match(re.escape(rule.trade_prefix) + r"\b",
                                                     title))


def custody_labels(event, household):
    """The custody labels of 1 event; None when it is not a custody event.

    A tag is read on every calendar; a title only on the calendar of a rule.
    An empty list is a custody event with no label (an ``ignore`` title).
    """
    title = event.title.strip()
    folded = " ".join(title.split()).casefold()
    weekend = "weekend" in folded
    tags = [t.casefold() for t in TAG.findall(event.description or "")]
    found = []
    for word in tags:
        for rule in household.custody.values():
            state = "home" if word in rule.tag_home else "away" if word in rule.tag_away else None
            if state:
                found.append(Label(rule.id, state, _trade(title, rule), weekend, event))
    if found:
        return found
    ignored = False
    for rule in household.rules_on(event.calendar):
        if _trade(title, rule):
            words = set(re.findall(r"[a-z]+", folded))
            home, away = bool(words & set(rule.trade_home)), bool(words & set(rule.trade_away))
            state = "home" if home and not away else "away" if away and not home else None
            found.append(Label(rule.id, state, True, weekend, event))
        elif folded in rule.home:
            found.append(Label(rule.id, "home", False, weekend, event))
        elif folded in rule.away:
            found.append(Label(rule.id, "away", False, weekend, event))
        elif folded in rule.ignore:
            ignored = True
    if found:
        return found
    return [] if ignored else None


@dataclass
class KidDay:
    state: str             # "home", "away", "unsure", or "off" (not on the board)
    label: str
    why: str = ""          # for an unsure day: why
    override: str = ""     # for an override: its reason


def _unsure(why):
    return KidDay("unsure", "unsure", why=why)


def custody_day(day, kid, rule, labels):
    """The state of ``kid`` (a ``Person``) on ``day`` by the labels of its custody ``rule``."""
    today = [lab for lab in labels if lab.rule == rule.id and day in lab.event.days]
    trades = [lab for lab in today if lab.trade]
    use = trades or today
    if not use:
        return _unsure("no custody label")
    states = {lab.state for lab in use}
    if None in states:
        return _unsure("the trade event names no side")
    if len(states) != 1:
        return _unsure("custody labels disagree")
    state = states.pop()
    if trades:
        label = plain(trades[0].event.title, 30)
    else:
        label = "home" if state == "home" else rule.other_parent
        if any(lab.weekend for lab in use):
            label += " wknd"
    if state == "away" and kid.after_school_with and day.weekday() < 5:
        label += f" · PM w/ {kid.after_school_with}"
    return KidDay(state, label)


def kid_state(day, kid, base_rule, household, labels):
    """The state of 1 kid on ``day`` by its rule: ``custody``, ``home`` or ``off``."""
    if base_rule["status"] == "home":
        return KidDay("home", "home")
    if base_rule["status"] == "off":
        return KidDay("off", "off")
    return custody_day(day, household.kid(kid), household.rule_of(kid), labels)


def apply_override(kid_day, override):
    return KidDay(override.state, plain(f"{override.state} · {override.reason}", 40),
                  override=override.reason)


# --- the week ----------------------------------------------------------------

@dataclass
class Pill:
    time: str
    title: str
    location: str
    css: str
    event: object
    warn: bool = False


@dataclass
class Day:
    date: dt.date
    pills: list = field(default_factory=list)
    transitions: list = field(default_factory=list)   # (lead, bold, rest)
    kids: dict = field(default_factory=dict)


@dataclass
class Week:
    monday: dt.date
    days: list
    conflicts: list
    open_points: list
    custody_found: bool = True     # a custody label this week
    follows_calendar: bool = True  # a kid follows a custody calendar on a day of this week
    missing: list = field(default_factory=list)   # (name, fixed reason) of calendars left out
    config_points: list = field(default_factory=list)

    @property
    def this_week(self):
        return self.days[:7]

    @property
    def next_week(self):
        return self.days[7:]


def _hidden(title, config):
    folded = title.casefold()
    if folded in {t.casefold() for t in config.get("hide_titles", [])}:
        return True
    return any(folded.startswith(p.casefold()) for p in config.get("hide_title_prefixes", []))


def _rewrite(title, config):
    for old, new in config.get("title_replace", {}).items():
        title = title.replace(old, new)
    return title


def _pill(event, calendar, config):
    if event.all_day:
        last = event.end - dt.timedelta(days=1)
        when = "all day" if last == event.start else f"all day, thru {day_name(last)}"
        css = calendar.get("pill_all_day", calendar.get("pill", "p-gray"))
    else:
        when = time_range(event.start, event.end)
        css = calendar.get("pill", "p-gray")
    return Pill(when, plain(_rewrite(event.title, config), 120),
                plain(re.split(r"[,\n]", event.location, maxsplit=1)[0], 60), css, event)


def people_of(event, calendar, config):
    """The people an event is about: the calendar's people, then a name or alias in its text."""
    text = f"{event.title} {event.description} {event.location}"
    found = list(calendar.get("people", []))
    for name, aliases in config.get("people", {}).items():
        if name in found:
            continue
        if any(re.search(rf"\b{re.escape(a)}\b", text, re.I) for a in aliases):
            found.append(name)
    return found


def _transition(label, days, kids, rule):
    lead = f"{join_names(kids)} → "
    if label.trade:
        return (lead, plain(label.event.title, 40), f" {_span(days)}")
    side = "home" if label.state == "home" else rule.other_parent
    if label.weekend:
        kind = "weekend"
    else:
        kind = "overnights" if len(days) > 1 else "overnight"
    return (lead, f"{side} {kind}", f" {_span(days)}")


def _kid_points(day, kids, household):
    points = []
    for kid in household.kid_names:
        state = kids[kid]
        if state.override:
            points.append(f"{day_name(day)}: {kid} {state.state} by override "
                          f"({state.override})")
    # The kids of 1 custody rule that are unsure for the same reason make 1 point.
    groups = {}
    for kid in household.kid_names:
        if kids[kid].state == "unsure":
            groups.setdefault((household.kid(kid).custody, kids[kid].why), []).append(kid)
    for names in groups.values():
        points.append(f"{day_name(day)}: {join_names(names)} unsure ({kids[names[0]].why})")
    return points


def in_dates(calendar, day):
    """True when ``day`` is inside the dates of ``calendar`` (both included; none: no limit)."""
    start, end = calendar.get("start"), calendar.get("end")
    return (not start or start <= day.isoformat()) and (not end or day.isoformat() <= end)


def _inside_dates(events, calendars):
    """Each event only on the days inside the dates of its calendar."""
    kept = []
    for event in events:
        days = tuple(d for d in event.days if in_dates(calendars.get(event.calendar, {}), d))
        if days:
            kept.append(event if days == event.days else replace(event, days=days))
    return kept


def rule_on(kid, day, children, rules):
    """The rule of ``kid`` on ``day``: the bypass rule whose period holds the day (both
    ends included; no end date: no end), else the kid's base rule."""
    for rule in rules:
        if rule["kid"] == kid and in_dates(rule, day):
            return rule
    return children[kid]


def status_text(rule):
    """``follows Custody``, ``home`` or ``off the board``."""
    return {"home": "home", "off": "off the board"}.get(rule["status"],
                                                        f"follows {rule.get('calendar')}")


def rule_text(rule):
    """``Bypass rule: Theo off the board from Thu Oct 1 to Sun Oct 4``."""
    what = status_text(rule)
    start = day_name(dt.date.fromisoformat(rule["start"]))
    period = (f"from {start} to {day_name(dt.date.fromisoformat(rule['end']))}" if rule["end"]
              else f"from {start}, no end")
    return f"Bypass rule: {rule['kid']} {what} {period}"


def in_window(calendars, first_day, days):
    """The calendars whose dates hold at least 1 of the ``days`` days from ``first_day``."""
    window = [first_day + dt.timedelta(days=i) for i in range(days)]
    return [c for c in calendars if any(in_dates(c, day) for day in window)]


def build_week(events, monday, notes, household, missing=()):
    """The 14 days from ``monday``, with kid states, pills and open points.

    ``missing`` lists ``(name, fixed reason)`` of the optional calendars that
    could not be read; each is the first kind of open point. The
    configuration points name a calendar whose end date is in this week and
    a bypass rule that starts or ends in it.
    """
    config = household.week_config()
    calendars = {c["name"]: c for c in config["calendars"]}
    children, rules = config["children"], config["rules"]
    kids_all = household.kid_names
    dates = [monday + dt.timedelta(days=i) for i in range(14)]
    days = {d: Day(d) for d in dates}
    labels = []
    for event in _inside_dates(events, calendars):
        calendar = calendars.get(event.calendar, {})
        found = custody_labels(event, household)
        if found is not None:
            labels.extend(found)
            for label in found:
                rule = household.custody[label.rule]
                if not (rule.show_changes and event.days):
                    continue
                # The change pill: only for the kids that follow the rule that day.
                kids = [k for k in household.kids_of(rule.id)
                        if rule_on(k, event.days[0], children, rules)["status"] == "custody"]
                if kids:
                    days[event.days[0]].transitions.append(
                        _transition(label, list(event.days), kids, rule))
            continue
        if _hidden(event.title, config):
            continue
        days[event.days[0]].pills.append(_pill(event, calendar, config))

    overrides = {(o.day, o.kid): o for o in notes.overrides}
    conflicts = []
    open_points = [f"{name}: not read ({reason})" for name, reason in missing]
    this_week = {d.isoformat() for d in dates[:7]}
    config_points = [f"{c['name']}: the calendar ends on "
                     f"{day_name(dt.date.fromisoformat(c['end']))}"
                     for c in config["calendars"] if c.get("end") in this_week]
    config_points += [rule_text(r) for r in rules
                      if r["start"] in this_week or r["end"] in this_week]
    open_points += notes.problems
    for d in dates:
        day = days[d]
        # All-day events first, then timed events by start.
        day.pills.sort(key=lambda p: (0, 0.0, p.title) if p.event.all_day
                       else (1, p.event.start.timestamp(), p.title))
        day.kids = {kid: kid_state(d, kid, rule_on(kid, d, children, rules), household, labels)
                    for kid in kids_all}
        for kid in kids_all:
            if (d, kid) in overrides:
                day.kids[kid] = apply_override(day.kids[kid], overrides[(d, kid)])
        timed = [p for p in day.pills if not p.event.all_day]
        for a, b in itertools.combinations(timed, 2):
            a_end = max(a.event.end, a.event.start + dt.timedelta(minutes=1))
            b_end = max(b.event.end, b.event.start + dt.timedelta(minutes=1))
            if a.event.start < b_end and b.event.start < a_end:
                a.warn = b.warn = True
                conflicts.append({"day": d.isoformat(), "events": [
                    {"title": p.title, "time": p.time, "calendar": p.event.calendar,
                     "people": people_of(p.event, calendars.get(p.event.calendar, {}), config)}
                    for p in (a, b)]})
        open_points.extend(_kid_points(d, day.kids, household))
    custody_found = any(set(dates[:7]).intersection(label.event.days) for label in labels)
    follows_calendar = any(rule_on(kid, d, children, rules)["status"] == "custody"
                           for kid in kids_all for d in dates[:7])
    return Week(monday, [days[d] for d in dates], conflicts, open_points, custody_found,
                follows_calendar, list(missing), config_points)


def model_input(week, notes, built_on):
    """The JSON for the notes step. It holds no calendar address."""
    def day_json(day):
        return {
            "date": day.date.isoformat(),
            "weekday": WEEKDAYS[day.date.weekday()],
            "events": [{"time": p.time, "title": p.title, "calendar": p.event.calendar,
                        "location": p.location,
                        "description": plain(p.event.description, DESCRIPTION_LIMIT)}
                       for p in day.pills],
            "custody_changes": ["".join(t) for t in day.transitions],
            "kids": {k: {"state": s.state, "label": s.label} for k, s in day.kids.items()
                     if s.state != "off"},
        }
    return {
        "built_on": built_on.isoformat(),
        "this_week": [day_json(d) for d in week.this_week],
        "next_week": [day_json(d) for d in week.next_week],
        "conflict_candidates": week.conflicts,
        "open_points_from_code": week.open_points + week.config_points,
        "missing_calendars": [name for name, _ in week.missing],
        "notes_page": {
            "standing_notes": notes.standing,
            "overrides": [{"date": o.day.isoformat(), "kid": o.kid, "state": o.state,
                           "reason": o.reason} for o in notes.overrides],
        },
    }

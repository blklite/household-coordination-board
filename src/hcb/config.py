"""The household configuration: ``household.toml`` (and the env file of calendar addresses).

``load(path)`` reads and checks the file and returns a ``Household``. Every
fact about the household that the jobs use comes from here: the people, the
custody rules, the calendars, the kitchen settings, the output folder and
the model step. Nothing about a real household is in the code.

An error names the table and the entry and a fixed reason. It never quotes a
calendar ID or an address: a calendar address lives only in the env file,
and a cell that holds ``://`` is an error itself.
"""
import datetime as dt
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PILLS = ("blue", "amber", "teal", "coral", "red", "gray")
STATUSES = ("custody", "home", "off")
PRACTICE = ("eat together", "held plates")
CLOCK = re.compile(r"^(\d{1,2})(?::([0-5]\d))?\s*([ap])\.?(?:m\.?)?$", re.I)
ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*")
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
NAME_CHARS = 40


class ConfigError(Exception):
    """The configuration can not be used. ``errors`` lists each problem; each is safe to print."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def parse_clock(text):
    """The time of ``6:00p``, ``6p``, ``6:00 pm`` or ``4:15P``; None when it is not one."""
    match = CLOCK.match(str(text).strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if not 1 <= hour <= 12:
        return None
    return dt.time(hour % 12 + (12 if match.group(3).lower() == "p" else 0), minute)


@dataclass(frozen=True)
class Person:
    name: str
    color: str = ""
    aliases: tuple = ()
    custody: str = ""              # the id of the kid's custody rule; "" for always home
    after_school_with: str = ""    # an adult who has the kid after school on a weekday away night


@dataclass(frozen=True)
class CustodyRule:
    id: str
    calendar: str
    other_parent: str
    home: tuple                    # casefolded titles that put the kid home
    away: tuple                    # casefolded titles that put the kid with the other parent
    ignore: tuple = ()             # casefolded titles that are information only
    tag_home: tuple = ()           # words of a ``custody:<word>`` tag that mean home
    tag_away: tuple = ()
    trade_prefix: str = ""         # a title that starts with it replaces the day's label
    trade_home: tuple = ()         # words in a trade title that mean home
    trade_away: tuple = ()
    show_changes: bool = False     # show a custody-change pill on the whiteboard


@dataclass(frozen=True)
class Diet:
    person: str
    rule: str
    tag: str = "Diet"


@dataclass(frozen=True)
class KitchenSettings:
    dinner: dt.time
    snack: dt.time
    practice: str
    latest_dinner: dt.time
    diets: tuple = ()


@dataclass
class Household:
    name: str
    timezone: str
    adults: list
    kids: list
    custody: dict                  # rule id -> CustodyRule
    calendars: list                # dicts: name, source, env|calendar_id, required, pill, ...
    bypass: list                   # dicts: kid, start, end, status
    hide_titles: list
    hide_title_prefixes: list
    title_replace: dict
    kitchen: KitchenSettings
    output_folder: Path
    state_folder: Path
    env_file: Path
    notes_file: Path
    kitchen_file: Path
    google_key_file: object        # Path or None
    claude: str
    model: str
    notes_budget: float
    plan_budget: float
    base: Path = field(default=Path("."))

    @property
    def tz(self):
        return ZoneInfo(self.timezone)

    @property
    def kid_names(self):
        return tuple(kid.name for kid in self.kids)

    @property
    def adult_names(self):
        return tuple(adult.name for adult in self.adults)

    def kid(self, name):
        return next(kid for kid in self.kids if kid.name == name)

    def kid_index(self, name):
        return self.kid_names.index(name)

    def rule_of(self, kid_name):
        """The custody rule of a kid, or None for a kid who is always home."""
        kid = self.kid(kid_name)
        return self.custody.get(kid.custody) if kid.custody else None

    def kids_of(self, rule_id):
        return [kid.name for kid in self.kids if kid.custody == rule_id]

    def rules_on(self, calendar):
        return [rule for rule in self.custody.values() if rule.calendar == calendar]

    @property
    def children(self):
        """The base rule of each kid: follows its custody calendar, or home."""
        return {kid.name: ({"status": "custody", "calendar": self.custody[kid.custody].calendar}
                           if kid.custody else {"status": "home"}) for kid in self.kids}

    @property
    def people(self):
        """``{name: aliases}`` of each person an event can be about."""
        found = {}
        for person in [*self.adults, *self.kids]:
            found[person.name] = [person.name, *person.aliases]
        for rule in self.custody.values():
            found.setdefault(rule.other_parent, [rule.other_parent])
        return found

    def kid_aliases(self):
        """``{casefolded name or alias: kid name}``."""
        return {alias.casefold(): kid.name for kid in self.kids
                for alias in (kid.name, *kid.aliases)}

    def week_config(self):
        """The dict that ``week.build_week`` reads."""
        return {"calendars": self.calendars, "children": self.children, "rules": self.bypass,
                "hide_titles": self.hide_titles,
                "hide_title_prefixes": self.hide_title_prefixes,
                "title_replace": self.title_replace, "people": self.people}


# --- reading ----------------------------------------------------------------------------

def _words(values):
    return tuple(" ".join(str(v).split()).casefold() for v in values or ())


def _text(table, key, where, errors, required=True, limit=NAME_CHARS, default=""):
    value = table.get(key, default)
    if value in ("", None):
        if required:
            errors.append(f"{where}: {key} is missing")
        return default
    if not isinstance(value, str):
        errors.append(f"{where}: {key} is not text")
        return default
    value = " ".join(value.split())
    if "://" in value:
        errors.append(f"{where}: {key} holds a web address; put addresses in the env file")
        return default
    if limit and len(value) > limit:
        errors.append(f"{where}: {key} is longer than {limit} characters")
        return default
    return value


def _date(value, where, key, errors):
    if value in ("", None):
        return None
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        errors.append(f"{where}: {key} is not a date (YYYY-MM-DD)")
        return None


def _person(table, where, errors):
    name = _text(table, "name", where, errors)
    color = table.get("color", "")
    if color and not COLOR.fullmatch(str(color)):
        errors.append(f"{where}: color is not a color like #60a5fa")
        color = ""
    aliases = tuple(_text({"a": a}, "a", f"{where} aliases", errors)
                    for a in table.get("aliases", []))
    return Person(name=name, color=color, aliases=tuple(a for a in aliases if a),
                  custody=_text(table, "custody", where, errors, required=False),
                  after_school_with=_text(table, "after_school_with", where, errors,
                                          required=False))


def _calendar(table, number, errors):
    where = f"calendars #{number}"
    name = _text(table, "name", where, errors, limit=60)
    where = f"calendar {name}" if name else where
    entry = {"name": name, "required": table.get("required", False) is True}
    if not isinstance(table.get("required", False), bool):
        errors.append(f"{where}: required is not true or false")
    source = table.get("source", "ical")
    if source == "ical":
        env = table.get("env", "")
        if not (isinstance(env, str) and ENV_KEY.fullmatch(env)):
            errors.append(f"{where}: env is not the name of a key, such as HCB_ICAL_FAMILY")
        entry.update(source="ical", env=env)
    elif source == "gcal":
        calendar_id = table.get("calendar_id", "")
        if not (isinstance(calendar_id, str) and calendar_id and "://" not in calendar_id):
            errors.append(f"{where}: calendar_id is missing or not valid")
        entry.update(source="gcal", calendar_id=calendar_id)
    else:
        errors.append(f"{where}: source is not ical or gcal")
    pill = table.get("pill", "gray")
    if pill not in PILLS:
        errors.append(f"{where}: pill is not 1 of {', '.join(PILLS)}")
        pill = "gray"
    entry["pill"] = f"p-{pill}"
    if "pill_all_day" in table:
        if table["pill_all_day"] not in PILLS:
            errors.append(f"{where}: pill_all_day is not 1 of {', '.join(PILLS)}")
        else:
            entry["pill_all_day"] = f"p-{table['pill_all_day']}"
    entry["people"] = [_text({"p": p}, "p", where, errors) for p in table.get("people", [])]
    entry["start"] = _date(table.get("start"), where, "start", errors)
    entry["end"] = _date(table.get("end"), where, "end", errors)
    if entry["required"] and (entry["start"] or entry["end"]):
        errors.append(f"{where}: a required calendar has dates")
    return entry


def _rule(rule_id, table, errors):
    where = f"custody.{rule_id}"
    rule = CustodyRule(
        id=rule_id,
        calendar=_text(table, "calendar", where, errors, limit=60),
        other_parent=_text(table, "other_parent", where, errors),
        home=_words(table.get("home")), away=_words(table.get("away")),
        ignore=_words(table.get("ignore")),
        tag_home=_words(table.get("tag_home")), tag_away=_words(table.get("tag_away")),
        trade_prefix=_text(table, "trade_prefix", where, errors, required=False),
        trade_home=_words(table.get("trade_home")), trade_away=_words(table.get("trade_away")),
        show_changes=table.get("show_changes", False) is True)
    if not rule.home or not rule.away:
        errors.append(f"{where}: home and away each need at least 1 title")
    if set(rule.home) & set(rule.away):
        errors.append(f"{where}: a title is both home and away")
    return rule


def _resolve(base, value, default):
    path = Path(value or default).expanduser()
    return path if path.is_absolute() else base / path


def parse(data, base=Path(".")):
    """The ``Household`` of the parsed TOML ``data``. Raises ``ConfigError``."""
    errors = []
    house = data.get("household", {})
    name = _text(house, "name", "household", errors, required=False, limit=60) or "Household"
    timezone = house.get("timezone", "America/Chicago")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        errors.append("household: timezone is not a known zone, such as America/Chicago")
        timezone = "UTC"

    adults = [_person(t, f"adults #{i}", errors) for i, t in enumerate(data.get("adults", []), 1)]
    kids = [_person(t, f"kids #{i}", errors) for i, t in enumerate(data.get("kids", []), 1)]
    if not adults:
        errors.append("adults: at least 1 adult is needed")
    names = [p.name for p in [*adults, *kids] if p.name]
    errors += [f"the name {n} occurs more than once" for n in sorted(set(names))
               if names.count(n) > 1]

    custody = {rule_id: _rule(rule_id, table, errors)
               for rule_id, table in data.get("custody", {}).items()}
    calendars = [_calendar(t, i, errors) for i, t in enumerate(data.get("calendars", []), 1)]
    by_name = {c["name"]: c for c in calendars}
    cal_names = [c["name"] for c in calendars]
    errors += [f"the calendar name {n} occurs more than once" for n in sorted(set(cal_names))
               if cal_names.count(n) > 1]
    for rule in custody.values():
        if rule.calendar and rule.calendar not in by_name:
            errors.append(f"custody.{rule.id}: the calendar {rule.calendar} is not in calendars")
        elif rule.calendar and not by_name[rule.calendar]["required"]:
            errors.append(f"calendar {rule.calendar}: a custody rule reads it, so it must be "
                          "required = true")
    for kid in kids:
        if kid.custody and kid.custody not in custody:
            errors.append(f"kid {kid.name}: the custody rule {kid.custody} is not defined")
        if kid.after_school_with and kid.after_school_with not in [a.name for a in adults]:
            errors.append(f"kid {kid.name}: after_school_with is not an adult")
        if kid.after_school_with and not kid.custody:
            errors.append(f"kid {kid.name}: after_school_with needs a custody rule")

    bypass = []
    for i, table in enumerate(data.get("bypass", []), 1):
        where = f"bypass #{i}"
        kid = _text(table, "kid", where, errors)
        status = table.get("status", "")
        if kid and kid not in [k.name for k in kids]:
            errors.append(f"{where}: kid is not 1 of the kids")
            continue
        if status not in STATUSES:
            errors.append(f"{where}: status is not custody, home or off")
            continue
        start = _date(table.get("start"), where, "start", errors)
        end = _date(table.get("end"), where, "end", errors)
        if not start:
            errors.append(f"{where}: start is missing")
            continue
        if end and end < start:
            errors.append(f"{where}: end is before start")
            continue
        rule = {"kid": kid, "start": start, "end": end, "status": status}
        if status == "custody":
            owner = next((k for k in kids if k.name == kid), None)
            if not owner or not owner.custody or owner.custody not in custody:
                errors.append(f"{where}: {kid} has no custody rule to follow")
                continue
            rule["calendar"] = custody[owner.custody].calendar
        bypass.append(rule)
    for kid in {r["kid"] for r in bypass}:
        mine = sorted((r for r in bypass if r["kid"] == kid), key=lambda r: r["start"])
        for earlier, later in zip(mine, mine[1:]):
            if earlier["end"] is None or earlier["end"] >= later["start"]:
                errors.append(f"bypass: 2 rules of {kid} overlap")

    display = data.get("display", {})
    kitchen = data.get("kitchen", {})
    times = {}
    for key, default in (("dinner_time", "6:00p"), ("snack_time", "4:15p"),
                         ("latest_dinner", "8:00p")):
        moment = parse_clock(kitchen.get(key, default))
        if moment is None:
            errors.append(f"kitchen: {key} is not a time like 6:00p")
            moment = parse_clock(default)
        times[key] = moment
    practice = " ".join(str(kitchen.get("practice_nights", "eat together")).split()).casefold()
    if practice not in PRACTICE:
        errors.append("kitchen: practice_nights is not eat together or held plates")
        practice = "eat together"
    diets = []
    for i, table in enumerate(kitchen.get("diets", []), 1):
        where = f"kitchen.diets #{i}"
        person = _text(table, "person", where, errors)
        if person and person not in names:
            errors.append(f"{where}: person is not 1 of the household")
        diets.append(Diet(person, _text(table, "rule", where, errors, limit=200),
                          _text(table, "tag", where, errors, required=False, limit=12)
                          or "Diet"))

    output = data.get("output", {})
    files = data.get("files", {})
    model = data.get("model", {})
    google = data.get("google", {})
    budgets = {}
    for key, default in (("notes_budget_usd", 0.50), ("plan_budget_usd", 1.00)):
        value = model.get(key, default)
        if not isinstance(value, (int, float)) or not 0 < value <= 20:
            errors.append(f"model: {key} is not a number from 0 to 20")
            value = default
        budgets[key] = float(value)
    if errors:
        raise ConfigError(errors)
    return Household(
        name=name, timezone=timezone, adults=adults, kids=kids, custody=custody,
        calendars=calendars, bypass=bypass,
        hide_titles=list(display.get("hide_titles", [])),
        hide_title_prefixes=list(display.get("hide_title_prefixes", [])),
        title_replace=dict(display.get("title_replace", {})),
        kitchen=KitchenSettings(times["dinner_time"], times["snack_time"], practice,
                                times["latest_dinner"], tuple(diets)),
        output_folder=_resolve(base, output.get("folder"), "out"),
        state_folder=_resolve(base, files.get("state"), "state"),
        env_file=_resolve(base, files.get("env"), "household.env"),
        notes_file=_resolve(base, files.get("whiteboard_notes"), "whiteboard-notes.md"),
        kitchen_file=_resolve(base, files.get("kitchen_notes"), "kitchen-notes.md"),
        google_key_file=(_resolve(base, google["key_file"], "") if google.get("key_file")
                         else None),
        claude=str(model.get("claude", "claude")), model=str(model.get("model",
                                                                       "claude-opus-5-5")),
        notes_budget=budgets["notes_budget_usd"], plan_budget=budgets["plan_budget_usd"],
        base=base)


def load(path):
    """The ``Household`` of the TOML file at ``path``. Raises ``ConfigError``."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{path} is missing: copy household.example.toml to it"]) from None
    except (OSError, ValueError) as err:
        raise ConfigError([f"{path.name} can not be read ({type(err).__name__})"]) from None
    return parse(data, path.resolve().parent)


def read_env(path):
    """``{KEY: value}`` of a ``KEY=value`` file; a missing file is ``{}``.

    The values are calendar addresses: they stay in this dict and never go
    into ``os.environ``, a log line or an exception. On POSIX, a file that
    group or others can read is refused.
    """
    path = Path(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return {}
    if os.name == "posix" and mode & 0o077:
        raise ConfigError([f"{path} is mode {mode:o}: run chmod 600 {path}"])
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key.startswith("export "):
            key = key[7:].strip()
        if value:
            found[key] = value
    return found


def describe(household):
    """The household as plain sentences for the model prompts. No address, no calendar ID."""
    def join(names):
        names = list(names)
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"

    lines = [f"The adults: {join(household.adult_names)}."]
    for rule in household.custody.values():
        kids = household.kids_of(rule.id)
        if kids:
            lines.append(f"{join(kids)}: custody shared with {rule.other_parent}; "
                         f"the calendar {rule.calendar} sets each day.")
    home = [kid.name for kid in household.kids if not kid.custody]
    if home:
        lines.append(f"{join(home)}: always home.")
    for kid in household.kids:
        if kid.after_school_with:
            lines.append(f"On a weekday away night, {kid.name} is with {kid.after_school_with} "
                         "after school, then goes to the other parent.")
    lines.append(f"The week runs Monday to Sunday, {household.timezone}.")
    return "\n".join(lines)

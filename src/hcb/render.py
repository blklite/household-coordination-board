"""The whiteboard page, and the guard on the page text before it is written.

``render`` gives the body of the page: the wrapper ``hh-whiteboard-page``, 7
day rows Monday to Sunday, a dot for each kid on each day, the event pills,
the next-week section and the flags. The stylesheet is ``assets/page.css``;
the dot color of each kid comes from ``household.toml`` (``kid_css``).

A kid that is ``off`` on a day has no dot on that day, and a kid that is off
on each day of the week has no legend entry. The date line of a rebuild
(``--this-week``) says ``rebuilt`` and the day. The row of links to the 3
pages (page_links.py) sits below the date line.

Every string from a calendar, the notes file or the model is collapsed to 1
line and HTML-escaped. The model's 4 fields appear only in the standing note,
the week label and the flags box. No model field reaches a day row. When
optional calendars could not be read, code adds 1 line to the standing box
that names them, so that no reader takes the page for complete.

A week with a theme (season.py, from the Monday of the week) gets seasonal
elements drawn by code (season_art.py).
"""
import html
import re
from importlib import resources

from . import page_links, season, season_art
from .week import WEEKDAYS, MONTHS, day_name, join_names, plain

WRAPPER = '<div id="hh-whiteboard-page">'
MIN_BYTES, MAX_BYTES = 3 * 1024, 60 * 1024
MISSING_NOTES = ("<b>The notes for this week are missing.</b> Nobody has checked this "
                 "week for conflicts, and the standing notes are not shown. The days below "
                 "come straight from the calendars.")
DEFAULT_COLORS = ("#a78bfa", "#f87171", "#60a5fa", "#f472b6", "#4ade80", "#f5b942",
                  "#2dd4bf", "#fb923c")


def css():
    return resources.files("hcb").joinpath("assets/page.css").read_text(encoding="utf-8")


def esc(text, limit=None):
    return html.escape(plain(text, limit), quote=True)


def dot_class(household, name):
    return f"d-k{household.kid_index(name)}"


def kid_css(household):
    """The dot rule of each kid: its color from household.toml, else a default color."""
    rules = []
    for i, kid in enumerate(household.kids):
        color = kid.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        rules.append(f"#hh-whiteboard-page .d-k{i}{{background:{color}}}")
    return "\n".join(rules)


def _short(day):
    return f"{WEEKDAYS[day.weekday()]} {MONTHS[day.month - 1]} {day.day}"


def _kid(household, name, state):
    css_class = "kid" + (" away" if state.state == "away" else "") \
        + (" unsure" if state.state == "unsure" else "")
    return (f'      <span class="{css_class}"><span class="dot {dot_class(household, name)}">'
            f"</span><b>{esc(name)}</b> {esc(state.label)}</span>")


def _pill(pill):
    text = f"{esc(pill.time)} · {esc(pill.title)}"
    if pill.location:
        text += f" — {esc(pill.location)}"
    css_class = f"pill {pill.css}" + (" warn" if pill.warn else "")
    return f'    <span class="{css_class}">{text}</span>'


def _code(text):
    """Escape a string that code made from checked parts; its spaces are kept."""
    return html.escape(text, quote=True)


def _transition(transition):
    lead, bold, rest = transition
    return (f'    <span class="pill p-blue">{_code(lead)}<b>{_code(bold)}</b>'
            f"{_code(rest)}</span>")


def day_kids(day, household):
    """The kids on the row of ``day``: each whose state is not ``off``."""
    return [name for name in household.kid_names if day.kids[name].state != "off"]


def _day_row(day, household, extra=(), mark=""):
    css_class = "day weekend" if day.date.weekday() >= 5 else "day"
    lines = [f'<div class="{css_class}">', *extra,
             f'  <div class="dcol"><div class="dname">{WEEKDAYS[day.date.weekday()]}</div>'
             f'<div class="dnum">{day.date.day}</div>{mark}</div>',
             '  <div class="dbody">']
    lines += [_pill(p) for p in day.pills]
    lines += [_transition(t) for t in day.transitions]
    if not day.pills and not day.transitions:
        lines.append('    <div class="none">Nothing scheduled</div>')
    lines.append('    <div class="kids">')
    lines += [_kid(household, name, day.kids[name]) for name in day_kids(day, household)]
    lines += ["    </div>", "  </div>", "</div>"]
    return lines


def _kid_summary(kids, household):
    """The kids of 1 coming-week row: the kids that agree make 1 text, in the legend's order.

    A kid whose custody changes show as a pill is named only when it is unsure
    or set by an override. A kid that is off is left out.
    """
    parts, groups = [], {}
    for name in household.kid_names:
        state = kids[name]
        if state.state == "off":
            continue
        rule = household.rule_of(name)
        if rule and rule.show_changes and state.state != "unsure" and not state.override:
            continue
        groups.setdefault((state.state, state.label), []).append(name)
    others = {rule.other_parent for rule in household.custody.values()}
    for (_, label), names in groups.items():
        parts.append(f"{join_names(names)} {'with ' + label if label in others else label}")
    return parts


def _next_row(day, household, mark=""):
    parts = [esc(f"{p.title} {p.time}") for p in day.pills]
    parts += [f"{_code(lead)}<b>{_code(bold)}</b>{_code(rest)}"
              for lead, bold, rest in day.transitions]
    if not day.pills:
        parts.insert(0, "Nothing scheduled")
    parts += [esc(text) for text in _kid_summary(day.kids, household)]
    label = f"{WEEKDAYS[day.date.weekday()]} {day.date.day}"
    return (f'  <div class="nrow"><div class="nd">{label}</div>'
            f'<div class="nx">{mark}{" · ".join(parts)}</div></div>')


def date_text(first, last, built_on, rebuilt=False):
    """``Mon Sep 28 – Sun Oct 4, 2026 · built Sun Sep 27 ·``: the date line up to its last part."""
    return (f"{_short(first)} – {_short(last)}, {last.year} · "
            f"{'rebuilt' if rebuilt else 'built'} {day_name(built_on)} ·")


FROM_MONDAY = "from the Monday"


def render(week, notes, built_on, household, rebuilt=False, theme=FROM_MONDAY):
    """The page body. ``notes`` is the checked model output, or None; ``rebuilt``: a rebuild.

    ``theme``: the season of the elements; by default the theme of the week's
    Monday (never of ``built_on``), None for no elements.
    """
    first, last = week.this_week[0].date, week.this_week[-1].date
    nfirst, nlast = week.next_week[0].date, week.next_week[-1].date
    art = season_art.markup(season.theme_of(first) if theme == FROM_MONDAY else theme, first,
                            [day.date for day in [*week.this_week, *week.next_week]])

    def put(slot, indent=""):
        return [indent + line for line in art.get(slot, [])]

    def mark(key, day):
        return "".join(art.get(f"{key}:{day.date.isoformat()}", []))

    if notes:
        standing = esc(notes["standing_note"])
        label = f"This week — {esc(notes['headline'])}"
        flags = notes["flags"]
    else:
        standing, label, flags = MISSING_NOTES, "This week", []
    if week.missing:
        names = ", ".join(name for name, _ in week.missing)
        standing += (f"<br><b>{esc(f'Not on this page: {names}.')}</b> "
                     "These calendars could not be read.")
    lines = [WRAPPER, "<style>", css().rstrip("\n"), kid_css(household), "</style>",
             *put("head"), "", *put("title"),
             f"<h1>{esc(household.name)} Whiteboard</h1>",
             f'<div class="sub">{date_text(first, last, built_on, rebuilt)} '
             "<em>weeks run Mon–Sun</em></div>",
             page_links.html_row("Whiteboard"), "",
             '<div class="legend">', *put("legend", "  ")]
    # A kid that is off on each day of this week has no legend entry.
    lines += [f'  <div class="lg"><span class="dot {dot_class(household, name)}"></span>'
              f"{esc(name)}</div>"
              for name in household.kid_names
              if any(name in day_kids(day, household) for day in week.this_week)]
    if household.custody:
        lines.append('  <div class="lg">Faded = other parent</div>')
    lines += ["</div>", "",
              f'<div class="standing">{standing}</div>', "",
              f'<div class="weeklabel">{label}</div>', ""]
    for i, day in enumerate(week.this_week):
        lines += _day_row(day, household, put(f"day{i}", "  "), mark("mark", day)) + [""]
    lines += ['<div class="next">', *put("next", "  "),
              f"  <h2>Coming up — {_short(nfirst)} – {_short(nlast)}</h2>"]
    lines += [_next_row(day, household, mark("nxmark", day)) for day in week.next_week]
    lines += ["</div>", ""]
    if flags:
        lines += ['<div class="flags">', "  <h2>Flags</h2>", "  <ul>"]
        lines += [f"    <li>{esc(flag)}</li>" for flag in flags]
        lines += ["  </ul>", "</div>", ""]
    lines += put("foot")
    lines.append("</div>")
    return "\n".join(lines)


DAY_ROW = re.compile(r'^<div class="day(?: weekend)?">$', re.M)
KID_SPAN = re.compile(r'<span class="kid(?: away)?(?: unsure)?"><span class="dot '
                      r'(d-k\d+)"></span>')


def guard(page, kids, household):
    """What is wrong with the page body; [] when it may be written.

    ``kids`` lists the kids of each of the 7 day rows (``day_kids``). Each kid
    of a row is on it once, and no other kid.
    """
    problems = []
    if page.count(WRAPPER) != 1:
        problems.append("the wrapper hh-whiteboard-page is not there exactly once")
    rows = list(DAY_ROW.finditer(page))
    if len(rows) != 7:
        problems.append(f"{len(rows)} day rows, not 7")
    for i, (row, expected) in enumerate(zip(rows, kids)):
        end = rows[i + 1].start() if i + 1 < len(rows) else page.find('<div class="next">',
                                                                       row.start())
        chunk = page[row.start():end if end > 0 else len(page)]
        if sorted(KID_SPAN.findall(chunk)) != sorted(dot_class(household, n) for n in expected):
            problems.append(f"day row {i + 1} does not hold the {len(expected)} kids once each")
    size = len(page.encode("utf-8"))
    if not MIN_BYTES <= size <= MAX_BYTES:
        problems.append(f"size {size} bytes is outside {MIN_BYTES // 1024}-"
                        f"{MAX_BYTES // 1024} KB")
    return problems

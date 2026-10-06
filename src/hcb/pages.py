"""The 2 pages of the menu job, and the guard on each page body before it is written.

``render_menu`` gives the body of the dinner plan (wrapper ``hh-menu-page``),
``render_groceries`` that of the grocery list (wrapper ``hh-groceries-page``):

- menu: the header with the week, the row of links, the note with the build
  date, the rules of the week, the diet box, 7 day rows (the dinner, its tags,
  how to cook it, and the table line from code), the snack shelf, the
  assumptions and the open questions;
- groceries: the header, the row of links, the note with the build date, the
  check-first box, the state of the week (carries, the put-away rule, the
  plates), the diet box, the 7 meal rows (with the plates from code), and the
  list by section.

The diet box and the diet tags appear only when household.toml has diet
rules. The style sheets are ``assets/menu.css`` and ``assets/groceries.css``.

Every string of the plan is collapsed to 1 line and HTML-escaped (``esc``).
Each assumption is marked on the menu: a tag on its day, and the section
Assumptions.
"""
import datetime as dt
import html
import re
from importlib import resources

from . import page_links, plan_step
from .render import esc
from .week import MONTHS, WEEKDAYS, day_name, join_names

MENU_WRAPPER = '<div id="hh-menu-page">'
GROCERIES_WRAPPER = '<div id="hh-groceries-page">'
MIN_BYTES, MAX_BYTES = 2 * 1024, 60 * 1024
TAG_CSS = {"holds": "t-hold", "crock": "t-hold", "fresh": "t-fresh", "one pan": "t-fresh",
           "easy": "t-easy", "no cook": "t-easy", "reheat": "t-easy"}
SEATS_CSS = {"late": "late", "snack": "early", "unsure": "unsure"}
MEAL_BUYS = 8              # the items named on a meal row of the groceries page


def _css(name):
    return resources.files("hcb").joinpath(f"assets/{name}").read_text(encoding="utf-8")


def _short(day):
    return f"{WEEKDAYS[day.weekday()]} {MONTHS[day.month - 1]} {day.day}"


def _weekday(iso):
    return WEEKDAYS[dt.date.fromisoformat(iso).weekday()]


def built_line(built_on):
    """``Built Sun Sep 27.``: how both pages say when they were built."""
    return f"Built {day_name(built_on)}."


def _sentence(text):
    """``text`` ending in a stop, so that a bold lead reads apart from the text after it."""
    return text if not text or text[-1] in ".!?:;…" else text + "."


def _lead_text(item):
    text = esc(item["text"])
    return f"<b>{esc(_sentence(item['lead']))}</b>" + (f" {text}" if text else "")


def _paragraphs(parts):
    """Indented lines, separated by a blank line."""
    return [f"  {part}" + ("<br><br>" if i < len(parts) - 1 else "")
            for i, part in enumerate(parts)]


def _list(css, title, items):
    """A boxed section with a heading and a list; [] when there is no item."""
    if not items:
        return []
    return ([f'<div class="{css}">', f"  <h3>{title}</h3>", "  <ul>"]
            + [f"    <li>{item}</li>" for item in items] + ["  </ul>", "</div>", ""])


# --- diets ---------------------------------------------------------------------------------

def diet_label(diets):
    """The short tag of the diet rules (``GF``), or ``Diet`` when they differ."""
    tags = {d.tag for d in diets}
    return tags.pop() if len(tags) == 1 else "Diet"


def diet_heading(diets):
    """``⚑ GF — Sam``: the heading of the diet box."""
    return f"⚑ {esc(diet_label(diets))} — {esc(join_names(sorted({d.person for d in diets})))}"


def diet_tag(diet, diets):
    """``(css, text)`` of the diet tag of a dinner."""
    label = esc(diet_label(diets))
    detail = esc(diet["detail"])
    if diet["kind"] == "swap":
        return "t-swap", f"{label}: swap {detail}" if detail else f"{label}: swap"
    if diet["kind"] == "check":
        return "t-gf", f"{label} — check {detail}" if detail else f"{label} — check the label"
    return "t-gf", f"{label} as built"


# --- the menu ------------------------------------------------------------------------------

def seats_html(seats):
    """The table line of code, each part escaped, the late, snack and unsure parts marked."""
    parts = []
    for kind, text in seats.parts():
        css = SEATS_CSS.get(kind)
        parts.append(f'<span class="{css}">{esc(text)}</span>' if css else esc(text))
    return " · ".join(parts)


def _day_row(dinner, seats, assumed, diets):
    date = dt.date.fromisoformat(dinner["date"])
    tags = [f'<span class="dtag {TAG_CSS[tag]}">{esc(tag)}</span>' for tag in dinner["tags"]]
    if diets:
        css, text = diet_tag(dinner["diet"], diets)
        tags.append(f'<span class="dtag {css}">{text}</span>')
    if assumed:
        tags.append('<span class="dtag t-risk">assumption</span>')
    body = f"<b>{esc(_sentence(dinner['lead']))}</b> {esc(dinner['cook'])}"
    for carry in dinner["carries"]:
        to = dt.date.fromisoformat(carry["to"])
        body += f"<br><br><b>Carries to {_short(to)}:</b> {esc(carry['what'])}"
    return ['<div class="day">',
            f'  <div class="dhead"><span class="dday">{WEEKDAYS[date.weekday()]} {date.day}</span>'
            f'<span class="dmeal">{esc(dinner["title"])}</span>{"".join(tags)}</div>',
            f'  <div class="dbody">{body}</div>',
            f'  <div class="seats">{seats_html(seats)}</div>',
            "</div>", ""]


def _assumption_day(assumption, monday):
    if assumption["day"] == "week":
        return "The week"
    return _short(monday + dt.timedelta(days=WEEKDAYS.index(assumption["day"])))


def render_menu(plan, seats, built_on, diets=()):
    """The dinner plan page. ``plan`` is the checked plan, ``seats`` the 7 table lines."""
    monday = seats[0].date
    sunday = monday + dt.timedelta(days=6)
    assumed = {a["day"] for a in plan["assumptions"]}
    lines = [MENU_WRAPPER, "<style>", _css("menu.css").rstrip("\n"), "</style>", "",
             '<div class="gh">',
             '  <div class="gtitle">Dinner Plan</div>',
             f'  <div class="gsub">{_short(monday)} – {_short(sunday)}, {sunday.year}</div>',
             "</div>",
             page_links.html_row("Dinner plan"),
             f'<div class="gnote">{built_line(built_on)} <b>{esc(_sentence(plan["lead"]))}</b> '
             "<b>Inventory is not known</b>: the "
             f'<a href="{page_links.GROCERIES_LINK}">grocery list</a> is a full shop with '
             f'check-first marks. Pairs with the <a href="{page_links.WHITEBOARD_LINK}">'
             "whiteboard</a>.</div>", "",
             '<div class="rule">', "  <h3>⚑ The rules this week</h3>"]
    lines += _paragraphs([_lead_text(item) for item in plan["week_rules"]]) + ["</div>", ""]
    if diets and plan["diet_note"]:
        lines += ['<div class="gfbox">', f"  <h3>{diet_heading(diets)}</h3>"]
        lines += _paragraphs([_lead_text(item) for item in plan["diet_note"]]) + ["</div>", ""]
    for dinner, line in zip(plan["dinners"], seats):
        lines += _day_row(dinner, line, WEEKDAYS[line.date.weekday()] in assumed, diets)
    lines += _list("sect", "Practice-day snack shelf", [
        esc(item["item"]) + (f' <span class="n">— {esc(item["note"])}</span>' if item["note"]
                             else "") for item in plan["snack_shelf"]])
    lines += _list("sect", "Assumptions", [
        f"<b>{esc(_assumption_day(a, monday))}:</b> {esc(a['text'])}"
        for a in plan["assumptions"]])
    lines += _list("sect", "Open questions", [
        f"<b>{esc(q['question'])}</b>" + (f" {esc(q['why'])}" if q["why"] else "")
        for q in plan["open_questions"]])
    lines.append("</div>")
    return "\n".join(lines)


# --- the groceries -------------------------------------------------------------------------

def uses(days):
    """``Tue, Thu``, ``staples``, ``snack shelf``: the days of use of a list item."""
    return ", ".join(days)


def _check_first(plan):
    """1 line for each section with check-first items: ``Produce: Onions (3 lb), Garlic``."""
    lines = []
    for section in plan_step.SECTIONS:
        found = [f"{esc(i['item'])} ({esc(i['quantity'])})" for i in plan["shopping"]
                 if i["check_first"] and i["section"] == section]
        if found:
            lines.append(f"<b>{esc(section)}:</b> {', '.join(found)}")
    return lines


def _state_of_week(plan, seats):
    carries = [f"{_weekday(d['date'])} → {_short(dt.date.fromisoformat(c['to']))}: "
               f"{esc(c['what'])}" for d in plan["dinners"] for c in d["carries"]]
    frozen = [f"{esc(i['item'])} ({uses(i['days'])})" for i in plan["shopping"] if i["freeze"]]
    counts = [line.count for line in seats]
    late = [WEEKDAYS[s.date.weekday()] for s in seats if s.late]
    snack = [(WEEKDAYS[s.date.weekday()], s.snack[0][1]) for s in seats if s.snack]
    who = f"Plates run {min(counts)} → {max(counts)}: " + ", ".join(
        f"{WEEKDAYS[s.date.weekday()]} {s.count}" for s in seats) + "."
    if late:
        who += f" Late plates: {', '.join(late)}."
    if snack:
        who += f" {snack[0][1]} snack: {', '.join(day for day, _ in snack)}."
    parts = [("<strong>Carries:</strong> " + "; ".join(carries) + ".") if carries
             else "<strong>Carries:</strong> no dinner carries to another night.",
             (f"<strong>Put-away rule:</strong> <b>into the freezer: {', '.join(frozen)}</b>. "
              "The rest goes in the fridge.") if frozen
             else "<strong>Put-away rule:</strong> nothing goes into the freezer this week.",
             f'<span class="who">{esc(who)}</span>']
    return ['<div class="prep">', "  <h3>⚑ State of the week</h3>"] + _paragraphs(parts) + [
        "</div>", ""]


def _diet_box(plan, diets):
    if not diets:
        return []
    swaps = [f"{_weekday(d['date'])}: "
             f"{diet_tag(d['diet'], diets)[1].removeprefix(esc(diet_label(diets)) + ': ')}"
             for d in plan["dinners"] if d["diet"]["kind"] == "swap"]
    labels = [esc(i["item"]) for i in plan["shopping"] if i["read_label"]]
    notes = [_lead_text(item) for item in plan["diet_note"]]
    items = notes[1:]
    if swaps:
        items.insert(0, f"<b>Swap nights:</b> {'; '.join(swaps)}.")
    if labels:
        items.append(f"<b>Read in the store:</b> {', '.join(labels)}.")
    first = notes[0] if notes else "; ".join(f"<b>{esc(d.person)}:</b> {esc(d.rule)}"
                                             for d in diets)
    lines = ['<div class="gfsect">', f"  <h3>{diet_heading(diets)}</h3>", f"  {first}"]
    if items:
        lines += ["  <ul>"] + [f"    <li>{item}</li>" for item in items] + ["  </ul>"]
    return lines + ["</div>", ""]


def _meal_row(dinner, seats, plan):
    day = _weekday(dinner["date"])
    carried = [f"From {_weekday(d['date'])}: {esc(c['what'])}." for d in plan["dinners"]
               for c in d["carries"] if c["to"] == dinner["date"]]
    buys = [esc(i["item"]) for i in plan["shopping"] if day in i["days"]]
    who = " ".join(carried)
    if buys:
        more = f", and {len(buys) - MEAL_BUYS} more" if len(buys) > MEAL_BUYS else ""
        who += (" " if who else "") + f"Buys: {', '.join(buys[:MEAL_BUYS])}{more}."
    elif not carried:
        who = "Nothing to buy."
    return (f'  <div class="mrow"><span class="d">{day}</span><span class="seats">{seats.count}'
            f'</span><span>{esc(dinner["title"])}. <span class="who">{who}</span></span></div>')


def _item(item):
    note = [uses(item["days"])] + ([esc(item["note"])] if item["note"] else [])
    note += [mark for flag, mark in (("check_first", "<b>Check first</b>"),
                                     ("read_label", "Read the label"),
                                     ("freeze", "Freeze at put-away")) if item[flag]]
    return (f"<b>{esc(item['item'])}</b> — {esc(item['quantity'])} "
            f'<span class="n">{" · ".join(note)}</span>')


def render_groceries(plan, seats, built_on, diets=()):
    """The grocery list page. ``plan`` is the checked plan, ``seats`` the 7 table lines."""
    monday = seats[0].date
    sunday = monday + dt.timedelta(days=6)
    lines = [GROCERIES_WRAPPER, "<style>", _css("groceries.css").rstrip("\n"), "</style>", "",
             '<div class="gh">',
             '  <div class="gtitle">Groceries</div>',
             f'  <div class="gsub">For {_short(monday)} – {_short(sunday)}, {sunday.year}</div>',
             "</div>",
             page_links.html_row("Groceries"),
             f'<div class="gnote">{built_line(built_on)} <strong>Shopping list, not an '
             "inventory board.</strong> Every line is written as a buy, and the ones that may "
             "already be in the freezer or pantry are marked <b>check first</b>. Tied to "
             f'<a href="{page_links.MENU_LINK}">this week\'s dinner plan</a>. Schedule and kid '
             f'placement on the <a href="{page_links.WHITEBOARD_LINK}">household whiteboard</a>.'
             "</div>", ""]
    lines += _list("checkfirst", "⚑ Check before you leave", _check_first(plan))
    lines += _state_of_week(plan, seats)
    lines += _diet_box(plan, diets)
    lines += ['<div class="meals">', "  <h3>Meal Plan — and what it draws on</h3>"]
    lines += [_meal_row(dinner, line, plan) for dinner, line in zip(plan["dinners"], seats)]
    lines += ["</div>", ""]
    for section in plan_step.SECTIONS:
        lines += _list("sect", html.escape(section),
                       [_item(i) for i in plan["shopping"] if i["section"] == section])
    lines.append("</div>")
    return "\n".join(lines)


# --- the guard -----------------------------------------------------------------------------

SECTION = re.compile(r'^<div class="(rule|gfbox|sect|checkfirst|prep|gfsect|meals)">$')
DAY_ROW = re.compile(r'^<div class="day">$', re.M)
SEATS_LINE = re.compile(r'^  <div class="seats">', re.M)
MEAL_ROW = re.compile(r'^  <div class="mrow">', re.M)
TAG = re.compile(r"<[^>]*>")


def empty_sections(page):
    """The class of each section whose body holds no text besides its heading."""
    empty, current, texts = [], None, []
    for line in page.split("\n"):
        match = SECTION.match(line)
        if match:
            current, texts = match.group(1), []
        elif current and line == "</div>":
            if not any(texts):
                empty.append(current)
            current = None
        elif current and not line.strip().startswith("<h3>"):
            texts.append(TAG.sub("", line).strip())
    return empty


def _common(page, wrapper):
    problems = []
    if page.count(wrapper) != 1:
        problems.append(f"the wrapper {wrapper[9:-2]} is not there exactly once")
    size = len(page.encode("utf-8"))
    if not MIN_BYTES <= size <= MAX_BYTES:
        problems.append(f"size {size} bytes is outside {MIN_BYTES // 1024}-"
                        f"{MAX_BYTES // 1024} KB")
    problems += [f"the section {css} is empty" for css in empty_sections(page)]
    return problems


def guard_menu(page):
    """What is wrong with the body of the dinner plan; [] when it may be written."""
    problems = _common(page, MENU_WRAPPER)
    rows = list(DAY_ROW.finditer(page))
    if len(rows) != 7:
        problems.append(f"{len(rows)} day rows, not 7")
    for i, row in enumerate(rows):
        end = rows[i + 1].start() if i + 1 < len(rows) else len(page)
        if len(SEATS_LINE.findall(page[row.start():end])) != 1:
            problems.append(f"day row {i + 1} does not hold 1 table line")
    return problems


def guard_groceries(page):
    """What is wrong with the body of the grocery list; [] when it may be written."""
    problems = _common(page, GROCERIES_WRAPPER)
    rows = len(MEAL_ROW.findall(page))
    if rows != 7:
        problems.append(f"{rows} meal rows, not 7")
    return problems

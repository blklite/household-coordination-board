"""The seasonal elements of the whiteboard page: the drawings and the look.

``markup(theme, monday, days)`` gives the season markup of a page: a dict
from a slot of the page (``head``, ``title``, ``legend``, ``day0`` to
``day6``, ``next``, ``foot``) to the new lines that render.py puts there,
and from ``mark:<date>`` to the inline mark of a holiday. Only the lines
that hold a mark change; the existing elements of those lines keep their
bytes.

The look ("always A, mix up B and C"): a
garland hung along the top edge of the board and an element by the title,
in each week with a theme; below it a mix of elements on the top right
corner of 3 or 4 day cards and 2 or 3 round stickers in the gaps between
the sections, and 4 larger stickers in the margins on a wide screen only.
A hash of the Monday picks the mix, so each week looks a little different
and each run of the same week gives the same page.

Each element is drawn by code: it is 1 ``<symbol>`` of 1 hidden sprite
``<svg>`` and is placed with ``<use>``. Each shape sets its own color
inside the symbol (``style="fill:..."``), from the variables of page.css or
a mix of 2 of them (Q78), so the drawings follow light and dark; a page
rule does not reach a ``<use>`` copy. The sprite holds only the symbols
that the page uses. Size and position go on the outer ``<svg>``, which has
``pointer-events:none`` and ``aria-hidden="true"``.

No text from a calendar, the notes page or the model reaches this module:
the markup is a function of the theme and the dates alone.

Each line starts with ``<`` or 2 spaces, and none holds ``<!--`` (the rules
of the write gate; see render.py).
"""
import hashlib
import re

from . import season

# The inks. A mix of 2 page variables gives the colors page.css lacks
# (pumpkin orange, bark brown, leaf green, pine); each follows light and dark.
ORANGE = "color-mix(in srgb,var(--red),var(--amber))"
RED = "var(--red)"
GOLD = "var(--amber)"
BARK = "color-mix(in srgb,var(--amber-tx),var(--tx-faint))"
GREEN = "color-mix(in srgb,var(--teal-tx),var(--amber))"
PINE = "color-mix(in srgb,var(--teal-tx) 75%,var(--amber))"
ICE = "var(--season-ice)"
CUT = "var(--card)"
GLOW = "var(--flag-bg)"
PURPLE = "var(--season-purple)"
PINK = "var(--season-pink)"
GHOST, GHOST_LINE, GHOST_EYE = "var(--note-bg)", "var(--note-tx)", "var(--note-b)"
INKS = {"red": RED, "orange": ORANGE, "gold": GOLD, "green": GREEN, "pine": PINE,
        "ice": ICE, "purple": PURPLE}


def _fill(ink, more=""):
    return f'style="fill:{ink}{more}"'


def _line(ink, width, more=""):
    return f'style="fill:none;stroke:{ink};stroke-width:{width};stroke-linecap:round{more}"'


def _solid(ink, width=1):
    """A fill with a stroke of the same ink: the corners come out round."""
    return f'style="fill:{ink};stroke:{ink};stroke-width:{width};stroke-linejoin:round"'


def _n(value):
    return f"{round(value, 2):g}"


def _use(symbol, x, y, w, h=None, ink=None, rot=None):
    """A ``<use>`` of ``symbol`` in the box x, y, w, h; ``rot`` = (degrees, cx, cy)."""
    attrs = (f'href="#sn-{symbol}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" '
             f'height="{_n(h if h is not None else w)}"')
    if rot:
        attrs += f' transform="rotate({_n(rot[0])} {_n(rot[1])} {_n(rot[2])})"'
    if ink:
        attrs += f' style="color:{ink}"'
    return f"<use {attrs}/>"


# The drawings: name -> (viewBox, shapes). A leaf, an ornament, a bulb, a
# gift and a mitten take their color from the ``color`` of their ``<use>``
# (currentColor); every other shape has its ink.
MAPLE = ("M12 1.5l1.6 3.6 1.9-1-.6 4.4 3.2-2.8.4 2.3 3.4-.7-1.9 3.5 1.2 1.1-4.8 3.2.7 2"
         "-4.5-.9V22h-1.2v-5.8l-4.5.9.7-2-4.8-3.2 1.2-1.1-1.9-3.5 3.4.7.4-2.3 3.2 2.8-.6-4.4 1.9 1z")
STAR = ("M12 1.6 14.7 8.9 22.5 9.2 16.4 14 18.5 21.5 12 17.2 5.5 21.5 7.6 14 1.5 9.2 9.3 8.9z")
TOP_STAR = "M14 .2 15 2.8 17.8 3 15.6 4.7 16.4 7.4 14 5.9 11.6 7.4 12.4 4.7 10.2 3 13 2.8z"
FLAKE_ARM = ("M12 1.5v21M12 4.6 9.7 2.4M12 4.6l2.3-2.2M12 19.4l-2.3 2.2M12 19.4l2.3 2.2"
             "M12 8.2 9.2 5.8M12 8.2l2.8-2.4M12 15.8l-2.8 2.4M12 15.8l2.8 2.4")
SYMBOLS = {
    "pumpkin": ("0 0 32 32", [
        f'<path d="M15.2 10c-.4-2.8.4-5.3 2.4-7.1l2 1.4c-1.6 1.5-2.2 3.4-1.9 5.7z" {_fill(BARK)}/>',
        f'<ellipse cx="10.5" cy="20" rx="8.5" ry="9.5" {_fill(ORANGE)}/>',
        f'<ellipse cx="21.5" cy="20" rx="8.5" ry="9.5" {_fill(ORANGE)}/>',
        f'<ellipse cx="16" cy="20" rx="6.5" ry="10.2" {_fill(ORANGE)}/>',
        '<path d="M16 10.6c-3 2.6-3 16.2 0 18.8M16 10.6c3 2.6 3 16.2 0 18.8M9.2 12c-3.6 3.6-3.6 '
        f'12.4 0 16M22.8 12c3.6 3.6 3.6 12.4 0 16" {_line(BARK, 1.1, ";opacity:.45")}/>',
        f'<path d="M18.6 6c2.6-2.6 6.2-2.8 8.8-1.2-2 2.9-5.8 3.5-8.8 1.2z" {_fill(GREEN)}/>']),
    "jack": ("0 0 32 32", [
        '<use href="#sn-pumpkin"/>',
        '<path d="M9.6 18l2.6-3.8 2.6 3.8zM17.2 18l2.6-3.8 2.6 3.8zM8.6 21.4c3.4 5.8 11.4 5.8 '
        f'14.8 0-4.6 1.8-10.2 1.8-14.8 0z" {_fill(GLOW)}/>',
        f'<rect x="14.4" y="22.2" width="3.2" height="1.8" rx=".4" {_fill(ORANGE)}/>']),
    "maple": ("0 0 24 24", [
        f'<path d="{MAPLE}" style="fill:currentColor;stroke:currentColor;stroke-width:.8;'
        'stroke-linejoin:round"/>',
        f'<path d="M12 16.4V5.5M12 15.6l5-5.4M12 15.6l-5-5.4" {_line(CUT, .9, ";opacity:.7")}/>']),
    "leaf": ("0 0 24 24", [
        f'<path d="M12 19.5V23" {_line("currentColor", 1.3)}/>',
        '<path d="M12 2C18.5 6 19 14.5 12 20 5 14.5 5.5 6 12 2z" style="fill:currentColor"/>',
        '<path d="M12 18V5.5M12 10.5l2.8-2.4M12 14.5l3.4-2.9M12 10.5 9.2 8.1M12 14.5l-3.4-2.9" '
        f'{_line(CUT, .9, ";opacity:.7")}/>']),
    "acorn": ("0 0 20 24", [
        f'<path d="M3.5 10.5h13c0 6.6-3.6 11.2-6.5 12.6-2.9-1.4-6.5-6-6.5-12.6z" {_fill(GOLD)}/>',
        f'<path d="M10 7c0-2.1.6-3.8 2.1-5" {_line(BARK, 1.7)}/>',
        f'<path d="M1.8 11.6C1.8 5.6 18.2 5.6 18.2 11.6z" {_fill(BARK)}/>',
        f'<path d="M6.6 14c.3 3 1.4 5.5 2.9 7" {_line(CUT, 1.1, ";opacity:.45")}/>']),
    "apple": ("0 0 22 24", [
        '<path d="M11 7.5C7 4.5 1.5 6.5 2 13c.4 5.5 4.5 10 7 9.5 1-.2 1.4-.6 2-.6s1 .4 2 .6c2.5.5 '
        f'6.6-4 7-9.5.5-6.5-5-8.5-9-5.5z" {_fill(RED)}/>',
        f'<path d="M11 7.5c-.2-2.4.4-4.4 1.8-5.8" {_line(BARK, 1.5)}/>',
        f'<path d="M12.2 5c1.2-2.6 4-3.6 6.6-2.8-1.2 2.6-4 3.6-6.6 2.8z" {_fill(GREEN)}/>',
        f'<ellipse cx="6.5" cy="12" rx="1.4" ry="2.6" transform="rotate(20 6.5 12)" '
        f'{_fill(CUT, ";opacity:.45")}/>']),
    "bat": ("0 0 32 18", [
        '<path d="M13 7c-4-4.5-9-4.5-12-2 2 1 2.6 3 2.4 5 1.6-1.4 3.6-1.4 4.6 0 1-1.4 3-1.6 '
        '4.4-.2.4-1 .6-1.8.6-2.8zM19 7c4-4.5 9-4.5 12-2-2 1-2.6 3-2.4 5-1.6-1.4-3.6-1.4-4.6 0-1-1.4'
        '-3-1.6-4.4-.2-.4-1-.6-1.8-.6-2.8zM13.7 6.2l.2-4 1.7 2.6zM18.3 6.2l-.2-4-1.7 2.6z" '
        f'{_fill(PURPLE)}/>',
        f'<ellipse cx="16" cy="9.2" rx="3.4" ry="4.8" {_fill(PURPLE)}/>',
        f'<circle cx="14.7" cy="8.2" r=".9" {_fill(GLOW)}/>',
        f'<circle cx="17.3" cy="8.2" r=".9" {_fill(GLOW)}/>',
        f'<path d="M15 10.6q1 .8 2 0" {_line(GLOW, .6)}/>']),
    "ghost": ("0 0 24 28", [
        '<path d="M4 25V12a8 8 0 0 1 16 0v13' + "q-1.33 2.4-2.67 0" * 6 + 'z" '
        f'style="fill:{GHOST};stroke:{GHOST_LINE};stroke-width:1.4;stroke-linejoin:round"/>',
        f'<ellipse cx="9.4" cy="12.4" rx="1.3" ry="1.8" {_fill(GHOST_EYE)}/>',
        f'<ellipse cx="14.6" cy="12.4" rx="1.3" ry="1.8" {_fill(GHOST_EYE)}/>',
        f'<path d="M10.4 16.2q1.6 1.5 3.2 0" {_line(GHOST_EYE, 1.1)}/>',
        f'<circle cx="7.6" cy="15.2" r="1.3" {_fill(PINK, ";opacity:.35")}/>',
        f'<circle cx="16.4" cy="15.2" r="1.3" {_fill(PINK, ";opacity:.35")}/>']),
    "candy": ("0 0 16 20", [
        f'<path d="M8 1.6 14.6 16.4Q8 19.6 1.4 16.4z" {_solid(GOLD, 1.4)}/>',
        f'<path d="M8 1.6 12.6 11.9H3.4z" {_solid(ORANGE, 1.4)}/>',
        f'<path d="M8 1.6 10.2 6.6H5.8z" {_solid(CUT, 1.4)}/>']),
    "moon": ("0 0 24 24", [
        f'<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" {_fill(GOLD)}/>',
        f'<path d="M17.5 2.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" {_fill(GOLD)}/>']),
    "turkey": ("0 0 32 32", [
        *[f'<ellipse cx="16" cy="10" rx="4.2" ry="9" transform="rotate({angle} 16 19)" '
          f'{_fill(ink)}/>' for angle, ink in ((-64, GOLD), (-32, RED), (0, ORANGE),
                                              (32, RED), (64, GOLD))],
        f'<path d="M13.5 28.2v2.6M18.5 28.2v2.6" {_line(GOLD, 1.3)}/>',
        f'<ellipse cx="16" cy="21" rx="7.5" ry="7.8" {_fill(BARK)}/>',
        f'<circle cx="16" cy="13" r="3.8" {_fill(BARK)}/>',
        f'<circle cx="14.7" cy="12.4" r=".8" {_fill(GLOW)}/>',
        f'<circle cx="17.3" cy="12.4" r=".8" {_fill(GLOW)}/>',
        f'<path d="M15 14.2h2l-1 1.6z" {_solid(GOLD, .6)}/>',
        f'<path d="M16.6 14.8c.9.6 1 2 .3 2.8-.6-.6-.8-1.6-.3-2.8z" {_fill(RED)}/>']),
    "pie": ("0 0 32 32", [
        '<path d="M3 17h26l-2.4 7.4c-.4 1.3-1.5 2.1-2.8 2.1H8.2c-1.3 0-2.4-.8-2.8-2.1z" '
        f'{_fill(GOLD)}/>',
        f'<ellipse cx="16" cy="17" rx="13" ry="5" {_fill(ORANGE)}/>',
        f'<ellipse cx="16" cy="17" rx="13" ry="5" {_line(GOLD, 2.4, ";stroke-dasharray:2.2 1")}/>',
        f'<path d="M7 21.5h18" {_line(BARK, .8, ";opacity:.4")}/>',
        f'<path d="M13.4 15.6c.6-1.8 4.6-1.8 5.2 0-1.2.9-4 .9-5.2 0z" {_fill(CUT, ";opacity:.6")}/>']),
    "corn": ("0 0 24 32", [
        f'<ellipse cx="12" cy="13" rx="4.6" ry="11" {_fill(GOLD)}/>',
        '<path d="M9.7 3.5v19M12 2.2v21M14.3 3.5v19M8 6h8M7.6 9h8.8M7.4 12h9.2M7.4 15h9.2M7.8 18h8.4" '
        f'{_line(BARK, .55, ";opacity:.5")}/>',
        f'<path d="M12 30.5C6.4 27.4 5.2 20.6 6.8 14.4c1.2 4 3 7 5.2 8.6z" {_fill(GREEN)}/>',
        f'<path d="M12 30.5c5.6-3.1 6.8-9.9 5.2-16.1-1.2 4-3 7-5.2 8.6z" {_fill(GREEN)}/>']),
    "tree": ("0 0 28 32", [
        f'<rect x="12" y="24.5" width="4" height="5.5" rx="1" {_fill(BARK)}/>',
        f'<path d="M14 4 6 14.5h4L4.5 24h19L18 14.5h4z" {_solid(PINE, 1.2)}/>',
        f'<circle cx="11" cy="13" r="1.3" {_fill(RED)}/>',
        f'<circle cx="16.6" cy="11" r="1.2" {_fill(GOLD)}/>',
        f'<circle cx="17.5" cy="19.5" r="1.4" {_fill(RED)}/>',
        f'<circle cx="9.6" cy="20.6" r="1.3" {_fill(GOLD)}/>',
        f'<circle cx="13.6" cy="17" r="1.2" {_fill(ICE)}/>',
        f'<path d="{TOP_STAR}" {_solid(GOLD, .6)}/>']),
    "star": ("0 0 24 24", [f'<path d="{STAR}" {_solid(GOLD, 1.4)}/>']),
    "ornament": ("0 0 24 28", [
        f'<path d="M12 3.6c-1.7 0-1.7-2.6 0-2.6s1.7 2.6 0 2.6" {_line(BARK, .9)}/>',
        f'<rect x="9.4" y="3.4" width="5.2" height="3.6" rx=".8" {_fill(GOLD)}/>',
        '<circle cx="12" cy="16.5" r="10" style="fill:currentColor"/>',
        f'<path d="M2.8 14.6q9.2 4.4 18.4 0" {_line(CUT, 1.3, ";opacity:.6")}/>',
        f'<ellipse cx="8" cy="12.4" rx="1.6" ry="2.6" transform="rotate(30 8 12.4)" '
        f'{_fill(CUT, ";opacity:.45")}/>']),
    "bulb": ("0 0 16 24", [
        f'<rect x="5.5" y="1" width="5" height="5.2" rx="1" {_fill(BARK)}/>',
        '<path d="M8 5.6c3.4 0 5 4.4 5 8.4 0 4.2-2.4 8-5 8s-5-3.8-5-8c0-4 1.6-8.4 5-8.4z" '
        'style="fill:currentColor"/>',
        f'<ellipse cx="6.3" cy="11.6" rx="1" ry="2.2" {_fill(CUT, ";opacity:.45")}/>']),
    "snowflake": ("0 0 24 24", [
        f'<path d="{FLAKE_ARM}" transform="rotate({angle} 12 12)" {_line(ICE, 1.4)}/>'
        for angle in (0, 60, 120)]),
    "gift": ("0 0 24 24", [
        '<rect x="3.5" y="10.5" width="17" height="11.5" rx="1.4" style="fill:currentColor"/>',
        '<rect x="2.2" y="7.2" width="19.6" height="4.4" rx="1.2" style="fill:currentColor"/>',
        f'<rect x="2.2" y="10.6" width="19.6" height="1" {_fill(CUT, ";opacity:.35")}/>',
        f'<rect x="10.6" y="7.2" width="2.8" height="14.8" {_fill(GOLD)}/>',
        '<path d="M12 7.2c-1.4-3.6-6-4.4-6-1.7 0 1.9 3.6 2 6 1.7zM12 7.2c1.4-3.6 6-4.4 6-1.7 '
        f'0 1.9-3.6 2-6 1.7z" {_solid(GOLD, .8)}/>']),
    "mitten": ("0 0 22 28", [
        '<path d="M4.6 20V9.2c0-4.4 2.9-7.7 6.7-7.7s6.6 3.1 6.6 7.4V14c1.2-1.4 3.2-1.2 3.6.5.4 1.8'
        '-1.6 4-3.6 5.1V20z" style="fill:currentColor"/>',
        f'<path d="M6 11.6h10.4M6 14.2h10.4" {_line(CUT, 1.2, ";opacity:.6")}/>',
        '<rect x="3.6" y="19.4" width="15.4" height="6.6" rx="1.6" '
        f'style="fill:{CUT};stroke:currentColor;stroke-width:1.3"/>']),
    "snowman": ("0 0 24 32", [
        f'<path d="M5.2 20.2 1.6 16.6M18.8 20.2l3.6-3.6" {_line(BARK, 1.2)}/>',
        '<circle cx="12" cy="23.5" r="7.5" '
        f'style="fill:{GHOST};stroke:{GHOST_LINE};stroke-width:1.2"/>',
        '<circle cx="12" cy="12.2" r="5.4" '
        f'style="fill:{GHOST};stroke:{GHOST_LINE};stroke-width:1.2"/>',
        f'<path d="M7.2 16c3 1.5 6.6 1.5 9.6 0v1.9c-3 1.5-6.6 1.5-9.6 0zM14 17.2l1.6 4.3h-2.5l-.6-4z" '
        f'{_fill(RED)}/>',
        f'<rect x="8.6" y="1.6" width="6.8" height="5.4" rx=".8" {_fill(PURPLE)}/>',
        f'<rect x="6.6" y="6.4" width="10.8" height="1.7" rx=".8" {_fill(PURPLE)}/>',
        f'<circle cx="10.2" cy="11.2" r=".8" {_fill(GHOST_EYE)}/>',
        f'<circle cx="13.8" cy="11.2" r=".8" {_fill(GHOST_EYE)}/>',
        f'<path d="M12 12.6l3.8 1-3.8 1z" {_solid(ORANGE, .6)}/>',
        f'<circle cx="12" cy="22" r=".9" {_fill(GHOST_LINE)}/>',
        f'<circle cx="12" cy="25.4" r=".9" {_fill(GHOST_LINE)}/>']),
    "badge": ("0 0 32 32", [
        f'<circle cx="16" cy="16" r="15.2" style="fill:{CUT};stroke:var(--rule);stroke-width:.8"/>',
        f'<circle cx="16" cy="16" r="12.8" {_fill("var(--amber-bg)")}/>']),
}


# The garland: a twine hung in 8 swags across 640 units (the box shows y 1
# to 40 of them), an element at the low point and at the 2 quarter points
# of each swag, and at each of the 9 pins.
def _garland(low, quarter, pin, twine=BARK):
    path = "M0 5Q" + " ".join(f"{80 * i + 40} 24 {80 * i + 80} 5" for i in range(8))
    shapes = [f'<path d="{path}" {_line(twine, 1.3)}/>']
    shapes += [pin(i, 80 * i, 5) for i in range(9)]
    for i in range(8):
        x = 80 * i
        shapes += [quarter(i, 0, x + 20, 12.1), quarter(i, 1, x + 60, 12.1), low(i, x + 40, 14.5)]
    return shapes


def _bead(i, x, y):
    return f'<circle cx="{x}" cy="{y}" r="2.4" {_fill(GOLD)}/>'


def _tilt(i, size=10):
    return size if i % 2 else -size


def _maple(x, y, ink, i):
    return _use("maple", x - 11, y - 20.2, 22, ink=ink, rot=(180 + _tilt(i), x, y))


def _small_leaf(i, side, x, y, inks=(GOLD, RED, ORANGE, RED)):
    return _use("leaf", x - 6.5, y - 12.5, 13, ink=inks[(2 * i + side) % len(inks)],
                rot=(152 if side else 208, x, y))


def _acorn_pin(i, x, y):
    return _use("acorn", x - 6, y - 1, 12) if i in (2, 4, 6) else _bead(i, x, y)


def _fall_low(i, x, y):
    if i == 3:
        return _use("apple", x - 9.2, y - 1.1, 16, rot=(_tilt(i), x, y))
    return _maple(x, y, (RED, GOLD, ORANGE)[i % 3], i)


def _halloween_low(i, x, y):
    kind = ("jack", "ghost", "jack", "moon")[i % 4]
    if kind == "jack":
        return _use("jack", x - 10.9, y - 1.8, 20, rot=(_tilt(i, 6), x, y))
    if kind == "ghost":
        return _use("ghost", x - 7.5, y - 2.5, 15, 17.5, rot=(_tilt(i, 6), x, y))
    return _use("moon", x - 7.5, y - 2, 16, rot=(_tilt(i, 6), x, y))


def _halloween_quarter(i, side, x, y):
    return _use("candy", x - 4.8, y - 11.2, 9.6, 12, rot=(165 if side else 195, x, y))


def _halloween_pin(i, x, y):
    return _use("bat", x - 9, y - 4, 18, 10.1) if i in (3, 5) else _bead(i, x, y)


def _thanksgiving_low(i, x, y):
    if i % 2:
        return _use("corn", x - 7.5, y - 1.2, 15, 20, rot=(_tilt(i, 8), x, y))
    return _maple(x, y, (ORANGE, RED, GOLD)[(i // 2) % 3], i)


def _christmas_low(i, x, y):
    return _use("ornament", x - 8, y - .7, 16, 18.7, ink=(RED, GOLD, PURPLE, ICE)[i % 4],
                rot=(_tilt(i, 5), x, y))


def _christmas_quarter(i, side, x, y):
    ink = (RED, GOLD, PINE, ICE, PURPLE)[(2 * i + side) % 5]
    return _use("bulb", x - 4, y - .5, 8, 12, ink=ink, rot=(18 if side else -18, x, y))


def _christmas_pin(i, x, y):
    return _use("star", x - 5, y - 5, 10) if i % 2 == 0 else _bead(i, x, y)


def _winter_low(i, x, y):
    if i % 2:
        return _use("snowflake", x - 9, y - .5, 18)
    # A mitten hangs by its cuff.
    return _use("mitten", x - 7.24, y - 16.67, 14.1, 18, ink=(RED, ICE, PURPLE)[(i // 2) % 3],
                rot=(180 + _tilt(i, 6), x, y))


def _winter_quarter(i, side, x, y):
    return _use("snowflake", x - 5, y - .4, 10)


# Each theme: the garland, the element by the title, and the elements of
# the corners and stickers ("name" or "name:ink").
THEMES = {
    "fall": {"garland": _garland(_fall_low, _small_leaf, _acorn_pin), "title": "pumpkin",
             "art": ("maple:red", "pumpkin", "acorn", "leaf:gold", "apple", "maple:orange")},
    "halloween": {"garland": _garland(_halloween_low, _halloween_quarter, _halloween_pin),
                  "title": "ghost", "art": ("jack", "bat", "ghost", "candy", "moon")},
    "thanksgiving": {"garland": _garland(_thanksgiving_low, _small_leaf, _acorn_pin),
                     "title": "turkey",
                     "art": ("turkey", "pie", "corn", "maple:orange", "leaf:red", "maple:gold")},
    "christmas": {"garland": _garland(_christmas_low, _christmas_quarter, _christmas_pin, PINE),
                  "title": "tree",
                  "art": ("tree", "ornament:red", "star", "gift:red", "snowflake",
                          "ornament:gold", "gift:pine")},
    "winter": {"garland": _garland(_winter_low, _winter_quarter, _bead), "title": "snowman",
               "art": ("snowflake", "mitten:red", "snowman", "mitten:ice", "snowflake",
                       "mitten:purple")},
}
# The mark of a holiday: after ``.dnum`` in its day row, and first in ``.nx``.
MARKS = {"halloween": "jack", "thanksgiving": "turkey", "christmas": "tree", "new_year": "star"}

# Where a sticker can go: slot -> (position, size). A day sticker sits on
# the top left edge of a day card that has no corner element (not Monday:
# the week label above it can reach the left edge).
STICKER_AT = {"legend": ("top:-12px;right:16px", 20), "next": ("top:-27px;right:16px", 34),
              "foot": ("bottom:6px;right:22px", 28)}
DAY_STICKER = ("top:-14px;left:-6px", 24)
WIDE_AT = (("top:110px;left:-66px", 46), ("top:330px;right:-68px", 46),
           ("top:560px;left:-64px", 46), ("top:790px;right:-66px", 46))

CSS = ("  #hh-whiteboard-page{position:relative;padding-top:52px}",
       "  #hh-whiteboard-page .legend,#hh-whiteboard-page .day,#hh-whiteboard-page .next"
       "{position:relative}",
       "  #hh-whiteboard-page .sn{position:absolute;pointer-events:none;overflow:visible}",
       "  #hh-whiteboard-page .sn-garland{top:0;left:6px;width:calc(100% - 12px);height:47px}",
       "  #hh-whiteboard-page .sn-title{position:static;float:left;width:28px;height:28px;"
       "margin:0 8px 0 -2px}",
       "  #hh-whiteboard-page .sn-corner{top:-7px;right:-14px;width:26px;height:26px}",
       "  #hh-whiteboard-page .sn-mark{position:static;display:block;width:22px;height:22px;"
       "margin:3px auto 0}",
       "  #hh-whiteboard-page .sn-nx{position:static;display:inline-block;width:15px;"
       "height:15px;vertical-align:-3px;margin-right:5px}",
       "  #hh-whiteboard-page .sn-wide{display:none}",
       "  @media (min-width:900px){#hh-whiteboard-page .sn-wide{display:block}}")


def mix(monday):
    """The mix of a week: (days with a corner element, slots with a sticker, art offset).

    3 or 4 of the 7 day cards get a corner element, 2 or 3 of the gaps a
    sticker; a hash of the Monday picks them.
    """
    h = hashlib.sha256(f"whiteboard-season-{monday.isoformat()}".encode("ascii")).digest()
    days = sorted(range(7), key=lambda i: (h[i], i))
    corners = sorted(days[:3 + h[7] % 2])
    gaps = ["legend", "next", "foot"] + [f"day{i}" for i in range(1, 7) if i not in corners]
    stickers = sorted(gaps, key=lambda g: (h[8 + gaps.index(g)], g))[:2 + h[20] % 2]
    return corners, sorted(stickers), h[21]


def _art_use(art, inset):
    """The ``<use>`` of an element named ``name`` or ``name:ink`` in a 32 box."""
    name, _, ink = art.partition(":")
    return _use(name, inset, inset, 32 - 2 * inset, ink=INKS.get(ink))


def _placed(cls, style, inner, box="0 0 32 32"):
    style = f' style="{style}"' if style else ""
    return f'<svg class="{cls}" viewBox="{box}"{style} aria-hidden="true">{inner}</svg>'


def _sticker(cls, where, size, art, tilt):
    inner = (f'<g transform="rotate({tilt} 16 16)"><use href="#sn-badge"/>'
             f"{_art_use(art, 6)}</g>")
    return _placed(cls, f"{where};width:{size}px;height:{size}px", inner)


def _placements(theme, monday):
    """slot -> the placed ``<svg>`` lines of ``theme`` in the week of ``monday``."""
    spec = THEMES[theme]
    art = spec["art"]
    corners, stickers, offset = mix(monday)
    places = {"head": [f'<svg class="sn sn-garland" aria-hidden="true">'
                       f'<use href="#sn-garland-{theme}"/></svg>'],
              "title": [_placed("sn sn-title", "", _use(spec["title"], 0, 0, 32))]}
    # The corners, the stickers and the wide stickers take the art in turn
    # (9 or more places), so each element of the theme is on each page.
    tilts = (-12, 9, -6, 12, -9, 7, -10, 10)
    for k, day in enumerate(corners):
        tilt = tilts[(offset + k) % len(tilts)]
        inner = f'<g transform="rotate({tilt} 16 16)">{_art_use(art[(offset + k) % len(art)], 0)}</g>'
        places[f"day{day}"] = [_placed("sn sn-corner", "", inner)]
    for k, slot in enumerate(stickers):
        where, size = STICKER_AT.get(slot, DAY_STICKER)
        line = _sticker("sn", where, size, art[(offset + len(corners) + k) % len(art)],
                        tilts[(offset + 3 + k) % len(tilts)])
        places.setdefault(slot, []).append(line)
    for k, (where, size) in enumerate(WIDE_AT):
        first = offset + len(corners) + len(stickers)
        places["head"].append(_sticker("sn sn-wide", where, size, art[(first + k) % len(art)],
                                       tilts[(offset + 5 + k) % len(tilts)]))
    return places


def _mark(holiday, inline):
    cls = "sn sn-nx" if inline else "sn sn-mark"
    return f'<svg class="{cls}" aria-hidden="true"><use href="#sn-{MARKS[holiday]}"/></svg>'


def _symbol(name):
    if name.startswith("garland-"):
        shapes = THEMES[name[len("garland-"):]]["garland"]
        return ([f'  <symbol id="sn-{name}" viewBox="0 1 640 39" '
                 'preserveAspectRatio="xMidYMin slice">']
                + [f"  {shape}" for shape in shapes] + ["  </symbol>"])
    box, shapes = SYMBOLS[name]
    return [f'  <symbol id="sn-{name}" viewBox="{box}">{"".join(shapes)}</symbol>']


REF = re.compile(r'href="#sn-([\w-]+)"')


def markup(theme, monday, days=()):
    """slot -> lines of the season markup of ``theme`` for the week of ``monday``; {} for no theme.

    ``days``: the dates of the rows of the page (this week and the coming
    week); a holiday among them gets its mark under ``mark:<date>``, and
    ``nxmark:<date>`` for a row of the coming week.
    """
    if not theme:
        return {}
    places = _placements(theme, monday)
    this_week = {monday.toordinal() + i for i in range(7)}
    for day in days:
        holiday = season.holiday_of(day)
        if holiday:
            inline = day.toordinal() not in this_week
            places[f"{'nxmark' if inline else 'mark'}:{day.isoformat()}"] = [_mark(holiday, inline)]
    # The sprite: each symbol that a placed element names, and the symbols those name.
    names, todo = [], [n for lines in places.values() for line in lines for n in REF.findall(line)]
    while todo:
        name = todo.pop(0)
        if name not in names:
            names.append(name)
            todo += REF.findall("".join(_symbol(name)))
    sprite = ['<svg width="0" height="0" style="position:absolute" aria-hidden="true">']
    for name in sorted(names):
        sprite += _symbol(name)
    sprite.append("</svg>")
    places["head"] = ["<style>", *CSS, "</style>", *sprite, *places["head"]]
    return places

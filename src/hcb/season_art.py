"""The seasonal elements of the whiteboard page: the drawings and the look.

``markup(theme, monday, days)`` gives the season markup of a page: a dict
from a slot of the page (``head``, ``title``, ``legend``, ``day0`` to
``day6``, ``next``, ``foot``) to the new lines that render.py puts there,
and from ``mark:<date>`` to the inline mark of a holiday. Only the lines
that hold a mark change; the existing elements of those lines keep their
bytes.

The look: 2 fixed elements in each week with a theme, a garland hung along
the top edge of the board and an element by the title; below them a mix of
elements on the top right
corner of 3 or 4 day cards and 2 or 3 round stickers in the gaps between
the sections, and 4 larger stickers in the margins on a wide screen only.
A hash of the Monday picks the mix, so each week looks a little different
and each run of the same week gives the same page.

The drawings, their inks and the theme table live in art.py, shared with
the dinner plan and the groceries page (menu_art.py); this module places
them on the whiteboard with the whiteboard's color map and the sprite ids
``sn-``. The sprite holds only the symbols that the page uses. Size and
position go on the outer ``<svg>``, which has ``pointer-events:none`` and
``aria-hidden="true"``.

No text from a calendar, the notes page or the model reaches this module:
the markup is a function of the theme and the dates alone.

Each line starts with ``<`` or 2 spaces, and none holds ``<!--`` (the rules
of the write gate; see render.py).
"""
import hashlib

from . import art as artmod
from . import season

ART = artmod.Art(artmod.COLORS["whiteboard"], "sn")
THEMES = artmod.THEMES
# The mark of a holiday: after ``.dnum`` in its day row, and first in ``.nx``.
MARKS = artmod.MARKS

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


def _placed(cls, style, inner, box="0 0 32 32"):
    style = f' style="{style}"' if style else ""
    return f'<svg class="{cls}" viewBox="{box}"{style} aria-hidden="true">{inner}</svg>'


def _sticker(cls, where, size, art, tilt):
    inner = (f'<g transform="rotate({tilt} 16 16)"><use href="#sn-badge"/>'
             f"{ART.art_use(art, 6)}</g>")
    return _placed(cls, f"{where};width:{size}px;height:{size}px", inner)


def _placements(theme, monday):
    """slot -> the placed ``<svg>`` lines of ``theme`` in the week of ``monday``."""
    spec = THEMES[theme]
    art = spec["art"]
    corners, stickers, offset = mix(monday)
    places = {"head": [f'<svg class="sn sn-garland" aria-hidden="true">'
                       f'<use href="#sn-garland-{theme}"/></svg>'],
              "title": [_placed("sn sn-title", "", ART.use(spec["title"], 0, 0, 32))]}
    # The corners, the stickers and the wide stickers take the art in turn
    # (9 or more places), so each element of the theme is on each page.
    tilts = (-12, 9, -6, 12, -9, 7, -10, 10)
    for k, day in enumerate(corners):
        tilt = tilts[(offset + k) % len(tilts)]
        inner = (f'<g transform="rotate({tilt} 16 16)">'
                 f'{ART.art_use(art[(offset + k) % len(art)], 0)}</g>')
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
    sprite = ART.sprite([line for lines in places.values() for line in lines])
    places["head"] = ["<style>", *CSS, "</style>", *sprite, *places["head"]]
    return places

"""The seasonal icons of the dinner plan and the groceries page.

``markup(page, theme, monday)`` gives the art of ``page`` (``menu`` or
``groceries``) in a week of ``theme``: the lines of the head (a second
``<style>``, the hidden sprite ``<svg>`` and the garland), the icon by the
title, and the corner icons of 3 or 4 boxes; {} for no theme. The drawings
are those of the whiteboard (art.py), in the page's own color map and with
its own sprite ids and classes (``hm`` on the dinner plan, ``hg`` on the
groceries page). The dinner plan puts a corner icon on the day cards that
have one on the whiteboard of the same week (``season_art.mix``); the
groceries page on the meal box and the first list sections, as many.

Like the whiteboard art, every line starts with ``<`` or 2 spaces, holds no
``<!--`` and no text, and each placed ``<svg>`` has ``pointer-events:none``
and ``aria-hidden="true"``. No text of the plan reaches this module.
"""
from . import art as artmod
from . import season_art

PAGES = {"menu": ("#hh-menu-page", "hm", ".day"),
         "groceries": ("#hh-groceries-page", "hg", ".meals,.sect")}
TILTS = (-12, 9, -6, 12, -9, 7, -10, 10)
ARTS = {page: artmod.Art(artmod.COLORS[page], prefix) for page, (_, prefix, _) in PAGES.items()}


def _css(page):
    w, p, boxes = PAGES[page]
    return (f"  {w}{{position:relative;padding-top:52px}}",
            "  " + ",".join(f"{w} {box}" for box in boxes.split(",")) + "{position:relative}",
            f"  {w} .{p}{{position:absolute;pointer-events:none;overflow:visible}}",
            f"  {w} .{p}-garland{{top:0;left:6px;width:calc(100% - 12px);height:47px}}",
            f"  {w} .{p}-title{{position:static;display:inline-block;width:26px;height:26px;"
            "vertical-align:-5px;margin-right:8px}",
            f"  {w} .{p}-corner{{top:-9px;right:-9px;width:24px;height:24px}}")


def markup(page, theme, monday):
    """{"head": lines, "title": an inline ``<svg>``, "corners": {index: line}}; {} for None.

    ``corners`` holds 1 line for each box with a corner icon: on the dinner
    plan the day cards of ``season_art.mix(monday)`` (by their index, Monday
    0), on the groceries page the boxes in order (the meal box first).
    """
    if not theme:
        return {}
    _, p, _ = PAGES[page]
    art = ARTS[page]
    spec = artmod.THEMES[theme]
    days, _, offset = season_art.mix(monday)
    title = (f'<svg class="{p} {p}-title" viewBox="0 0 32 32" aria-hidden="true">'
             f'{art.use(spec["title"], 0, 0, 32)}</svg>')
    corners = {}
    for k, day in enumerate(days):
        element = spec["art"][(offset + k) % len(spec["art"])]
        tilt = TILTS[(offset + k) % len(TILTS)]
        corners[day if page == "menu" else k] = (
            f'  <svg class="{p} {p}-corner" viewBox="0 0 32 32" aria-hidden="true">'
            f'<g transform="rotate({tilt} 16 16)">{art.art_use(element, 0)}</g></svg>')
    garland = (f'<svg class="{p} {p}-garland" aria-hidden="true">'
               f'<use href="#{p}-garland-{theme}"/></svg>')
    sprite = art.sprite([title, garland, *corners.values()])
    return {"head": ["<style>", *_css(page), "</style>", *sprite, garland],
            "title": title, "corners": corners}

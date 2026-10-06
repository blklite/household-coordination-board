"""The theme of a week and the holidays of the whiteboard page.

The Monday of the board's week (``week.this_week[0].date``) selects the
theme, never the day of the run:

- ``fall``: the Mondays from Sep 16 up to, not including, the first Halloween week;
- ``halloween``: the week that holds Oct 31, and the week before it;
- ``thanksgiving``: then up to and including the week that holds the 4th
  Thursday of November;
- ``christmas``: then up to and including the week that holds Jan 1;
- ``winter``: then each Monday in January or February;
- None: each other week.

``holiday_of`` names the 4 days that get a mark: Oct 31, Thanksgiving,
Dec 25 and Jan 1.
"""
import datetime as dt

WEEK = dt.timedelta(days=7)


def _monday(day):
    return day - dt.timedelta(days=day.weekday())


def thanksgiving(year):
    """The 4th Thursday of November of ``year``."""
    first = dt.date(year, 11, 1)
    return first + dt.timedelta(days=(3 - first.weekday()) % 7 + 21)


def _themes(year):
    """(theme, first Monday, last Monday) of each theme of the season that starts in ``year``."""
    fall = dt.date(year, 9, 16)
    fall += dt.timedelta(days=-fall.weekday() % 7)
    halloween = _monday(dt.date(year, 10, 31))
    turkey = _monday(thanksgiving(year))
    new_year = _monday(dt.date(year + 1, 1, 1))
    last_winter = _monday(dt.date(year + 1, 3, 1) - dt.timedelta(days=1))
    return (("fall", fall, halloween - 2 * WEEK),
            ("halloween", halloween - WEEK, halloween),
            ("thanksgiving", halloween + WEEK, turkey),
            ("christmas", turkey + WEEK, new_year),
            ("winter", new_year + WEEK, last_winter))


def theme_of(monday):
    """``"fall"``, ``"halloween"``, ``"thanksgiving"``, ``"christmas"``, ``"winter"`` or None."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday.isoformat()} is not a Monday")
    for year in (monday.year - 1, monday.year):
        for theme, first, last in _themes(year):
            if first <= monday <= last:
                return theme
    return None


def holiday_of(day):
    """``"halloween"``, ``"thanksgiving"``, ``"christmas"``, ``"new_year"`` or None."""
    if (day.month, day.day) == (10, 31):
        return "halloween"
    if day.month == 11 and day == thanksgiving(day.year):
        return "thanksgiving"
    if (day.month, day.day) == (12, 25):
        return "christmas"
    if (day.month, day.day) == (1, 1):
        return "new_year"
    return None

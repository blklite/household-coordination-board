"""The copy that dedupe keeps of an event on more than 1 calendar."""
import datetime as dt

import pytest
from conftest import MONDAY, URLS, all_day, calendar, timed

from hcb import calendars, jobs
from hcb import week as weekmod
from hcb.calendars import Event

FRIDAY = MONDAY + dt.timedelta(days=4)


def copy(calendar_, title="Alex Weekend", uid="alex-weekend", description=""):
    """An all-day Fri-Sun event on ``calendar_``; the same ``uid`` on each copy by default."""
    return Event(calendar_, uid, title, description, "", True, FRIDAY,
                 FRIDAY + dt.timedelta(days=3), tuple(FRIDAY + dt.timedelta(days=i)
                                                      for i in range(3)))


def kept(household, *events):
    return calendars.dedupe(list(events), jobs.custody_copy(household))


@pytest.mark.parametrize("order", [("Family", "Maya's Schedule"), ("Maya's Schedule", "Family")])
@pytest.mark.parametrize("match", ["uid", "title and times"])
def test_dedupe_keeps_the_custody_copy_in_both_calendar_orders(household, order, match):
    events = [copy(name, uid=f"{name}-uid" if match == "title and times" else "alex-weekend")
              for name in order]
    assert [e.calendar for e in kept(household, *events)] == ["Maya's Schedule"]


def test_dedupe_keeps_the_first_custody_copy_of_3_copies_at_the_place_of_the_first(household):
    found = kept(household, copy("Family"), copy("Family", title="Soccer", uid="soccer"),
                 copy("Maya's Schedule", description="first"),
                 copy("Custody", description="custody:sam"))
    assert [(e.calendar, e.title) for e in found] == [("Maya's Schedule", "Alex Weekend"),
                                                     ("Family", "Soccer")]
    assert found[0].description == "first"
    found = kept(household, copy("Family"), copy("Alex"), copy("Maya's Schedule"))
    assert [e.calendar for e in found] == ["Maya's Schedule"]


def test_dedupe_keeps_the_first_copy_of_a_normal_event(household):
    for order in (("Family", "Maya's Schedule"), ("Maya's Schedule", "Family")):
        found = kept(household, *[copy(name, title="Birthday party") for name in order])
        assert [e.calendar for e in found] == [order[0]]
    # A custody title on a calendar with no custody rule is no custody copy.
    assert [e.calendar for e in kept(household, copy("Family"), copy("Alex"))] == ["Family"]
    # With no test, the first copy as before.
    found = calendars.dedupe([copy("Family"), copy("Maya's Schedule")])
    assert [e.calendar for e in found] == ["Family"]


def test_a_custody_event_also_on_family_keeps_its_label(household, fetch):
    # Family is listed before Maya's Schedule; its copy of "Alex Weekend" has another UID.
    fetch.served[URLS["HCB_ICAL_FAMILY"]] = calendar(
        all_day("f-copy", "Alex Weekend", 4, 3),
        timed("f1", "Dentist: Theo", 2, "1530", "1630", "Main St Dental"))
    events, missing = jobs.read_events(household, MONDAY, 14, fetch=fetch)
    assert missing == []
    assert [e.calendar for e in events if e.title == "Alex Weekend" and FRIDAY in e.days] == [
        "Maya's Schedule"]
    week = weekmod.build_week(events, MONDAY, weekmod.Notes(), household)
    weekend = week.days[4:7]
    assert [d.kids["Maya"].state for d in weekend] == ["home"] * 3
    assert [p.title for d in weekend for p in d.pills if p.title == "Alex Weekend"] == []
    assert [d.transitions for d in weekend][1:] == [[], []]
    assert len(weekend[0].transitions) == 1 and "Maya" in "".join(weekend[0].transitions[0])
    assert not [p for p in week.open_points if "Maya" in p]


def test_dedupe_a_third_copy_that_matches_only_the_kept_custody_copy_is_dropped(household):
    # Family and Maya's Schedule match by title and times; the copy on Alex matches the
    # copy of Maya's Schedule by uid only.
    found = kept(household, copy("Family", uid="family-uid"),
                 copy("Maya's Schedule", uid="maya-uid"),
                 copy("Alex", title="Alex Weekend (copy)", uid="maya-uid"))
    assert [e.calendar for e in found] == ["Maya's Schedule"]


def test_dedupe_keeps_the_family_copy_of_an_ignored_custody_title(household):
    # An ignored title on Custody gives no label, so it is no custody copy; the Family
    # copy (listed first) is kept and its pill stays.
    found = kept(household, copy("Family", title="Shift Night"),
                 copy("Custody", title="Shift Night"))
    assert [e.calendar for e in found] == ["Family"]
    week = weekmod.build_week(found, MONDAY, weekmod.Notes(), household)
    assert [p.title for p in week.days[4].pills] == ["Shift Night"]
    # A labelled custody event on Custody still wins over the Family copy.
    found = kept(household, copy("Family", title="Sam"), copy("Custody", title="Sam"))
    assert [e.calendar for e in found] == ["Custody"]

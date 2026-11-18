"""The DST fortnight: the whiteboard across the end of daylight saving time.

The example household is in America/New_York. Daylight saving time ends
there at 02:00 on Sun 2026-11-01: the clocks go from EDT (UTC-4) back to EST
(UTC-5), and 01:00 to 02:00 comes twice. The Sunday run of 2026-10-25 06:00
builds Mon Oct 26 to Sun Nov 8, a
fortnight that holds the change; the fortnight of the other tests holds none.

The calendars are made up, for the example household. Family has a weekly
event on both sides of the change. Alex has an event in the hour that comes
twice and a late event after the change. Leo Soccer gives each event as a UTC
instant, as many team feeds do: a practice at 17:00 is 21:00Z before the
change and 22:00Z after it. Maya's Schedule puts Maya across the change.
"""
import datetime as dt

import pytest
from conftest import NOTES, URLS, FakeRunner, calendar

from hcb import cli, notes_step
from hcb import week as weekmod

# Sun 2026-10-25 06:00 America/New_York (EDT, UTC-4): the run that builds the DST fortnight.
SUNDAY = dt.datetime(2026, 10, 25, 10, 0, tzinfo=dt.timezone.utc)
MONDAY = dt.date(2026, 10, 26)
CHANGE = dt.date(2026, 11, 1)


def event(uid, title, start, end, extra=""):
    return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{title}\r\n{start}\r\n{end}\r\n{extra}"
            "END:VEVENT\r\n")


def utc(uid, title, start, end):
    return event(uid, title, f"DTSTART:{start}Z", f"DTEND:{end}Z")


def local(uid, title, start, end, extra=""):
    return event(uid, title, f"DTSTART;TZID=America/New_York:{start}",
                 f"DTEND;TZID=America/New_York:{end}", extra)


def day(uid, title, first, end):
    return event(uid, title, f"DTSTART;VALUE=DATE:{first}", f"DTEND;VALUE=DATE:{end}")


def bodies():
    family = [local("swim", "Swim lessons", "20261028T173000", "20261028T183000",
                    "RRULE:FREQ=WEEKLY;COUNT=2\r\n")]
    alex = [utc("redeye", "Red-eye lands", "20261101T053000", "20261101T073000"),
            local("pickup", "Airport pickup", "20261101T231500", "20261101T234500")]
    soccer = [utc("p1", "Leo Soccer Lightning practice", "20261026T210000", "20261026T230000"),
              utc("p2", "Leo Soccer Lightning practice", "20261029T210000", "20261029T230000"),
              utc("g1", "Leo Soccer Lightning game", "20261101T180000", "20261101T193000"),
              utc("p3", "Leo Soccer Lightning practice", "20261102T220000", "20261103T000000"),
              utc("p4", "Leo Soccer Lightning practice", "20261105T220000", "20261106T000000")]
    maya = [day("m1", "Alex Night", "20261026", "20261028"),
            day("m2", "Jordan Night", "20261028", "20261030"),
            day("m3", "Alex Weekend", "20261030", "20261102"),
            day("m4", "Jordan Night", "20261102", "20261104"),
            day("m5", "Alex Night", "20261104", "20261109")]
    custody = [day("c1", "Sam", "20261026", "20261109")]
    return {URLS["HCB_ICAL_FAMILY"]: calendar(*family),
            URLS["HCB_ICAL_ALEX"]: calendar(*alex),
            URLS["HCB_ICAL_MAYA"]: calendar(*maya),
            URLS["HCB_ICAL_CUSTODY"]: calendar(*custody),
            URLS["HCB_ICAL_LEO_SOCCER"].replace("webcal://", "https://"): calendar(*soccer)}


@pytest.fixture
def week(home, monkeypatch):
    """The ``Week`` of the Sunday run of 2026-10-25 06:00."""
    served = bodies()
    built = []
    real = weekmod.build_week

    def keep(*args, **kwargs):
        built.append(real(*args, **kwargs))
        return built[-1]
    monkeypatch.setattr(weekmod, "build_week", keep)
    lines = []
    code = cli.main(["-c", str(home / "household.toml"), "whiteboard"], now=lambda: SUNDAY,
                    out=lines.append, fetch=lambda url, *a, **k: served[url],
                    runner=FakeRunner(NOTES, notes_step.LAST_LINE))
    assert code == 0, lines
    (found,) = built
    return found


def times(week, title):
    """``{date: time}`` of each pill of the event ``title``."""
    return {d.date: pill.time for d in week.days for pill in d.pills if pill.event.title == title}


def test_the_run_of_oct_25_builds_the_14_days_mon_oct_26_to_sun_nov_8(week):
    assert [d.date for d in week.days] == [MONDAY + dt.timedelta(days=i) for i in range(14)]
    assert week.this_week[-1].date == CHANGE


def test_a_weekly_event_keeps_its_local_time_on_both_sides_of_the_change(week):
    assert times(week, "Swim lessons") == {dt.date(2026, 10, 28): "5:30–6:30p",
                                           dt.date(2026, 11, 4): "5:30–6:30p"}


def test_utc_practices_show_at_5p_on_both_sides_of_the_change(week):
    found = times(week, "Leo Soccer Lightning practice")
    assert found == {dt.date(2026, 10, 26): "5–7p", dt.date(2026, 10, 29): "5–7p",
                     dt.date(2026, 11, 2): "5–7p", dt.date(2026, 11, 5): "5–7p"}


def test_a_utc_event_on_the_day_of_the_change_shows_in_est(week):
    # 18:00Z on Sun Nov 1 is 13:00 EST (14:00 at the offset of the day before).
    assert times(week, "Leo Soccer Lightning game") == {CHANGE: "1–2:30p"}


def test_a_late_event_after_the_change_stays_on_its_local_day(week):
    # 23:15 EST on Sun Nov 1 is 04:15Z on Mon Nov 2.
    assert times(week, "Airport pickup") == {CHANGE: "11:15–11:45p"}


def test_an_event_that_starts_in_the_hour_that_comes_twice_shows_its_local_times(week):
    # 05:30Z is the first 01:30 (EDT); 07:30Z is 02:30 EST: 2 hours, shown as the clock reads.
    assert times(week, "Red-eye lands") == {CHANGE: "1:30–2:30a"}


def test_a_kid_follows_the_custody_calendar_on_both_sides_of_the_change(week):
    states = {d.date: d.kids["Maya"].state for d in week.days}
    # Alex Weekend Fri Oct 30 to Sun Nov 1, then Jordan Night Mon Nov 2 and Tue Nov 3.
    assert [states[dt.date(2026, 10, 30) + dt.timedelta(days=i)] for i in range(6)] == [
        "home", "home", "home", "away", "away", "home"]

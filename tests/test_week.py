"""The custody rules and the table lines, on events made in the test."""
import datetime as dt

from conftest import MONDAY

from hcb import calendars, seats, kitchen
from hcb.calendars import Event
from hcb.week import Notes, Override, build_week, custody_labels, parse_notes

TZ = calendars.TZ


def day_event(calendar, title, offset, days=1, description=""):
    start = MONDAY + dt.timedelta(days=offset)
    return Event(calendar, f"{calendar}-{title}-{offset}", title, description, "", True, start,
                 start + dt.timedelta(days=days),
                 tuple(start + dt.timedelta(days=i) for i in range(days)))


def time_event(calendar, title, offset, start, end, description=""):
    day = MONDAY + dt.timedelta(days=offset)
    begin = dt.datetime.combine(day, start, TZ)
    return Event(calendar, f"{calendar}-{title}-{offset}", title, description, "", False, begin,
                 dt.datetime.combine(day, end, TZ), (day,))


def week_of(household, events, notes=None):
    calendars.set_timezone(household.timezone)
    return build_week(events, MONDAY, notes or Notes(), household)


def test_titles_set_home_and_away(household):
    week = week_of(household, [day_event("Maya's Schedule", "Alex Night", 0),
                               day_event("Maya's Schedule", "jordan night", 1)])
    assert week.days[0].kids["Maya"].state == "home"
    assert week.days[1].kids["Maya"].state == "away"
    assert week.days[1].kids["Maya"].label == "Jordan · PM w/ Alex"
    assert week.days[2].kids["Maya"].state == "unsure"


def test_a_title_on_another_calendar_is_a_plain_event(household):
    week = week_of(household, [day_event("Family", "Alex Night", 0)])
    assert week.days[0].kids["Maya"].state == "unsure"
    assert [p.title for p in week.days[0].pills] == ["Alex Night"]


def test_an_ignored_title_changes_nothing(household):
    week = week_of(household, [day_event("Custody", "Sam", 0, 2),
                               day_event("Custody", "Shift Night", 1)])
    assert week.days[1].kids["Leo"].state == "home"
    assert week.days[1].pills == []


def test_a_tag_works_on_any_calendar(household):
    event = day_event("Family", "Weekend at the lake", 0, description="custody:chris")
    labels = custody_labels(event, household)
    assert [(lab.rule, lab.state) for lab in labels] == [("chris", "away")]


def test_a_trade_replaces_the_base_label(household):
    week = week_of(household, [day_event("Maya's Schedule", "Jordan Night", 0),
                               day_event("Maya's Schedule", "TRADE Alex has Maya", 0)])
    assert week.days[0].kids["Maya"].state == "home"
    assert week.days[0].kids["Maya"].label == "TRADE Alex has Maya"


def test_a_trade_with_no_side_is_unsure(household):
    week = week_of(household, [day_event("Maya's Schedule", "TRADE swap tbd", 0)])
    assert week.days[0].kids["Maya"].why == "the trade event names no side"


def test_labels_that_disagree_are_unsure(household):
    week = week_of(household, [day_event("Custody", "Sam", 0), day_event("Custody", "Chris", 0)])
    assert week.days[0].kids["Leo"].why == "custody labels disagree"
    assert "Mon Oct 12: Leo and Ivy unsure (custody labels disagree)" in week.open_points


def test_an_override_wins_and_is_an_open_point(household):
    notes = Notes(overrides=[Override(MONDAY, "Ivy", "away", "sleepover")])
    week = week_of(household, [day_event("Custody", "Sam", 0)], notes)
    assert week.days[0].kids["Ivy"].state == "away"
    assert "Mon Oct 12: Ivy away by override (sleepover)" in week.open_points


def test_a_bypass_rule_takes_a_kid_off_the_board(household):
    household.bypass = [{"kid": "Theo", "start": MONDAY.isoformat(), "end": None,
                         "status": "off"}]
    week = week_of(household, [])
    assert week.days[0].kids["Theo"].state == "off"
    assert "Bypass rule: Theo off the board from Mon Oct 12, no end" in week.config_points


def test_notes_overrides_use_aliases(household):
    notes = parse_notes("## Overrides\n- 2026-10-12 | maya | away | trip\n- bad line\n",
                        MONDAY, household.kid_aliases())
    assert notes.overrides == [Override(MONDAY, "Maya", "away", "trip")]
    assert notes.problems == ["Notes file: an Overrides line does not parse: - bad line"]


def kitchen_for(household, practice):
    settings = household.kitchen
    return kitchen.Kitchen(settings.dinner, settings.snack, practice, settings.latest_dinner)


def test_eat_together_moves_dinner(household):
    events = [day_event("Maya's Schedule", "Alex Night", 0), day_event("Custody", "Sam", 0),
              time_event("Leo Soccer", "Practice", 0, dt.time(17), dt.time(19))]
    household.calendars[4]["people"] = ["Leo"]
    week = week_of(household, events)
    line = seats.table_lines(week, household, kitchen_for(household, "eat together"))[0]
    assert line.text == "Table ~7:15p: Alex, Sam, Theo, Maya, Leo, Ivy (6)"


def test_held_plates_keep_dinner(household):
    events = [day_event("Maya's Schedule", "Alex Night", 0), day_event("Custody", "Sam", 0),
              time_event("Leo Soccer", "Practice", 0, dt.time(17), dt.time(19))]
    week = week_of(household, events)
    line = seats.table_lines(week, household, kitchen_for(household, "held plates"))[0]
    assert line.text == "Table ~6:00p: Alex, Sam, Theo, Maya, Ivy (5) · Late after 7:00p: Leo"


def test_an_away_kid_with_after_school_gets_a_snack(household):
    events = [day_event("Maya's Schedule", "Jordan Night", 0), day_event("Custody", "Chris", 0),
              time_event("Alex", "Late meeting", 0, dt.time(17), dt.time(21))]
    week = week_of(household, events)
    line = seats.table_lines(week, household, kitchen_for(household, "eat together"))[0]
    assert line.text == ("Table ~6:00p: Sam, Theo (2) · Maya: 4:15p snack, dinner at Jordan's"
                         " · Alex out until 9:00p · Leo and Ivy at Chris's")


# --- eat together: each person at the table is tested again at each moved time ----------

def night(household, *timed, practice="eat together", latest=None):
    """The table line of Monday: every kid home, with the timed events ``timed``."""
    events = [day_event("Maya's Schedule", "Alex Night", 0), day_event("Custody", "Sam", 0)]
    events += [time_event(calendar, title, 0, dt.time(*start), dt.time(*end))
               for calendar, title, start, end in timed]
    week = week_of(household, events)
    kitchen_ = kitchen_for(household, practice)
    if latest is not None:
        kitchen_.latest_dinner = latest
    return seats.table_lines(week, household, kitchen_)[0]


PRACTICE = ("Leo Soccer", "Practice", (17,), (19,))


def test_eat_together_tests_the_table_again_and_a_person_out_after_8_00p_is_not_a_plate(
        household):
    # Leo 5-7p moves dinner to 7:15p; Alex 6:30-9p covers 7:15p and ends after 8:00p.
    line = night(household, PRACTICE, ("Alex", "Coaching", (18, 30), (21,)))
    assert line.dinner == dt.time(19, 15)
    assert line.text == "Table ~7:15p: Sam, Theo, Maya, Leo, Ivy (5) · Alex out until 9:00p"
    assert line.count == 5 and line.waits == [("Leo", "7:00p")]


def test_eat_together_moves_again_for_a_person_who_is_late_at_the_moved_time(household):
    # Leo 5-7p: 7:15p; Ivy 6:45-7:30p covers 7:15p and is back by 8:00p: 7:45p.
    line = night(household, PRACTICE, ("Family", "Ivy recital", (18, 45), (19, 30)))
    assert line.dinner == dt.time(19, 45)
    assert line.text == "Table ~7:45p: Alex, Sam, Theo, Maya, Leo, Ivy (6)"
    assert line.waits == [("Leo", "7:00p"), ("Ivy", "7:30p")]


def test_eat_together_an_end_at_the_latest_dinner_time_after_a_move_is_back(household):
    line = night(household, PRACTICE, ("Family", "Sam meeting", (18, 30), (20,)))
    assert line.dinner == dt.time(20, 15)
    assert line.text == "Table ~8:15p: Alex, Sam, Theo, Maya, Leo, Ivy (6)"
    assert line.waits == [("Sam", "8:00p"), ("Leo", "7:00p")]


def test_eat_together_a_person_back_after_8_00p_at_the_moved_time_is_out(household):
    # Theo 7:00-8:30p does not cover 6:00p, but covers 7:15p and ends after 8:00p.
    line = night(household, PRACTICE, ("Family", "Theo rehearsal", (19,), (20, 30)))
    assert line.dinner == dt.time(19, 15)
    assert line.text == "Table ~7:15p: Alex, Sam, Maya, Leo, Ivy (5) · Theo out until 8:30p"
    assert line.waits == [("Leo", "7:00p")]


def test_eat_together_a_person_waited_for_and_out_at_the_final_time_is_not_waited_for(
        household):
    # Leo 5-7p: 7:15p; Ivy 6:45-7:30p: 7:45p; Leo 7:40-8:30p is out at 7:45p, which stays.
    line = night(household, PRACTICE, ("Family", "Ivy recital", (18, 45), (19, 30)),
                 ("Leo Soccer", "Scrimmage", (19, 40), (20, 30)))
    assert line.dinner == dt.time(19, 45)
    assert line.text == "Table ~7:45p: Alex, Sam, Theo, Maya, Ivy (5) · Leo out until 8:30p"
    assert line.waits == [("Ivy", "7:30p")]


def test_eat_together_reads_the_latest_dinner_time_of_the_kitchen(household):
    # With latest_dinner 7:00p, Leo back at 7:00p is waited for; Ivy back at 7:30p is out.
    line = night(household, PRACTICE, ("Family", "Ivy recital", (18, 45), (19, 30)),
                 latest=dt.time(19))
    assert line.text == "Table ~7:15p: Alex, Sam, Theo, Maya, Leo (5) · Ivy out until 7:30p"


def test_eat_together_tests_again_only_the_people_at_the_table(household):
    # Maya away on a school night (snack line), Leo and Ivy at Chris's: each keeps its part.
    events = [day_event("Maya's Schedule", "Jordan Night", 0), day_event("Custody", "Chris", 0),
              time_event("Family", "Theo practice", 0, dt.time(17), dt.time(19)),
              time_event("Family", "Maya Leo Ivy concert", 0, dt.time(18, 30), dt.time(21))]
    week = week_of(household, events)
    line = seats.table_lines(week, household, kitchen_for(household, "eat together"))[0]
    assert line.text == ("Table ~7:15p: Alex, Sam, Theo (3) · Maya: 4:15p snack, dinner at "
                         "Jordan's · Leo and Ivy at Chris's")


def test_held_plates_does_not_test_the_table_again(household):
    line = night(household, PRACTICE, ("Alex", "Coaching", (18, 30), (21,)),
                 practice="held plates")
    assert line.text == "Table ~6:00p: Alex, Sam, Theo, Maya, Ivy (5) · Late after 7:00p: Leo"

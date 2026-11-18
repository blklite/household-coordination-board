"""The mlb source: the games of 1 team from the MLB schedule API, with the postseason.

The replies here have the shape of the API (``hydrate=team``) with only the
fields that the code reads. The teams and games are made up. No test calls
the network.
"""
import datetime as dt
import json

import pytest
from conftest import ROOT

from hcb import calendars, config

FIRST, END = dt.date(2026, 9, 28), dt.date(2026, 10, 12)
TEAM = {"name": "Ball game", "source": "mlb", "team_id": 900, "required": False}
URL = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=900"
       "&startDate=2026-09-28&endDate=2026-10-11&hydrate=team")


def game(pk, kind="R", when="2026-09-29T23:10:00Z", state="Scheduled", league=104, number=None,
         tbd=False, official="2026-09-29", necessary="N", away="Comets", home="Owls"):
    found = {"gamePk": pk, "gameType": kind, "gameDate": when, "officialDate": official,
             "ifNecessary": necessary,
             "status": {"detailedState": state, "startTimeTBD": tbd},
             "teams": {"away": {"team": {"teamName": away, "league": {"id": 103}}},
                       "home": {"team": {"teamName": home, "league": {"id": league}}}}}
    if number is not None:
        found["seriesGameNumber"] = number
    return found


def read(*games, reply=None):
    """``(events, urls)`` of ``read_one`` of TEAM with a fake fetch that records each URL."""
    urls = []
    body = reply if reply is not None else json.dumps(
        {"dates": [{"games": list(games)}]}).encode("utf-8")

    def fetch(url):
        urls.append(url)
        return body
    return calendars.read_one(TEAM, {}, FIRST, END, fetch=fetch), urls


def titles(*games):
    return [e.title for e in read(*games)[0]]


def test_an_mlb_calendar_is_read_with_1_get_of_the_schedule_request_and_no_address():
    events, urls = read(game(1))
    assert urls == [URL]                   # endDate is the day before the end of the window
    assert [(e.calendar, e.uid, e.title) for e in events] == [("Ball game", "mlb-1",
                                                               "Comets @ Owls")]


def test_a_game_starts_at_its_utc_time_in_the_local_zone_and_ends_3_hours_later():
    calendars.set_timezone("America/New_York")
    (event,) = read(game(1, when="2026-09-29T23:10:00Z"))[0]
    assert event.start == dt.datetime(2026, 9, 29, 19, 10, tzinfo=calendars.TZ)
    assert event.end - event.start == dt.timedelta(hours=3)
    assert not event.all_day and event.days == (dt.date(2026, 9, 29),)


def test_a_game_with_its_start_time_tbd_is_all_day_on_its_official_date():
    (event,) = read(game(1, when="2026-10-01T04:33:00Z", tbd=True, official="2026-09-30"))[0]
    assert event.all_day and event.days == (dt.date(2026, 9, 30),)


@pytest.mark.parametrize("kind, league, number, title", [
    ("F", 104, 2, "WC 2 Comets @ Owls"), ("D", 104, 1, "NLDS 1 Comets @ Owls"),
    ("L", 103, 5, "ALCS 5 Comets @ Owls"), ("W", 103, 7, "WS 7 Comets @ Owls"),
    ("D", 999, 3, "DS 3 Comets @ Owls"), ("L", 104, None, "NLCS Comets @ Owls")])
def test_a_postseason_game_has_the_prefix_of_its_type_and_home_league(kind, league, number,
                                                                     title):
    assert titles(game(1, kind=kind, league=league, number=number)) == [title]


def test_if_necessary_y_adds_the_suffix():
    assert titles(game(1, kind="L", number=6, necessary="Y")) == [
        "NLCS 6 Comets @ Owls (if necessary)"]


@pytest.mark.parametrize("kind", ["S", "E", "A", ""])
def test_only_the_types_r_f_d_l_and_w_are_read(kind):
    assert titles(game(1, kind=kind)) == []


@pytest.mark.parametrize("state, kept", [("Postponed", False), ("Cancelled", False),
                                         ("Postponed: Rain", False), ("Final", True)])
def test_a_postponed_or_cancelled_game_is_dropped(state, kept):
    assert len(titles(game(1, state=state))) == int(kept)


def test_a_game_outside_the_window_is_left_out():
    assert titles(game(1, when="2026-10-13T23:10:00Z")) == []


@pytest.mark.parametrize("reply", [b"<html>Not Found</html>", b"\xff\xfe", b"", b"[]", b"null",
                                   b'{"dates": 3}', b'{"dates": [{"games": [{}]}]}'])
def test_a_reply_that_is_not_a_schedule_fails_with_a_fixed_reason(reply):
    with pytest.raises(calendars.CalendarError) as err:
        read(reply=reply)
    assert err.value.calendar == "Ball game" and err.value.reason == "not a schedule"


def test_an_off_season_reply_with_no_dates_is_valid():
    assert read(reply=b'{"dates": []}')[0] == []


def test_an_mlb_fetch_failure_gives_the_reason_of_the_fetch():
    def fetch(url):
        raise calendars.FetchFailed("HTTP 503", 503)
    with pytest.raises(calendars.CalendarError) as err:
        calendars.read_one(TEAM, {}, FIRST, END, fetch=fetch)
    assert err.value.reason == "HTTP 503"


# --- household.toml -----------------------------------------------------------------------

MLB_TOML = """
[[adults]]
name = "A"
[[calendars]]
name = "Ball game"
source = "mlb"
team_id = {team_id}
"""


def test_the_calendars_table_takes_an_mlb_source_with_a_team_id(tmp_path):
    path = tmp_path / "household.toml"
    path.write_text(MLB_TOML.format(team_id=900), encoding="utf-8")
    (entry,) = config.load(path).calendars
    assert (entry["source"], entry["team_id"]) == ("mlb", 900)


@pytest.mark.parametrize("team_id", ['"900"', "12345", "-1", "true"])
def test_a_team_id_that_is_not_1_to_4_digits_is_an_error(tmp_path, team_id):
    path = tmp_path / "household.toml"
    path.write_text(MLB_TOML.format(team_id=team_id), encoding="utf-8")
    with pytest.raises(config.ConfigError) as err:
        config.load(path)
    assert "calendar Ball game: team_id is not an MLB team number (1 to 4 digits)" in \
        err.value.errors


def test_an_unknown_source_names_mlb(tmp_path):
    path = tmp_path / "household.toml"
    path.write_text('[[adults]]\nname = "A"\n[[calendars]]\nname = "X"\nsource = "web"\n',
                    encoding="utf-8")
    with pytest.raises(config.ConfigError) as err:
        config.load(path)
    assert "calendar X: source is not ical, gcal or mlb" in err.value.errors


def test_the_example_shows_the_mlb_source_and_it_loads(tmp_path):
    text = (ROOT / "household.example.toml").read_text(encoding="utf-8")
    block = text[text.index("# [[calendars]]\n# name = \"Ball game\""):]
    block = block[:block.index("\n\n")]
    assert 'source = "mlb"' in block and "team_id = " in block
    path = tmp_path / "household.toml"
    path.write_text(text + "\n" + "\n".join(line[2:] for line in block.splitlines()) + "\n",
                    encoding="utf-8")
    entry = config.load(path).calendars[-1]
    assert entry["source"] == "mlb" and isinstance(entry["team_id"], int)

"""Read the household calendars.

1 entry point, ``read_all(calendars, urls, window, fetch, google)``: it reads
each calendar of the configuration and returns 1 list of ``Event`` for the
whole household, with an event that is on 2 calendars kept once. A calendar
with ``"source": "gcal"`` is read through the Google Calendar API by
``google`` (a ``gcal.Reader``); one with ``"source": "ical"`` from its private
iCal address, here: the reply must be a calendar, and the recurring events
of the window are expanded. Both sources make each ``Event`` with
``make_event``, so nothing after the fetch knows the source.

The rules of the iCal source, each with a test in tests/test_calendars.py:

- The window is local midnight to local midnight, in the household's timezone.
- An all-day event covers each day from its start date up to its end date,
  which is exclusive. An all-day event with no end covers 1 day.
- A timed event shows on the local day it starts, also when it runs past
  midnight. A UTC time is converted to the local zone first.
- A floating time (no zone) is local time. ``X-WR-TIMEZONE`` is ignored for
  it, because recurring-ical-events would otherwise read a floating time in
  that zone (UTC on some team feeds).
- Recurring events: RRULE, EXDATE and RECURRENCE-ID through
  recurring-ical-events; an instance with STATUS:CANCELLED is dropped.
- The same event on 2 or more calendars (same UID and instance, or same
  title, start and end) is kept once: the first copy that is a custody event
  on its own calendar (``prefer``), else the copy from the calendar listed
  first.
- Each iCal request names the program: ``User-Agent: household-coordination-board``.
  Some school feeds answer HTTP 403 to Python's default agent name.

A calendar with ``source = "mlb"`` holds the games of 1 MLB team
(``team_id``) from the public MLB schedule API, with no key and no address in
the env file: ``mlb_events`` gives its rules.

The address of a calendar is a secret. It is never logged, printed or put in
an exception: a failed calendar raises ``CalendarError`` with the calendar's
name and a fixed reason ("HTTP 404", "timeout", "not a calendar", ...), and
never the text of the underlying exception, which can carry the address.
urllib puts the address into the text of a ``ValueError`` (no ``https://``)
and of ``http.client.InvalidURL`` (a control character in it).

The iCal libraries are imported here, but a missing one does not stop the
import: ``MISSING_LIBRARY`` names it, and the job fails at its step
``config`` with the normal alert.
"""
import datetime as dt
import http.client
import itertools
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from zoneinfo import ZoneInfo

try:
    import icalendar
    import recurring_ical_events
except ImportError as _err:
    icalendar = recurring_ical_events = None
    MISSING_LIBRARY = _err.name or "icalendar"
else:
    MISSING_LIBRARY = ""

TZ = ZoneInfo("UTC")     # set_timezone() sets the household's zone
TIMEOUT_SECONDS = 30
GRACE_SECONDS = 1       # fetch waits this long past the timeout for the worker's own reason
CONNECT_SECONDS = 5     # the least share of a connect try that is not the last (see connect)
MAX_BYTES = 20 * 1024 * 1024
CHUNK = 64 * 1024
USER_AGENT = "household-coordination-board/0.2"     # some feeds refuse Python's own name
MLB_SCHEDULE = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team}"
                "&startDate={first}&endDate={last}&hydrate=team")
# The prefix of a postseason game, by gameType; {} is AL or NL, from the home team's league.
# R (the regular season) has none; a type that is not here (S spring training, ...) is left out.
MLB_PREFIX = {"R": "", "F": "WC", "D": "{}DS", "L": "{}CS", "W": "WS"}
MLB_LEAGUE = {103: "AL", 104: "NL"}
GAME_HOURS = 3


def set_timezone(name):
    """Use the zone ``name`` (such as Europe/Paris) for every local date and time."""
    global TZ
    TZ = ZoneInfo(name)


class CalendarError(Exception):
    """A calendar gave no valid reply. ``str()`` is safe to print and send."""

    def __init__(self, calendar, reason):
        super().__init__(f"{calendar}: {reason}")
        self.calendar = calendar
        self.reason = reason


class SpentDeadline(TimeoutError):
    """The deadline of ``connect`` was spent with ``left`` of its ``total`` addresses untried."""

    def __init__(self, left, total):
        super().__init__(f"timed out: {left} of {total} addresses got no try")
        self.left, self.total = left, total


class FetchFailed(Exception):
    """A fetch failed for a fixed reason that is safe to show (no address in it).

    ``status`` is the HTTP status of a reply that was not 200, else None.
    """

    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.status = status


@dataclass(frozen=True)
class Event:
    calendar: str
    uid: str
    title: str
    description: str
    location: str
    all_day: bool
    start: object          # aware local datetime, or a date for an all-day event
    end: object            # aware local datetime, or the exclusive end date
    days: tuple            # the local dates of the window the event shows on


def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """``socket.create_connection`` with a limit for each try and the families in turn.

    The tries alternate between the 2 address families, from the family of
    the first address of ``getaddrinfo``; inside a family its order stays.
    Each try but the last has a fair share of the time left of ``timeout``:
    the time left divided by the number of tries left, so an address that
    fails at once leaves its time to the next ones. It gets at least
    ``CONNECT_SECONDS`` while that much is left, never more than the time
    left; the last try has all the time left. With no ``timeout`` each try
    but the last has ``CONNECT_SECONDS`` and the last no limit. A deadline
    spent before a try (the tries before it used the time; a ``timeout`` of 0
    or less gives no try at all) raises ``SpentDeadline(left, total)``, a
    ``TimeoutError`` with the text ``timed out: <left> of <total> addresses
    got no try``, with ``left`` this try and the ones after it; when every
    try fails, the error of the last one is raised. The socket that connects
    gets ``timeout`` for each read.
    """
    if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout = socket.getdefaulttimeout()
    deadline = None if timeout is None else time.monotonic() + timeout
    infos = socket.getaddrinfo(*address, 0, socket.SOCK_STREAM)
    if not infos:
        raise OSError("getaddrinfo returns an empty list")
    first = [i for i in infos if i[0] == infos[0][0]]
    other = [i for i in infos if i[0] != infos[0][0]]
    tries = [i for pair in itertools.zip_longest(first, other) for i in pair if i]
    for n, (family, kind, proto, _, sockaddr) in enumerate(tries, 1):
        last = n == len(tries)
        if deadline is None:
            limit = None if last else CONNECT_SECONDS
        else:
            left = deadline - time.monotonic()
            if left <= 0:
                # settimeout(0) would not wait at all
                raise SpentDeadline(len(tries) - n + 1, len(tries))
            # 1 rule for each try: the share, at least CONNECT_SECONDS, at most the time left;
            # the last try has 1 try left, so its share is all the time left
            limit = min(left, max(left / (len(tries) - n + 1), CONNECT_SECONDS))
        sock = None
        try:
            sock = socket.socket(family, kind, proto)   # fails when the host lacks the family
            sock.settimeout(limit)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            sock.settimeout(timeout)
            return sock
        except BaseException as err:
            if sock is not None:
                sock.close()
            if last or not isinstance(err, OSError):
                raise


class _Connect:
    """An ``http.client`` connection that connects with ``connect``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect       # the hook that http.client keeps for it


class _HTTPConnection(_Connect, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_Connect, http.client.HTTPSConnection):
    pass


class HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class HTTPSHandler(urllib.request.HTTPSHandler):
    """The stock handler with ``connect``; the TLS context and its checks are urllib's."""

    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


OPENER = urllib.request.build_opener(HTTPHandler, HTTPSHandler)


def fetch(url, timeout=TIMEOUT_SECONDS, opener=OPENER.open, clock=time.monotonic):
    """The body of ``url``. Raises ``FetchFailed`` with a safe reason.

    The ``timeout`` (30 s by default) is for the whole request: the name
    lookup, the connect and every read. A socket timeout bounds only 1 read,
    so a body that trickles in (1 byte a second) never trips it. The request
    therefore runs in a worker thread, and ``fetch`` waits for it ``timeout``
    plus a grace of ``GRACE_SECONDS`` (1 s), so the hard limit is ``timeout``
    + 1 s: a worker that ends in that time gives its own reason, one still
    alive gives ``no reply in <n> s``. The worker, a daemon, ends at its next
    socket timeout or with the process. A ``timeout`` that is not an ``int``
    or a ``float`` gives ``fetch failed (TypeError)`` before any request.

    A connect whose deadline was spent (``SpentDeadline``) gives ``no reply
    in <n> s (<left> of <total> addresses got no try)``, built from its 2
    numbers, never from an exception's text; any other timeout gives ``no
    reply in <n> s``.

    The default ``opener`` connects with ``connect``: when IPv6 is dead past
    the router and ``getaddrinfo`` gives an IPv6 address first, a plain
    connect would spend the whole limit on it, and IPv4 would never be
    tried. So the tries alternate between the IPv6 and IPv4 addresses, from
    the family of the first address, and each try but the last has a fair
    share of the time left (the time left divided by the number of tries
    left, at least ``CONNECT_SECONDS`` and at most the time left), so 1 lost
    packet does not fail a try; the last try has all the time left. After
    the connect, each read has ``timeout``.

    An iCal address (a string) is sent with the header ``User-Agent:
    household-coordination-board``. A prepared request, the Google
    path of ``gcal.fetch``, is sent as it is.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise FetchFailed("fetch failed (TypeError)")
    outcome = {}

    def work():
        try:
            outcome["body"] = _fetch(url, timeout, opener, clock)
        except FetchFailed as err:
            outcome["error"] = err
        except Exception as err:  # noqa: BLE001 - the text may hold the address
            outcome["error"] = FetchFailed(f"fetch failed ({type(err).__name__})")

    worker = threading.Thread(target=work, name="calendar-fetch", daemon=True)
    worker.start()
    worker.join(timeout + GRACE_SECONDS)
    if worker.is_alive():
        raise FetchFailed(f"no reply in {timeout} s")
    if "error" in outcome:
        # A fresh exception: no chain back to the worker's exceptions.
        raise FetchFailed(str(outcome["error"]), outcome["error"].status) from None
    return outcome["body"]


def _fetch(url, timeout, opener, clock):
    """``fetch`` in the worker thread; the deadline is also checked between reads."""
    deadline = clock() + timeout
    try:
        # Built inside the try: urllib puts a malformed address into its ValueError.
        request = (urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                   if isinstance(url, str) else url)
        with opener(request, timeout=timeout) as reply:
            status = getattr(reply, "status", 200)
            if status != 200:
                raise FetchFailed(f"HTTP {status}", status)
            chunks, size = [], 0
            while True:
                if clock() > deadline:
                    raise FetchFailed(f"no reply in {timeout} s")
                chunk = reply.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchFailed("reply too large")
                chunks.append(chunk)
            return b"".join(chunks)
    except FetchFailed:
        raise
    except urllib.error.HTTPError as err:
        raise FetchFailed(f"HTTP {err.code}", err.code) from None
    except urllib.error.URLError as err:
        # urllib wraps a connect timeout in a URLError
        reason = (_no_reply(err.reason, timeout) if isinstance(err.reason, TimeoutError)
                  else "fetch failed (URLError)")
        raise FetchFailed(reason) from None
    except (socket.timeout, TimeoutError) as err:
        raise FetchFailed(_no_reply(err, timeout)) from None
    except Exception as err:  # noqa: BLE001 - the text may hold the address
        raise FetchFailed(f"fetch failed ({type(err).__name__})") from None


def _no_reply(err, timeout):
    """The reason of a timeout: the count from the 2 numbers of ``SpentDeadline``, never a text."""
    if isinstance(err, SpentDeadline):
        return f"no reply in {timeout} s ({err.left} of {err.total} addresses got no try)"
    return f"no reply in {timeout} s"


def parse(body):
    """``body`` as an icalendar VCALENDAR. Raises ValueError when it is not one."""
    try:
        cal = icalendar.Calendar.from_ical(body)
    except Exception:  # noqa: BLE001 - any parse fault means "not a calendar"
        raise ValueError("not a calendar") from None
    if getattr(cal, "name", "") != "VCALENDAR":
        raise ValueError("not a calendar")
    return cal


def _local(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)      # a floating time is local
    return value.astimezone(TZ)


def _text(component, key):
    value = component.get(key)
    return str(value) if value is not None else ""


def make_event(calendar, uid, title, description, location, start, end, first_day, end_day):
    """The ``Event`` of 1 instance, or None when it shows on no day of ``[first_day, end_day)``.

    Both sources (iCal here, the Google API in gcal.py) make their events
    with it, so an event is the same whatever its source: an all-day event
    (``start`` a date) covers its days up to the exclusive ``end``; a timed
    event is converted to the local zone and shows on the day it starts.
    """
    all_day = not isinstance(start, dt.datetime)
    if all_day:
        if isinstance(end, dt.datetime):
            end = end.date()
        if end is None or end <= start:
            end = start + dt.timedelta(days=1)
        days = []
        day = max(start, first_day)
        while day < end and day < end_day:
            days.append(day)
            day += dt.timedelta(days=1)
        if not days:
            return None
    else:
        start = _local(start)
        end = _local(end) if isinstance(end, dt.datetime) else start
        if not first_day <= start.date() < end_day:
            return None
        days = [start.date()]
    return Event(calendar=calendar, uid=uid, title=title, description=description,
                 location=location, all_day=all_day, start=start, end=end, days=tuple(days))


def events_in(cal, calendar, first_day, end_day):
    """The events of ``cal`` that show on a day in ``[first_day, end_day)``."""
    cal.pop("X-WR-TIMEZONE", None)            # floating times stay local
    lo = dt.datetime.combine(first_day - dt.timedelta(days=1), dt.time(), TZ)
    hi = dt.datetime.combine(end_day + dt.timedelta(days=1), dt.time(), TZ)
    found = []
    for comp in recurring_ical_events.of(cal).between(lo, hi):
        if _text(comp, "STATUS").upper() == "CANCELLED":
            continue
        start = comp.get("DTSTART")
        if start is None:
            continue
        start = start.dt
        end = comp.get("DTEND")
        end = end.dt if end is not None else None
        duration = comp.get("DURATION")
        if end is None and duration is not None:
            end = start + duration.dt
        recurrence = comp.get("RECURRENCE-ID")
        uid = _text(comp, "UID")
        if recurrence is not None:
            uid = f"{uid}@{recurrence.dt}"
        else:
            uid = f"{uid}@{_local(start) if isinstance(start, dt.datetime) else start}"
        event = make_event(calendar, uid, " ".join(_text(comp, "SUMMARY").split()),
                           _text(comp, "DESCRIPTION"), _text(comp, "LOCATION").strip(),
                           start, end, first_day, end_day)
        if event is not None:
            found.append(event)
    return found


def _same_key(event):
    return (event.title.casefold(), event.all_day, str(event.start), str(event.end))


def dedupe(events, prefer=None):
    """Keep 1 copy of each event that is on more than 1 calendar.

    The copies of an event match by UID or by title, start and end. The kept
    copy is the first copy for which ``prefer(event)`` is true (a custody
    event on its own calendar, so that its label is read), else the first
    copy; it stays at the place of the first copy.
    """
    by_uid, by_key, kept, chosen = {}, {}, [], []
    for event in events:
        key = _same_key(event)
        at = by_uid.get(event.uid, by_key.get(key))
        if at is None:
            at = len(kept)
            kept.append(event)
            chosen.append(bool(prefer and prefer(event)))
        elif not chosen[at] and prefer and prefer(event):
            kept[at], chosen[at] = event, True
        else:
            continue
        by_uid.setdefault(event.uid, at)
        by_key.setdefault(key, at)
    return kept


def https_address(address):
    """The address to fetch for an ``ical`` calendar, or None when its scheme is refused.

    ``https://`` stays; ``webcal://`` (as a team site gives a feed) is read as
    ``https://`` with the same host and path; any other scheme is refused.
    """
    scheme, sep, rest = address.partition("://")
    if sep and scheme.lower() == "https":
        return address
    if sep and scheme.lower() == "webcal":
        return f"https://{rest}"
    return None


def mlb_address(team_id, first_day, end_day):
    """The MLB schedule request of ``team_id`` for ``[first_day, end_day)``; its dates are
    inclusive, so endDate is the day before ``end_day``."""
    return MLB_SCHEDULE.format(team=team_id, first=first_day,
                               last=end_day - dt.timedelta(days=1))


def mlb_events(reply, calendar, first_day, end_day):
    """The events of the MLB schedule ``reply`` (parsed JSON) that show in the window.

    1 event for each game of type R, F, D, L or W, except a game whose
    ``status.detailedState`` starts with Postponed or Cancelled (the API also
    lists a postponed game on its new date, with the same ``gamePk``). The title
    is ``<away> @ <home>``; a postseason game starts with its prefix and its
    ``seriesGameNumber`` (``NLCS 5``) and ends with `` (if necessary)`` when
    ``ifNecessary`` is Y. The start is ``gameDate``, the end 3 hours later;
    with ``status.startTimeTBD`` the game is all-day on ``officialDate``. The
    uid is ``mlb-<gamePk>``. Raises ValueError, KeyError or TypeError for a
    reply that is not a schedule.
    """
    dates = reply["dates"]
    if not isinstance(dates, list):
        raise TypeError("not a schedule")
    found = []
    for day in dates:
        for game in day["games"]:
            prefix = MLB_PREFIX.get(game["gameType"])
            state = game["status"]["detailedState"]
            if prefix is None or state.startswith(("Postponed", "Cancelled")):
                continue
            home = game["teams"]["home"]["team"]
            title = f"{game['teams']['away']['team']['teamName']} @ {home['teamName']}"
            if prefix:
                # A league that is not 103 or 104, or no number: the prefix without it.
                league = MLB_LEAGUE.get((home.get("league") or {}).get("id"), "")
                number = str(game.get("seriesGameNumber") or "")
                title = " ".join(filter(None, (prefix.format(league), number, title)))
            if game.get("ifNecessary") == "Y":
                title += " (if necessary)"
            if game["status"].get("startTimeTBD"):
                start = dt.date.fromisoformat(game["officialDate"])
                end = None
            else:
                start = dt.datetime.fromisoformat(game["gameDate"].replace("Z", "+00:00"))
                end = start + dt.timedelta(hours=GAME_HOURS)
            event = make_event(calendar, f"mlb-{game['gamePk']}", title, "", "", start, end,
                               first_day, end_day)
            if event is not None:
                found.append(event)
    return found


def read_one(entry, urls, first_day, end_day, fetch=fetch, google=None):
    """The events of 1 calendar of the configuration in ``[first_day, end_day)``.

    ``entry`` is the config entry: ``source`` "gcal" with ``calendar_id``,
    "mlb" with ``team_id``, or "ical" (the default) with ``env``; ``urls``
    maps an ``env`` key to its address; ``google`` reads the gcal calendars.
    Raises ``CalendarError`` when the calendar gives no valid reply. A
    calendar with no events is a valid reply.
    """
    name = entry["name"]
    if entry.get("source", "ical") == "gcal":
        if google is None:
            raise CalendarError(name, "no Google service account")
        return google.events(entry["calendar_id"], name, first_day, end_day)
    mlb = entry.get("source") == "mlb"
    try:
        body = fetch(mlb_address(entry["team_id"], first_day, end_day) if mlb
                     else urls[entry["env"]])
    except FetchFailed as err:
        raise CalendarError(name, str(err)) from None
    except Exception as err:  # noqa: BLE001 - never the text, it may hold the address
        raise CalendarError(name, f"fetch failed ({type(err).__name__})") from None
    if mlb:
        try:
            return mlb_events(json.loads(body), name, first_day, end_day)
        except Exception:  # noqa: BLE001 - any fault of the reply means "not a schedule"
            raise CalendarError(name, "not a schedule") from None
    try:
        cal = parse(body)
        return events_in(cal, name, first_day, end_day)
    except ValueError:
        raise CalendarError(name, "not a calendar") from None
    except Exception as err:  # noqa: BLE001
        raise CalendarError(name, f"unreadable calendar ({type(err).__name__})") from None


def required(entry):
    """True for a calendar that the run needs (``"required": true``); else it is optional."""
    return entry.get("required") is True


def reason_for(err, name):
    """The fixed reason of a ``CalendarError`` for the line of calendar ``name``."""
    return err.reason if err.calendar == name else str(err)


def read_all(calendars, urls, first_day, end_day, fetch=fetch, google=None, missing=None,
             prefer=None):
    """All events of the window, from each calendar in config order (``read_one``).

    With ``missing`` None, every calendar must be read: the first that gives
    no valid reply raises ``CalendarError``. With ``missing`` a list, only a
    required calendar raises; an optional one that gives no valid reply is
    left out, and ``(name, fixed reason)`` is appended to ``missing``.
    ``prefer`` picks the copy that ``dedupe`` keeps of an event on 2 calendars.
    """
    events = []
    for entry in calendars:
        try:
            events.extend(read_one(entry, urls, first_day, end_day, fetch=fetch, google=google))
        except CalendarError as err:
            if missing is None or required(entry):
                raise
            missing.append((entry["name"], reason_for(err, entry["name"])))
    return dedupe(events, prefer)

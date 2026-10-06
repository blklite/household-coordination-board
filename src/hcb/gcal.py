"""Read a Google calendar through the Calendar API, as a service account.

The jobs read the calendars with ``source = "gcal"`` in household.toml
here, and the others (``source = "ical"``) through calendars.py. The rules,
each with a test in tests/test_gcal.py:

- The key file is a service account key (JSON). It must not be readable by
  group or others, the same rule as the env file; any fault with it is a
  ``KeyFileError`` (the job's step ``config``) with a fixed reason.
- Sign-in: a JWT (RS256), signed with the account's private key, for the
  read-only scope ``SCOPE`` only, traded at ``TOKEN_URI`` for 1 access token
  per run (the OAuth 2.0 JWT bearer grant). The token URI is fixed here, not
  read from the key file, so a key file can not send the assertion
  elsewhere. Signing uses ``cryptography`` (pip install ".[google]").
- ``events.list`` with ``singleEvents=true``, ``timeMin`` and ``timeMax``
  the window (local midnight to local midnight), every page.
- Each API event becomes the ``calendars.Event`` that the iCal reader gives
  (``calendars.make_event``): ``start.date``/``end.date`` (exclusive end) for
  an all-day event, ``start.dateTime`` in its zone converted to
  the local zone for a timed one, the event id as the UID. A cancelled
  instance is dropped. Nothing after the fetch knows the source.
- Every request goes through ``fetch``: ``calendars.fetch`` (1 hard
  deadline each) with an opener that refuses every redirect, because urllib
  would send the ``Authorization`` header on to the new host. A redirect is
  a failed fetch with a fixed reason.
- Only events of the type ``default``: the request asks for
  ``eventTypes=default``, and the mapping also drops an item whose
  ``eventType`` is another (birthday, working location, out of office,
  focus time, from Gmail), so the filter does not depend on the server.
  An item with no summary is dropped too.
- A calendar that the account sees as ``freeBusyReader`` (shared as
  free/busy only) is not readable, with the fixed reason ``FREE_BUSY``.

The key file's text, the private key, the signed assertion and the access
token are credentials. None of them reaches a log line, a message, the cost
log, the page, the model step or an exception text: a failure raises
``calendars.CalendarError`` with a fixed reason, never the text of an
exception or of a reply, and is raised outside the ``except`` block, so it
carries no chained exception either.
"""
import base64
import datetime as dt
import json
import os
import stat
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import calendars

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError as _err:
    hashes = serialization = padding = rsa = None
    MISSING_LIBRARY = (_err.name or "cryptography").split(".")[0]    # the package to install
else:
    MISSING_LIBRARY = ""

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
TOKEN_SECONDS = 3600
MAX_RESULTS = 2500
MAX_PAGES = 20
SIGN_IN = "Google sign-in"
NO_ACCESS = "no access: is the calendar shared with the service account?"
FREE_BUSY = 'shared as free/busy only: share it with "See all event details"'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect: urllib then raises ``HTTPError`` with the 3xx status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(request, timeout=calendars.TIMEOUT_SECONDS):
    """``calendars.fetch`` (the hard deadline) through an opener that refuses redirects."""
    opener = urllib.request.build_opener(_NoRedirect())
    return calendars.fetch(request, timeout=timeout, opener=opener.open)


class KeyFileError(Exception):
    """The key file is missing, too open, unreadable or malformed. ``str()`` is safe."""


@dataclass(frozen=True)
class Account:
    """A service account. Its fields are kept out of ``repr``."""
    email: str = field(repr=False)
    key: object = field(repr=False)
    key_id: str = field(repr=False)


def load_account(path):
    """The ``Account`` of the key file at ``path``. Raises ``KeyFileError``."""
    path = Path(path)
    problem, data, account = None, None, None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        problem = f"no key file at {path}"
    except OSError as err:
        problem = f"key file {path} unreadable ({type(err).__name__})"
    else:
        if os.name == "posix" and mode & 0o077:
            problem = f"key file {path} is mode {mode:o}, not 600"
    if problem is None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as err:
            problem = f"key file {path} unreadable ({type(err).__name__})"
        except ValueError:
            problem = f"key file {path} is not JSON"
    if problem is None:
        problem, account = _account(data, path)
    if problem is not None:
        raise KeyFileError(problem)
    return account


def _account(data, path):
    if not isinstance(data, dict) or data.get("type") != "service_account":
        return f"key file {path} is not a service account key", None
    email, pem = data.get("client_email"), data.get("private_key")
    if not (isinstance(email, str) and email and isinstance(pem, str) and pem):
        return f"key file {path} lacks client_email or private_key", None
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception:  # noqa: BLE001 - any fault means "does not load"; never its text
        key = None
    if not isinstance(key, rsa.RSAPrivateKey):
        return f"key file {path}: the private key does not load", None
    key_id = data.get("private_key_id")
    return None, Account(email, key, key_id if isinstance(key_id, str) else "")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def assertion(account, now):
    """The signed JWT that asks for an access token of ``SCOPE``."""
    header = {"alg": "RS256", "typ": "JWT"}
    if account.key_id:
        header["kid"] = account.key_id
    issued = int(now)
    claims = {"iss": account.email, "scope": SCOPE, "aud": TOKEN_URI,
              "iat": issued, "exp": issued + TOKEN_SECONDS}
    signing_input = ".".join(_b64(json.dumps(part, separators=(",", ":")).encode("utf-8"))
                             for part in (header, claims))
    signature = account.key.sign(signing_input.encode("ascii"), padding.PKCS1v15(),
                                 hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def _local_midnight(day):
    return dt.datetime.combine(day, dt.time(), calendars.TZ).isoformat()


def _when(value):
    """A date (all-day) or an aware datetime of an API ``start``/``end``."""
    if not isinstance(value, dict):
        raise ValueError("no start or end")
    if isinstance(value.get("date"), str):
        return dt.date.fromisoformat(value["date"])
    if isinstance(value.get("dateTime"), str):
        return dt.datetime.fromisoformat(value["dateTime"])   # RFC 3339: with its offset
    raise ValueError("no date or dateTime")


def to_event(item, calendar, first_day, end_day):
    """The ``calendars.Event`` of 1 API event, or None.

    None for a cancelled instance, an item of another type than ``default``,
    an item with no summary, or one outside the window. Raises ValueError
    when the item is not in the shape of the API.
    """
    if not isinstance(item, dict):
        raise ValueError("an item is not an object")
    if item.get("status") == "cancelled":
        return None
    if item.get("eventType", "default") != "default":
        return None
    summary = item.get("summary")
    if not (isinstance(summary, str) and summary.strip()):
        return None
    start, end = _when(item.get("start")), _when(item.get("end"))

    def text(key):
        value = item.get(key)
        return value if isinstance(value, str) else ""
    return calendars.make_event(calendar, text("id"), " ".join(text("summary").split()),
                                text("description"), text("location").strip(),
                                start, end, first_day, end_day)


class Reader:
    """Reads the ``gcal`` calendars of 1 run with 1 access token."""

    def __init__(self, account, fetch=fetch, now=time.time):
        self.account, self._fetch, self._now = account, fetch, now
        self._token = None
        self._sign_in_failed = None

    def _request(self, request):
        """``(body, None)`` or ``(None, (status, fixed reason))``; never an exception's text."""
        try:
            return self._fetch(request), None
        except calendars.FetchFailed as err:   # its text is a fixed reason of calendars.fetch
            if err.status is not None and 300 <= err.status < 400:
                return None, (err.status, f"redirect refused, HTTP {err.status}")
            return None, (err.status, str(err))
        except Exception as err:  # noqa: BLE001 - the text may hold a credential
            return None, (None, f"fetch failed ({type(err).__name__})")

    def token(self):
        """The access token of this run. Raises ``CalendarError`` named ``SIGN_IN``."""
        if self._sign_in_failed is None and self._token is None:
            body = urllib.parse.urlencode({"grant_type": GRANT,
                                           "assertion": assertion(self.account, self._now())})
            request = urllib.request.Request(
                TOKEN_URI, data=body.encode("ascii"), method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            reply, failure = self._request(request)
            if failure:
                self._sign_in_failed = f"token request failed ({failure[1]})"
            else:
                token = (_json(reply) or {}).get("access_token")
                if isinstance(token, str) and token:
                    self._token = token
                else:
                    self._sign_in_failed = "the token reply holds no access token"
        if self._sign_in_failed is not None:
            raise calendars.CalendarError(SIGN_IN, self._sign_in_failed)
        return self._token

    def events(self, calendar_id, name, first_day, end_day):
        """The events of 1 calendar in ``[first_day, end_day)``. Raises ``CalendarError``."""
        token = self.token()
        query = {"singleEvents": "true", "eventTypes": "default",
                 "timeMin": _local_midnight(first_day),
                 "timeMax": _local_midnight(end_day), "maxResults": str(MAX_RESULTS)}
        base = f"{API}/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"
        items, page_token, reason = [], None, None
        for _ in range(MAX_PAGES):
            page_query = {**query, "pageToken": page_token} if page_token else query
            request = urllib.request.Request(f"{base}?{urllib.parse.urlencode(page_query)}",
                                             headers={"Authorization": f"Bearer {token}"})
            reply, failure = self._request(request)
            if failure:
                status, text = failure
                reason = (NO_ACCESS if status in (403, 404)
                          else "not signed in (HTTP 401)" if status == 401 else text)
                break
            page = _json(reply)
            if (not page or page.get("kind") != "calendar#events"
                    or not isinstance(page.get("items", []), list)):
                reason = "the reply is not an event list"
                break
            if page.get("accessRole") == "freeBusyReader":
                reason = FREE_BUSY
                break
            items.extend(page.get("items", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        else:
            reason = f"more than {MAX_PAGES} pages"
        if reason is None:
            try:
                found = [to_event(item, name, first_day, end_day) for item in items]
            except (ValueError, TypeError):
                reason = "the reply holds an event that is not in the shape of the API"
        if reason is not None:
            raise calendars.CalendarError(name, reason)
        return [event for event in found if event is not None]


def _json(body):
    """The JSON object of a reply body, or None."""
    try:
        value = json.loads(body)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None

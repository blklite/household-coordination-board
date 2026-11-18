"""The calendar fetch: the connect of each address in turn, the deadline, and its reasons.

No test reads the network: ``FakeNet`` gives a made-up address list (the
documentation ranges 2001:db8::/32 and 192.0.2.0/24) and a fake clock, and a
live address is a local server on 127.0.0.1.
"""
import contextlib
import datetime as dt
import errno
import http.server
import socket
import ssl
import threading
import time
import types
import urllib.error

import pytest

from hcb import calendars, gcal

V6, V4 = socket.AF_INET6, socket.AF_INET
MARKER = "secret-marker"


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    """No request of a test goes through a proxy of the environment."""
    monkeypatch.setenv("no_proxy", "*")


def address(family, host, port=80):
    """1 entry of ``getaddrinfo`` for ``host``."""
    sockaddr = (host, port, 0, 0) if family == V6 else (host, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def v6(n, port=80):
    return address(V6, f"2001:db8::{n}", port)


def v4(n, port=80):
    return address(V4, f"192.0.2.{n}", port)


def local(port):
    return address(V4, "127.0.0.1", port)


class FakeNet:
    """The ``socket`` and ``time`` names of ``calendars.connect``, patched on ``calendars`` only.

    ``getaddrinfo`` gives ``addresses``. A socket of the family ``live`` is a
    real one. Any other socket is dead: its connect raises ``error`` after the
    clock has moved on by the limit of the try, as a real timeout would, or by
    ``took[host]`` seconds (0: a connect that fails at once). ``tries`` holds
    ``(host, limit)`` of each dead connect. The clock has no real time in it,
    so each limit is exact.
    """

    def __init__(self, monkeypatch, addresses, live=V4, error=TimeoutError, took=None):
        self.addresses, self.live, self.error, self.took = addresses, live, error, took or {}
        self.tries, self.dead, self.waited = [], [], 0.0
        fake = types.SimpleNamespace(**vars(socket))
        fake.getaddrinfo, fake.socket = self.getaddrinfo, self.socket
        monkeypatch.setattr(calendars, "socket", fake)
        monkeypatch.setattr(calendars, "time", types.SimpleNamespace(monotonic=self.monotonic))

    def getaddrinfo(self, host, port, family=0, kind=0, proto=0, flags=0):
        return list(self.addresses)

    def monotonic(self):
        return 1000.0 + self.waited

    def socket(self, family, kind, proto):
        if family == self.live:
            return socket.socket(family, kind, proto)
        self.dead.append(DeadSocket(self))
        return self.dead[-1]


class DeadSocket:
    def __init__(self, net):
        self.net, self.limit, self.closed = net, None, False

    def settimeout(self, limit):
        self.limit = limit

    def connect(self, sockaddr):
        self.net.tries.append((sockaddr[0], self.limit))
        self.net.waited += self.net.took.get(sockaddr[0], self.limit or 0)
        raise self.net.error(f"connect to {sockaddr[0]} failed {MARKER}")

    def close(self):
        self.closed = True


@contextlib.contextmanager
def serve(body):
    """A local HTTP server on 127.0.0.1 that answers each GET with ``body``; gives its port."""
    class Reply(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the http.server name
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Reply)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def connect_tries(monkeypatch, addresses, timeout=30, took=None):
    """``(host, limit)`` of each try of ``calendars.connect`` when every address is dead."""
    net = FakeNet(monkeypatch, addresses, live=None, took=took)
    with pytest.raises(TimeoutError):
        calendars.connect(("calendar.invalid", 80), timeout)
    assert all(sock.closed for sock in net.dead)
    return net.tries


# --- IPv4 when IPv6 is dead ----------------------------------------------------------------

def test_a_dead_first_address_does_not_use_the_whole_limit(monkeypatch):
    with serve(b"the body") as port:
        net = FakeNet(monkeypatch, [v6(1, port), local(port)])
        body = calendars.fetch(f"http://calendar.invalid:{port}/basic.ics")
    assert body == b"the body"
    assert net.tries == [("2001:db8::1", 15)] and net.dead[0].closed
    assert net.waited == 15


def test_an_ical_calendar_with_a_dead_first_address_is_read(monkeypatch):
    party = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\nBEGIN:VEVENT\r\nUID:p\r\n"
             b"DTSTART;VALUE=DATE:20261013\r\nSUMMARY:Party\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    with serve(party) as port:
        FakeNet(monkeypatch, [v6(1, port), local(port)])
        found = calendars.read_one({"name": "Family", "env": "F"},
                                   {"F": f"http://calendar.invalid:{port}/basic.ics"},
                                   dt.date(2026, 10, 12), dt.date(2026, 10, 26))
    assert [e.title for e in found] == ["Party"]


@pytest.mark.parametrize("addresses, order", [
    ([v6(1), v6(2), v6(3), v6(4), v4(1)],
     ["2001:db8::1", "192.0.2.1", "2001:db8::2", "2001:db8::3", "2001:db8::4"]),
    ([v4(1), v4(2), v6(1)], ["192.0.2.1", "2001:db8::1", "192.0.2.2"]),
])
def test_the_tries_alternate_between_the_families_from_the_first(monkeypatch, addresses, order):
    assert [host for host, _ in connect_tries(monkeypatch, addresses)] == order


def test_a_family_that_the_host_lacks_is_skipped_for_the_next(monkeypatch):
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        net = FakeNet(monkeypatch, [v6(1), local(port)])

        def no_ipv6(family, kind, proto):
            if family == V6:
                raise OSError(errno.EAFNOSUPPORT, "Address family not supported by protocol")
            return net.socket(family, kind, proto)
        monkeypatch.setattr(calendars.socket, "socket", no_ipv6)
        with calendars.connect(("calendar.invalid", 80), 30) as sock:
            assert sock.getpeername() == ("127.0.0.1", port)


def test_after_the_connect_the_socket_has_the_timeout_of_the_call_for_each_read(monkeypatch):
    with socket.create_server(("127.0.0.1", 0)) as listener:
        net = FakeNet(monkeypatch, [v6(1), local(listener.getsockname()[1])])
        with calendars.connect(("calendar.invalid", 80), 30) as sock:
            assert sock.gettimeout() == 30
    assert net.tries == [("2001:db8::1", 15)]


def test_https_connects_in_turn_and_keeps_the_default_tls_context_with_its_host_check(
        monkeypatch):
    wrapped = []

    def wrap_socket(context, sock, server_hostname=None, **kwargs):
        wrapped.append((context.check_hostname, context.verify_mode, server_hostname))
        raise ssl.SSLError("stop here")
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap_socket)
    with socket.create_server(("127.0.0.1", 0)) as listener:
        net = FakeNet(monkeypatch, [v6(1), local(listener.getsockname()[1])])
        with pytest.raises(calendars.FetchFailed):
            calendars.fetch(f"https://calendar.invalid:{listener.getsockname()[1]}/basic.ics")
    assert net.tries == [("2001:db8::1", 15)]
    assert wrapped == [(True, ssl.CERT_REQUIRED, "calendar.invalid")]


def test_the_google_fetch_connects_in_turn(monkeypatch):
    with serve(b"{}") as port:
        net = FakeNet(monkeypatch, [v6(1, port), local(port)])
        assert gcal.fetch(f"http://calendar.invalid:{port}/x") == b"{}"
    assert net.tries == [("2001:db8::1", 15)]


@pytest.mark.parametrize("error, reason", [
    (TimeoutError, "no reply in 30 s"), (ConnectionRefusedError, "fetch failed (URLError)")])
def test_when_every_address_fails_the_reason_is_fixed(monkeypatch, error, reason):
    net = FakeNet(monkeypatch, [v6(1), v4(1)], live=None, error=error)
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch(f"https://calendar-{MARKER}.invalid/basic.ics")
    assert [host for host, _ in net.tries] == ["2001:db8::1", "192.0.2.1"]
    assert str(err.value) == reason
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert MARKER not in repr(err.value) and "2001:db8" not in str(err.value)


# --- a fair share of the time left, and the deadline ---------------------------------------

def test_each_connect_but_the_last_has_its_share_and_the_last_the_time_left(monkeypatch):
    assert calendars.CONNECT_SECONDS == 5
    assert connect_tries(monkeypatch, [v6(1), v6(2), v6(3)]) == [
        ("2001:db8::1", 10), ("2001:db8::2", 10), ("2001:db8::3", 10)]


def test_an_address_that_fails_at_once_leaves_its_time_to_the_next(monkeypatch):
    tries = connect_tries(monkeypatch, [v6(1), v4(1), v6(2)], took={"2001:db8::1": 0})
    assert tries == [("2001:db8::1", 10), ("192.0.2.1", 15), ("2001:db8::2", 15)]


def test_a_lone_address_gets_the_whole_limit(monkeypatch):
    assert connect_tries(monkeypatch, [v6(1)]) == [("2001:db8::1", 30)]


def test_a_try_but_the_last_keeps_5_seconds_while_that_much_is_left(monkeypatch):
    tries = connect_tries(monkeypatch, [v6(n) for n in range(1, 9)])
    assert tries == [(f"2001:db8::{n}", 5) for n in range(1, 7)]


def test_a_try_gets_no_more_than_the_time_left(monkeypatch):
    tries = connect_tries(monkeypatch, [v6(1), v6(2), v6(3)], took={"2001:db8::1": 27})
    assert tries == [("2001:db8::1", 10), ("2001:db8::2", 3)]


def test_with_no_timeout_each_try_but_the_last_has_5_seconds_and_the_last_none(monkeypatch):
    net = FakeNet(monkeypatch, [v6(1), v6(2)], live=None)
    with pytest.raises(TimeoutError):
        calendars.connect(("calendar.invalid", 80))
    assert net.tries == [("2001:db8::1", 5), ("2001:db8::2", None)]


def test_an_empty_address_list_raises_an_os_error(monkeypatch):
    FakeNet(monkeypatch, [])
    with pytest.raises(OSError):
        calendars.connect(("calendar.invalid", 80), 30)


# --- the limits and the address count in the reason ----------------------------------------

def test_a_spent_deadline_says_how_many_addresses_got_no_try(monkeypatch):
    FakeNet(monkeypatch, [v6(n) for n in range(1, 9)], live=None)
    with pytest.raises(TimeoutError) as err:
        calendars.connect(("calendar.invalid", 80), 30)
    assert str(err.value) == "timed out: 2 of 8 addresses got no try"


def test_a_timeout_of_0_gives_no_address_a_try(monkeypatch):
    net = FakeNet(monkeypatch, [v6(1), v6(2), v6(3)], live=None)
    with pytest.raises(TimeoutError) as err:
        calendars.connect(("calendar.invalid", 80), 0)
    assert str(err.value) == "timed out: 3 of 3 addresses got no try"
    assert net.tries == []


def test_fetch_of_a_spent_deadline_gives_the_count(monkeypatch):
    FakeNet(monkeypatch, [v6(n) for n in range(1, 9)], live=None)
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch("http://calendar.invalid/x")
    assert str(err.value) == "no reply in 30 s (2 of 8 addresses got no try)"


@pytest.mark.parametrize("error, reason", [
    (lambda: urllib.error.URLError(calendars.SpentDeadline(3, 3)),
     "no reply in 30 s (3 of 3 addresses got no try)"),
    (lambda: calendars.SpentDeadline(3, 3), "no reply in 30 s (3 of 3 addresses got no try)"),
    (lambda: urllib.error.URLError(TimeoutError("timed out: 9 of 9 addresses got no try")),
     "no reply in 30 s"),
], ids=["url-error", "bare", "other-timeout"])
def test_the_count_comes_from_a_spent_deadline_only(error, reason):
    def opener(url, timeout):
        raise error()
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch("http://calendar.invalid/x", opener=opener)
    assert str(err.value) == reason


def test_fetch_joins_the_worker_for_the_timeout_plus_the_grace(monkeypatch):
    limits = []

    class Thread:
        def __init__(self, **kw):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            limits.append(timeout)

        def is_alive(self):
            return True

    monkeypatch.setattr(calendars, "threading", types.SimpleNamespace(Thread=Thread))
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch("http://calendar.invalid/x", timeout=1)
    assert str(err.value) == "no reply in 1 s"
    assert limits == [1 + calendars.GRACE_SECONDS] and calendars.GRACE_SECONDS == 1


def test_a_worker_that_ends_in_the_grace_gives_its_own_reason(monkeypatch):
    monkeypatch.setattr(calendars, "GRACE_SECONDS", 3)

    def opener(url, timeout):
        time.sleep(1.5)
        raise urllib.error.URLError(calendars.SpentDeadline(2, 8))
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch("http://calendar.invalid/x", timeout=1, opener=opener)
    assert str(err.value) == "no reply in 1 s (2 of 8 addresses got no try)"


@pytest.mark.parametrize("timeout", [None, "30"])
def test_a_timeout_that_is_not_a_number_gives_a_fixed_reason_before_any_request(timeout):
    calls = []
    with pytest.raises(calendars.FetchFailed) as err:
        calendars.fetch("http://calendar.invalid/x", timeout=timeout,
                        opener=lambda url, timeout: calls.append(url))
    assert str(err.value) == "fetch failed (TypeError)"
    assert calls == []

"""Launcher stability: MOTW removal, single instance, browser-mode idle shutdown,
graceful shutdown that lets in-flight requests finish, and the front-end heartbeat.

Every test that calls main() runs it in a separate thread guarded by join(timeout),
so a hang fails the test instead of blocking the suite.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import types
import urllib.request
import webbrowser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
NODE = shutil.which("node")
ZONE = ":Zone.Identifier"
ZONE_TEXT = "[ZoneTransfer]\nZoneId=3\n"


# ---------- helpers ----------

def fake_webview(monkeypatch, *, start=None, create_window=None):
    calls = {"create_window": [], "start": []}
    fake = types.ModuleType("webview")
    fake.settings = {}

    def _create_window(*a, **k):
        calls["create_window"].append((a, k))
        if create_window is not None:
            return create_window(*a, **k)

    def _start(*a, **k):
        calls["start"].append((a, k))
        if start is not None:
            return start(*a, **k)

    fake.create_window = _create_window
    fake.start = _start
    monkeypatch.setitem(sys.modules, "webview", fake)
    return calls


def failing_webview(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no webview in tests")
    return fake_webview(monkeypatch, create_window=boom)


def run_main(argv, timeout=20.0):
    from app import main as app_main
    out = {}

    def target():
        try:
            out["rc"] = app_main.main(argv)
        except BaseException as e:  # noqa: BLE001 - re-raised in the test thread
            out["exc"] = e
        finally:
            out["t"] = time.monotonic()

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    assert not th.is_alive(), f"main({argv}) did not return within {timeout}s"
    if "exc" in out:
        raise out["exc"]
    return out


def get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def record_fake_open(monkeypatch, on_open=None):
    opened = []

    def fake_open(url, *a, **k):
        opened.append(url)
        if on_open is not None:
            on_open(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)
    return opened


def add_slow_route(monkeypatch, seconds, entered=None):
    """Wrap app.main.create_app so the app gets GET /api/_slow (ahead of the static mount)."""
    from app import main as app_main
    original = app_main.create_app

    def wrapped(*a, **k):
        app = original(*a, **k)

        def slow():
            if entered is not None:
                entered.set()
            time.sleep(seconds)
            return {"done": True}

        app.add_api_route("/api/_slow", slow, methods=["GET"])
        app.router.routes.insert(0, app.router.routes.pop())
        return app

    monkeypatch.setattr(app_main, "create_app", wrapped)


def slow_request(url, result):
    try:
        status, body = get_json(url + "/api/_slow", timeout=60)
        result["status"], result["body"] = status, body
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
    finally:
        result["t"] = time.monotonic()


@pytest.fixture
def running_server(tmp_path):
    """A real uvicorn server on a free port (stands in for an already running instance)."""
    import uvicorn
    from app import main as app_main
    from app.server import create_app
    port = app_main.free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(tmp_path / "other.db"), host="127.0.0.1",
                                           port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    assert app_main.wait_ready(f"http://127.0.0.1:{port}")
    yield port
    server.should_exit = True
    th.join(10)


@pytest.fixture
def held_lock():
    from app import config, instance
    lock = instance.acquire(config.data_dir())
    assert lock is not None
    yield lock
    lock.release()


# ---------- MOTW: clear_zone_marks ----------

def _make_ads(p: Path):
    if sys.platform != "win32":
        pytest.skip("Zone.Identifier streams are Windows-only")
    try:
        with open(str(p) + ZONE, "w") as f:
            f.write(ZONE_TEXT)
    except OSError as e:
        pytest.skip(f"cannot create alternate data stream here: {e}")


def test_clear_zone_marks_removes_marks_recursively(tmp_path):
    from app.main import clear_zone_marks
    files = {
        tmp_path / "a.txt": b"alpha",
        tmp_path / "sub" / "b.dll": b"\x00\x01binary",
        tmp_path / "sub" / "deeper" / "c.js": b"export const x = 1;\n",
    }
    unmarked = tmp_path / "sub" / "plain.txt"
    unmarked.parent.mkdir(parents=True, exist_ok=True)
    unmarked.write_bytes(b"plain")
    for p, data in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        _make_ads(p)
        assert os.path.exists(str(p) + ZONE)

    assert clear_zone_marks(tmp_path) == len(files)

    for p, data in files.items():
        assert not os.path.exists(str(p) + ZONE), p
        assert p.read_bytes() == data
    assert unmarked.read_bytes() == b"plain"


def test_clear_zone_marks_no_marks_returns_zero(tmp_path):
    from app.main import clear_zone_marks
    (tmp_path / "x.txt").write_text("x")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "y.txt").write_text("y")
    assert clear_zone_marks(tmp_path) == 0


def test_clear_zone_marks_missing_path_returns_zero(tmp_path):
    from app.main import clear_zone_marks
    assert clear_zone_marks(tmp_path / "does-not-exist") == 0


def test_clear_zone_marks_read_only_file_no_exception(tmp_path):
    from app.main import clear_zone_marks
    ro = tmp_path / "ro.txt"
    rw = tmp_path / "rw.txt"
    ro.write_text("ro")
    rw.write_text("rw")
    _make_ads(ro)
    _make_ads(rw)
    os.chmod(ro, stat.S_IREAD)
    try:
        n = clear_zone_marks(tmp_path)
        assert isinstance(n, int)
        assert n >= 1
        assert not os.path.exists(str(rw) + ZONE)
        assert ro.read_text() == "ro"
    finally:
        os.chmod(ro, stat.S_IREAD | stat.S_IWRITE)


def test_main_frozen_clears_marks_before_create_app(monkeypatch):
    from app import main as app_main
    order = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(ROOT), raising=False)

    def fake_clear(root):
        order.append(("clear", root))
        return 0

    original = app_main.create_app

    def wrapped(*a, **k):
        order.append(("create_app", None))
        return original(*a, **k)

    monkeypatch.setattr(app_main, "clear_zone_marks", fake_clear)
    monkeypatch.setattr(app_main, "create_app", wrapped)
    calls = fake_webview(monkeypatch, create_window=lambda *a, **k: order.append(("webview", None)))

    out = run_main(["--port", str(app_main.free_port())])
    assert out["rc"] == 0
    assert [name for name, _ in order] == ["clear", "create_app", "webview"]
    assert Path(order[0][1]) == Path(ROOT)
    assert len(calls["create_window"]) == 1


def test_main_not_frozen_does_not_clear_marks(monkeypatch):
    from app import main as app_main
    monkeypatch.delattr(sys, "frozen", raising=False)
    called = []
    monkeypatch.setattr(app_main, "clear_zone_marks", lambda root: called.append(root) or 0)
    fake_webview(monkeypatch)
    out = run_main(["--port", str(app_main.free_port())])
    assert out["rc"] == 0
    assert called == []


# ---------- single instance: app.instance ----------

def test_instance_constants():
    from app import instance
    assert instance.LOCK_NAME == "instance.lock"
    assert instance.INFO_NAME == "instance.json"


def test_acquire_release_reacquire(tmp_path):
    from app import instance
    d = tmp_path / "inst"
    d.mkdir()
    lock = instance.acquire(d)
    assert isinstance(lock, instance.InstanceLock)
    try:
        assert instance.acquire(d) is None
    finally:
        lock.release()
    again = instance.acquire(d)
    assert isinstance(again, instance.InstanceLock)
    again.release()
    again.release()  # idempotent
    lock.release()


def test_different_data_dirs_do_not_block(tmp_path):
    from app import instance
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    la = instance.acquire(a)
    lb = instance.acquire(b)
    try:
        assert la is not None
        assert lb is not None
    finally:
        for lk in (la, lb):
            if lk is not None:
                lk.release()


def test_stale_lock_file_with_content_is_acquirable(tmp_path):
    from app import instance
    d = tmp_path / "stale"
    d.mkdir()
    (d / instance.LOCK_NAME).write_text("12345 leftover from a crashed run")
    lock = instance.acquire(d)
    assert lock is not None
    lock.release()


def test_info_roundtrip_and_clear(tmp_path):
    from app import instance
    d = tmp_path / "info"
    d.mkdir()
    instance.write_info(d, 8765, "browser")
    assert instance.read_info(d) == {"pid": os.getpid(), "port": 8765, "mode": "browser"}
    instance.clear_info(d)
    assert instance.read_info(d) is None
    instance.clear_info(d)  # missing file is fine


@pytest.mark.parametrize("content", [
    "{not json",
    json.dumps({"port": 8765, "mode": "browser"}),
    json.dumps({"pid": 1, "mode": "browser"}),
    json.dumps({"pid": 1, "port": 8765}),
    json.dumps({"pid": 1, "port": 0, "mode": "browser"}),
    json.dumps({"pid": 1, "port": 70000, "mode": "browser"}),
    json.dumps({"pid": 1, "port": "8765", "mode": "browser"}),
    json.dumps({"pid": 1, "port": 8765, "mode": "xyz"}),
], ids=["broken", "no-pid", "no-port", "no-mode", "port0", "port70000", "port-str", "mode-xyz"])
def test_read_info_invalid_returns_none(tmp_path, content):
    from app import instance
    d = tmp_path / "bad"
    d.mkdir()
    (d / instance.INFO_NAME).write_text(content, encoding="utf-8")
    assert instance.read_info(d) is None


def test_read_info_missing_returns_none(tmp_path):
    from app import instance
    assert instance.read_info(tmp_path) is None


def test_write_info_rejects_unknown_mode(tmp_path):
    from app import instance
    with pytest.raises(ValueError):
        instance.write_info(tmp_path, 1, "xyz")


def test_lock_held_by_other_process(tmp_path):
    from app import instance
    d = tmp_path / "proc"
    d.mkdir()
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from app import instance\n"
        "lk = instance.acquire(Path(sys.argv[1]))\n"
        "print('ready' if lk else 'busy', flush=True)\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(d)], cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    killer = threading.Timer(30, proc.kill)
    killer.start()
    try:
        line = proc.stdout.readline().strip()
        assert line == "ready", f"child did not get the lock: {line!r} {proc.stderr.read() if proc.poll() is not None else ''}"
        assert instance.acquire(d) is None
    finally:
        killer.cancel()
        proc.kill()
        proc.wait(10)
        proc.stdout.close()
        proc.stderr.close()

    lock = None
    end = time.monotonic() + 5
    while lock is None and time.monotonic() < end:
        lock = instance.acquire(d)
        if lock is None:
            time.sleep(0.1)
    assert lock is not None, "lock not released after the holder process was killed"
    lock.release()


def test_main_releases_lock_and_clears_info(monkeypatch):
    from app import config, instance
    from app import main as app_main
    fake_webview(monkeypatch)
    out = run_main(["--port", str(app_main.free_port())])
    assert out["rc"] == 0
    d = config.data_dir()
    assert not (d / instance.INFO_NAME).exists()
    lock = instance.acquire(d)
    assert lock is not None
    lock.release()


def test_main_ignores_stale_info_when_lock_free(monkeypatch):
    from app import config, instance
    from app import main as app_main
    d = config.data_dir()
    (d / instance.LOCK_NAME).write_text("99999")
    (d / instance.INFO_NAME).write_text(json.dumps({"pid": 99999, "port": 1, "mode": "window"}), encoding="utf-8")
    focused = []
    monkeypatch.setattr(instance, "focus_window", lambda title: focused.append(title) or True)
    opened = record_fake_open(monkeypatch)
    seen = []
    calls = fake_webview(monkeypatch, start=lambda *a, **k: seen.append(instance.read_info(d)))
    port = app_main.free_port()
    out = run_main(["--port", str(port)])
    assert out["rc"] == 0
    assert len(calls["create_window"]) == 1
    assert focused == [] and opened == []
    # the stale info was overwritten by this run while it was up
    assert seen and seen[0] is not None and seen[0]["port"] == port and seen[0]["pid"] == os.getpid()


def _track_create_app(monkeypatch):
    from app import main as app_main
    created = []
    original = app_main.create_app

    def wrapped(*a, **k):
        created.append(1)
        return original(*a, **k)

    monkeypatch.setattr(app_main, "create_app", wrapped)
    return created


def test_second_launch_opens_browser_of_running_instance(monkeypatch, held_lock, running_server):
    from app import config, instance
    instance.write_info(config.data_dir(), running_server, "browser")
    opened = record_fake_open(monkeypatch)
    focused = []
    monkeypatch.setattr(instance, "focus_window", lambda title: focused.append(title) or True)
    created = _track_create_app(monkeypatch)
    fake_webview(monkeypatch)

    out = run_main([])
    assert out["rc"] == 0
    assert opened == [f"http://127.0.0.1:{running_server}"]
    assert created == []
    assert focused == []


def test_second_launch_focuses_window_of_running_instance(monkeypatch, held_lock, running_server):
    from app import config, instance
    from app import main as app_main
    instance.write_info(config.data_dir(), running_server, "window")
    opened = record_fake_open(monkeypatch)
    focused = []
    monkeypatch.setattr(instance, "focus_window", lambda title: focused.append(title) or True)
    created = _track_create_app(monkeypatch)
    fake_webview(monkeypatch)

    out = run_main([])
    assert out["rc"] == 0
    assert focused == [app_main.window_title()]
    assert opened == []
    assert created == []


def test_second_launch_no_open_does_nothing(monkeypatch, held_lock, running_server):
    from app import config, instance
    instance.write_info(config.data_dir(), running_server, "browser")
    opened = record_fake_open(monkeypatch)
    focused = []
    monkeypatch.setattr(instance, "focus_window", lambda title: focused.append(title) or True)
    created = _track_create_app(monkeypatch)

    out = run_main(["--no-open"])
    assert out["rc"] == 0
    assert opened == [] and focused == [] and created == []


@pytest.mark.parametrize("with_info", [False, True], ids=["no-info", "dead-port"])
def test_second_launch_unresponsive_instance_is_fatal(monkeypatch, held_lock, with_info):
    from app import config, instance
    from app import main as app_main
    if with_info:
        instance.write_info(config.data_dir(), app_main.free_port(), "browser")  # nothing listens there
    monkeypatch.setattr(app_main, "ACTIVATE_WAIT", 0.5)
    fatal = []
    monkeypatch.setattr(app_main, "_fatal", lambda msg: fatal.append(msg))
    record_fake_open(monkeypatch)
    fake_webview(monkeypatch)

    out = run_main([], timeout=15)
    assert out["rc"] == 1
    assert len(fatal) == 1
    assert "아직 종료되지 않았습니다" in fatal[0]


def test_launch_proceeds_when_lock_released_while_waiting(monkeypatch):
    from app import config, instance
    from app import main as app_main
    lock = instance.acquire(config.data_dir())
    assert lock is not None
    releaser = threading.Timer(0.3, lock.release)
    releaser.start()
    try:
        calls = fake_webview(monkeypatch)
        out = run_main(["--port", str(app_main.free_port())], timeout=30)
        assert out["rc"] == 0
        assert len(calls["create_window"]) == 1
    finally:
        releaser.cancel()
        lock.release()


# ---------- server heartbeat ----------

def test_ping_ok_without_csrf_header(client):
    from fastapi.testclient import TestClient
    assert client.get("/api/ping").json() == {"ok": True}
    bare = TestClient(client.app)
    r = bare.get("/api/ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r = client.get("/api/ping", headers={})
    assert r.status_code == 200


def test_last_ping_updates(tmp_path):
    from fastapi.testclient import TestClient
    from app.server import create_app
    app = create_app(tmp_path / "ping.db")
    before = app.state.last_ping
    assert isinstance(before, float)
    time.sleep(0.05)
    with TestClient(app) as c:
        assert c.get("/api/ping").status_code == 200
    assert app.state.last_ping > before


# ---------- browser idle shutdown: units ----------

def test_idle_constants():
    from app import main as app_main
    assert app_main.IDLE_TIMEOUT == 180.0
    assert isinstance(app_main.ACTIVATE_WAIT, (int, float))


def test_idle_expired():
    from app.main import IDLE_TIMEOUT, idle_expired
    assert idle_expired(100.0, 279.9, 180.0) is False
    assert idle_expired(100.0, 280.0, 180.0) is True
    assert idle_expired(100.0, 100.0 + IDLE_TIMEOUT - 0.1) is False
    assert idle_expired(100.0, 100.0 + IDLE_TIMEOUT) is True


class FakeServer:
    def __init__(self):
        self.should_exit = False


class FakeThread:
    """Alive until join() is called with no timeout; join(poll) advances the fake clock."""

    def __init__(self, clock, alive=True, interrupt_on_first_poll=False):
        self.clock = clock
        self.alive = alive
        self.calls = []
        self.exit_flag_at_poll = []
        self.server = None
        self.interrupt = interrupt_on_first_poll

    def is_alive(self):
        return self.alive

    def join(self, *a, **k):
        self.calls.append((a, k))
        timeout = a[0] if a else k.get("timeout")
        if timeout is None:
            self.alive = False
            return
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        if self.server is not None:
            self.exit_flag_at_poll.append((self.clock.t, self.server.should_exit))
        self.clock.t += timeout


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _untimed_join(call):
    a, k = call
    return (a == () and k == {}) or (a == (None,) and k == {}) or (a == () and k == {"timeout": None})


def _guarded(fn, timeout=5.0):
    out = {}

    def target():
        try:
            out["rv"] = fn()
        except BaseException as e:  # noqa: BLE001
            out["exc"] = e

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    assert not th.is_alive(), "call did not return (infinite loop?)"
    if "exc" in out:
        raise out["exc"]
    return out["rv"]


def test_serve_until_idle_waits_while_seen_then_stops():
    from app.main import serve_until_idle
    clock = FakeClock()
    server = FakeServer()
    thread = FakeThread(clock)
    thread.server = server
    last_seen = lambda: min(clock.t, 5.0)  # heartbeats until t=5, then silence

    rv = _guarded(lambda: serve_until_idle(server, thread, last_seen, timeout=3.0, poll=1.0, clock=clock))

    assert rv == 0
    assert server.should_exit is True
    assert _untimed_join(thread.calls[-1]), f"last join must have no timeout: {thread.calls[-1]}"
    # never asked to exit while heartbeats were fresh (before t = 5 + 3)
    assert all(not flag for t, flag in thread.exit_flag_at_poll if t < 8.0)
    assert 8.0 <= clock.t <= 10.0
    polls = [c for c in thread.calls if not _untimed_join(c)]
    assert all((c[0] or (c[1].get("timeout"),))[0] == 1.0 for c in polls)


def test_serve_until_idle_thread_already_finished():
    from app.main import serve_until_idle
    clock = FakeClock()
    server = FakeServer()
    thread = FakeThread(clock, alive=False)
    rv = _guarded(lambda: serve_until_idle(server, thread, lambda: clock.t, timeout=3.0, poll=1.0, clock=clock))
    assert rv == 0
    assert clock.t <= 1.0


def test_serve_until_idle_keyboard_interrupt_stops_server():
    from app.main import serve_until_idle
    clock = FakeClock()
    server = FakeServer()
    thread = FakeThread(clock, interrupt_on_first_poll=True)
    rv = _guarded(lambda: serve_until_idle(server, thread, lambda: clock.t, timeout=100.0, poll=1.0, clock=clock))
    assert rv == 0
    assert server.should_exit is True
    assert _untimed_join(thread.calls[-1])


def test_stop_server_joins_without_timeout():
    from app.main import stop_server
    clock = FakeClock()
    server = FakeServer()
    thread = FakeThread(clock)
    stop_server(server, thread)
    assert server.should_exit is True
    assert len(thread.calls) == 1
    assert _untimed_join(thread.calls[0]), f"join must have no timeout: {thread.calls[0]}"


# ---------- browser idle shutdown: integration ----------

def test_browser_mode_exits_after_idle(monkeypatch):
    from app import config, instance
    from app import main as app_main
    monkeypatch.setattr(app_main, "IDLE_TIMEOUT", 1.0)
    failing_webview(monkeypatch)
    opened = record_fake_open(monkeypatch)

    modes = []
    stop = threading.Event()

    def poll_info():
        d = config.data_dir()
        while not stop.is_set():
            info = instance.read_info(d)
            if info:
                modes.append(info["mode"])
            time.sleep(0.05)

    poller = threading.Thread(target=poll_info, daemon=True)
    poller.start()
    port = app_main.free_port()
    t0 = time.monotonic()
    try:
        out = run_main(["--port", str(port)], timeout=15)
    finally:
        stop.set()
        poller.join(2)
    assert out["rc"] == 0
    assert out["t"] - t0 < 10
    assert opened == [f"http://127.0.0.1:{port}"]
    assert "browser" in modes


def test_browser_mode_stays_while_pinged(monkeypatch):
    from app import main as app_main
    monkeypatch.setattr(app_main, "IDLE_TIMEOUT", 1.0)
    failing_webview(monkeypatch)
    port = app_main.free_port()
    url = f"http://127.0.0.1:{port}"
    pings = {"last": None, "ok": 0}

    def pinger():
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            try:
                status, body = get_json(url + "/api/ping", timeout=5)
                if status == 200 and body == {"ok": True}:
                    pings["ok"] += 1
            except Exception:  # noqa: BLE001
                pass
            pings["last"] = time.monotonic()
            time.sleep(0.3)

    th = threading.Thread(target=pinger, daemon=True)
    record_fake_open(monkeypatch, on_open=lambda u: th.start())
    out = run_main(["--port", str(port)], timeout=20)
    th.join(5)
    assert out["rc"] == 0
    assert pings["ok"] >= 5
    assert out["t"] >= pings["last"]


# ---------- finish in-flight work before exit ----------

@pytest.mark.parametrize("seconds", [1.5, 6.0], ids=["1.5s", "6s"])
def test_window_mode_waits_for_in_flight_request(monkeypatch, seconds):
    from app import main as app_main
    entered = threading.Event()
    add_slow_route(monkeypatch, seconds, entered)
    port = app_main.free_port()
    url = f"http://127.0.0.1:{port}"
    result = {}
    req = threading.Thread(target=slow_request, args=(url, result), daemon=True)

    def start(*a, **k):
        req.start()
        entered.wait(10)
        time.sleep(0.2)

    fake_webview(monkeypatch, start=start)
    out = run_main(["--port", str(port)], timeout=30)
    req.join(30)
    assert out["rc"] == 0
    assert entered.is_set(), "slow request never reached the server"
    assert result.get("status") == 200, result
    assert result.get("body") == {"done": True}
    assert out["t"] >= result["t"]


def test_browser_mode_idle_exit_waits_for_in_flight_request(monkeypatch):
    from app import main as app_main
    monkeypatch.setattr(app_main, "IDLE_TIMEOUT", 1.0)
    entered = threading.Event()
    add_slow_route(monkeypatch, 3.0, entered)
    failing_webview(monkeypatch)
    port = app_main.free_port()
    url = f"http://127.0.0.1:{port}"
    result = {}
    req = threading.Thread(target=slow_request, args=(url, result), daemon=True)
    record_fake_open(monkeypatch, on_open=lambda u: req.start())

    out = run_main(["--port", str(port)], timeout=30)
    req.join(30)
    assert out["rc"] == 0
    assert entered.is_set()
    assert result.get("status") == 200, result
    assert result.get("body") == {"done": True}
    assert out["t"] >= result["t"]


# ---------- front-end heartbeat (static checks) ----------

def test_app_js_heartbeat():
    src = APP_JS.read_text(encoding="utf-8")
    assert re.search(r"HEARTBEAT_MS\s*=\s*20000\b", src)
    assert 'api("/ping")' in src
    assert "setInterval" in src
    assert "clearInterval" in src
    assert not re.search(r'api\("/ping"\)[^;\n]*toastErr', src)


@pytest.mark.skipif(NODE is None, reason="node 없음")
def test_app_js_syntax_module():
    with open(APP_JS, "rb") as f:
        r = subprocess.run([NODE, "--check", "--input-type=module"], stdin=f, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]

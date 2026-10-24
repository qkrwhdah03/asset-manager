"""프로그램 진입점.

기본: 로컬 서버(127.0.0.1, 빈 포트)를 띄우고 pywebview(Edge WebView2) 데스크톱 창으로 연다.
pywebview 를 쓸 수 없으면 기본 브라우저로 연다.

  python -m app.main              # 데스크톱 창
  python -m app.main --browser    # 브라우저로 열기
  python -m app.main --port 8765 --no-open   # 서버만 실행
"""
import argparse
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, config, instance
from .server import create_app

log = logging.getLogger("asset-manager")

IDLE_TIMEOUT = 180.0   # seconds without a heartbeat before browser mode shuts down
ACTIVATE_WAIT = 15.0   # seconds a second launch waits for the running instance (module constant, monkeypatchable)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "/api/meta", timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def window_title() -> str:
    """Title shown in the OS window title bar."""
    return f"v{__version__}"


def clear_zone_marks(root: Path) -> int:
    """Remove the Zone.Identifier stream (Mark of the Web) from every file under root.

    Returns the number of streams removed. Never raises; no-op outside Windows.
    """
    if os.name != "nt":
        return 0
    count = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                try:
                    os.remove(os.path.join(dirpath, name) + ":Zone.Identifier")
                    count += 1
                except OSError:  # includes FileNotFoundError (no stream)
                    pass
    except Exception:
        pass
    return count


def idle_expired(last_seen: float, now: float, timeout: float = IDLE_TIMEOUT) -> bool:
    return now - last_seen >= timeout


def stop_server(server, thread) -> None:
    """Stop accepting connections and wait, without a time limit, for in-flight requests to finish."""
    server.should_exit = True
    thread.join()


def serve_until_idle(server, thread, last_seen, timeout: float = IDLE_TIMEOUT,
                     poll: float = 1.0, clock=time.monotonic) -> int:
    """Serve until no heartbeat has arrived for `timeout` seconds, then shut down gracefully."""
    try:
        while thread.is_alive():
            if idle_expired(last_seen(), clock(), timeout):
                break
            thread.join(poll)
    except KeyboardInterrupt:
        pass
    stop_server(server, thread)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="개인 자산 관리")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--browser", action="store_true", help="데스크톱 창 대신 기본 브라우저로 연다")
    ap.add_argument("--no-open", action="store_true", help="창을 열지 않고 서버만 실행")
    args = ap.parse_args(argv)
    if sys.stdout is None or sys.stderr is None:
        # pythonw.exe / 콘솔 없는 exe 실행 시 표준 출력이 없으므로 로그 파일로 보낸다.
        log_file = open(config.data_dir() / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log_file
        sys.stderr = sys.stderr or log_file
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if getattr(sys, "frozen", False):
        # Only the bundled _internal folder; the exe's parent may be the Downloads folder.
        removed = clear_zone_marks(Path(sys._MEIPASS))
        if removed > 0:
            log.info("다운로드 표시(Zone.Identifier) %d개를 제거했습니다.", removed)

    data_dir = config.data_dir()
    lock = instance.acquire(data_dir)
    if lock is None:
        lock, code = _activate_existing(args, data_dir)
        if lock is None:
            return code

    state = {"server": None, "thread": None}
    try:
        return _run(args, data_dir, state)
    finally:
        # Clear run info first so a new launch does not connect to a dying server,
        # then drain the server, and release the lock only after the thread has ended.
        try:
            instance.clear_info(data_dir)
            if state["server"] is not None and state["thread"] is not None:
                stop_server(state["server"], state["thread"])
        finally:
            lock.release()


def _activate_existing(args, data_dir):
    """Hand off to the running instance. Returns (lock, exit_code); lock is set if it was freed meanwhile."""
    end = time.monotonic() + ACTIVATE_WAIT
    while True:
        info = instance.read_info(data_dir)
        if info:
            url = f"http://127.0.0.1:{info['port']}"
            if wait_ready(url, timeout=1.0):
                if not args.no_open:
                    if info["mode"] == "window":
                        instance.focus_window(window_title())
                    else:
                        webbrowser.open(url)
                return None, 0
        lock = instance.acquire(data_dir)
        if lock is not None:
            # The previous instance finished shutting down; start normally.
            return lock, 0
        if time.monotonic() >= end:
            break
        time.sleep(0.3)
    _fatal("이전에 실행한 프로그램이 아직 종료되지 않았습니다.\n잠시 후 다시 실행하세요.")
    return None, 1


def _run(args, data_dir, state) -> int:
    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}"
    try:
        app = create_app()
    except Exception as e:  # DB 초기화 실패 등
        log.exception("초기화 실패")
        _fatal(f"프로그램을 시작할 수 없습니다.\n\n{e}\n\n데이터 위치: {config.data_dir()}")
        return 1

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    state["server"], state["thread"] = server, t
    t.start()
    if not wait_ready(url):
        _fatal("로컬 서버를 시작하지 못했습니다.")
        return 1
    log.info("개인 자산 관리 v%s 실행 중: %s (데이터: %s)", __version__, url, config.data_dir())
    mode = "server" if args.no_open else ("browser" if args.browser else "window")
    instance.write_info(data_dir, port, mode)

    if args.no_open:
        return _serve_forever(server, t, data_dir)
    if not args.browser:
        try:
            import webview  # pywebview
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window(window_title(), url, width=1440, height=920, min_size=(1024, 680))
            webview.start(icon=str(config.icon_file()))
            instance.clear_info(data_dir)
            stop_server(server, t)
            return 0
        except Exception as e:
            log.warning("데스크톱 창을 열 수 없어 브라우저로 엽니다: %s", e)
            instance.write_info(data_dir, port, "browser")
    webbrowser.open(url)
    print(f"브라우저에서 {url} 이(가) 열렸습니다. 브라우저 탭을 닫으면 잠시 후 자동으로 종료됩니다.")
    return serve_until_idle(server, t, lambda: app.state.last_ping, timeout=IDLE_TIMEOUT)


def _serve_forever(server, t, data_dir) -> int:
    try:
        while t.is_alive():
            t.join(0.5)
    except KeyboardInterrupt:
        instance.clear_info(data_dir)
        stop_server(server, t)
    return 0


def _fatal(msg: str) -> None:
    print(msg, file=sys.stderr)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "개인 자산 관리", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())

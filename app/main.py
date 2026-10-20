"""프로그램 진입점.

기본: 로컬 서버(127.0.0.1, 빈 포트)를 띄우고 pywebview(Edge WebView2) 데스크톱 창으로 연다.
pywebview 를 쓸 수 없으면 기본 브라우저로 연다.

  python -m app.main              # 데스크톱 창
  python -m app.main --browser    # 브라우저로 열기
  python -m app.main --port 8765 --no-open   # 서버만 실행
"""
import argparse
import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from . import __version__, config
from .server import create_app

log = logging.getLogger("asset-manager")


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
    t.start()
    if not wait_ready(url):
        _fatal("로컬 서버를 시작하지 못했습니다.")
        return 1
    log.info("개인 자산 관리 v%s 실행 중: %s (데이터: %s)", __version__, url, config.data_dir())

    if args.no_open:
        return _serve_forever(server, t)
    if not args.browser:
        try:
            import webview  # pywebview
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window(f"개인 자산 관리 v{__version__}", url, width=1440, height=920, min_size=(1024, 680))
            webview.start()
            server.should_exit = True
            t.join(timeout=5)
            return 0
        except Exception as e:
            log.warning("데스크톱 창을 열 수 없어 브라우저로 엽니다: %s", e)
    webbrowser.open(url)
    print(f"브라우저에서 {url} 이(가) 열렸습니다. 종료하려면 이 창에서 Ctrl+C 를 누르세요.")
    return _serve_forever(server, t)


def _serve_forever(server, t) -> int:
    try:
        while t.is_alive():
            t.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        t.join(timeout=5)
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

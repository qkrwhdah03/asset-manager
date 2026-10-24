"""Single-instance lock and run info for the data folder.

Only one instance may use a given data folder. The running instance records its
port and mode in INFO_NAME so a second launch can hand off to it.
Standard library only; does not import other app modules.
"""
import json
import os
from pathlib import Path

LOCK_NAME = "instance.lock"
INFO_NAME = "instance.json"
MODES = ("window", "browser", "server")


class InstanceLock:
    """Holds a non-blocking exclusive lock on byte 0 of the lock file."""

    def __init__(self, fh):
        self._fh = fh

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            _unlock(fh)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass


def _lock(fh) -> None:
    fh.seek(0)
    if os.name == "nt":
        import msvcrt
        # LK_NBLCK fails immediately; LK_LOCK would retry for 10 seconds.
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh) -> None:
    fh.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def acquire(data_dir: Path) -> InstanceLock | None:
    """Return the lock, or None if another live instance holds it."""
    path = Path(data_dir) / LOCK_NAME
    try:
        fh = open(path, "a+b")
    except OSError:
        return None
    try:
        _lock(fh)
    except OSError:
        fh.close()
        return None
    return InstanceLock(fh)


def write_info(data_dir: Path, port: int, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    path = Path(data_dir) / INFO_NAME
    tmp = path.with_name(INFO_NAME + ".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "port": port, "mode": mode}), encoding="utf-8")
    # Atomic swap so a reader never sees a half-written file.
    os.replace(tmp, path)


def read_info(data_dir: Path) -> dict | None:
    try:
        data = json.loads((Path(data_dir) / INFO_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    pid, port, mode = data.get("pid"), data.get("port"), data.get("mode")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return None
    if mode not in MODES:
        return None
    return {"pid": pid, "port": port, "mode": mode}


def clear_info(data_dir: Path) -> None:
    try:
        os.remove(Path(data_dir) / INFO_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def focus_window(title: str) -> bool:
    """Bring the window with this exact title to the front. True if found."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

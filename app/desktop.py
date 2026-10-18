"""Desktop entry point: run the server on a private local port and show the
dashboard in a native window (Edge WebView2 on Windows).

The server listens on 127.0.0.1 only and stops when the window closes. Source
links open in the user's default browser.
"""

from __future__ import annotations

import ctypes
import logging
import socket
import sys
import threading
import time

from .config import DATA_DIR

# A fixed port keeps the window's saved UI state (localStorage is per origin).
# If it's taken (e.g. a second copy is open), any free port is used instead.
PREFERRED_PORT = 47361
TITLE = "Hotel Demand Forecaster"
log = logging.getLogger("desktop")


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    if _port_is_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "app.log"
    # A windowed build has no console, so sys.stdout/sys.stderr are None;
    # give libraries that print somewhere harmless to write.
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    logging.basicConfig(
        filename=log_path, level=logging.INFO, force=True,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_path


def _dark_mode() -> bool:
    """Windows 'apps use dark theme' setting, so the window doesn't flash white."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def _error_box(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)  # MB_ICONERROR
    except Exception:  # not on Windows
        print(message, file=sys.stderr)


def main() -> int:
    log_path = _setup_logging()
    import uvicorn
    import webview

    from .main import app

    port = _pick_port()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_config=None, log_level="warning", access_log=False,
    ))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            log.error("server did not start on port %s", port)
            _error_box(f"The forecaster couldn't start its local server.\n\nDetails are in:\n{log_path}")
            return 1
        time.sleep(0.05)
    log.info("server on http://127.0.0.1:%s", port)

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        TITLE, f"http://127.0.0.1:{port}/",
        width=1440, height=920, min_size=(900, 640),
        text_select=True, background_color="#0d0d0d" if _dark_mode() else "#f4f4f1",
    )
    try:
        webview.start(private_mode=False, storage_path=str(DATA_DIR / "webview"))
    except Exception:
        log.exception("window failed")
        _error_box(
            "The app window couldn't open. It needs the Microsoft Edge WebView2 Runtime, "
            "which is built into Windows 11 and available free from Microsoft for Windows 10.\n\n"
            f"Details are in:\n{log_path}"
        )
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())

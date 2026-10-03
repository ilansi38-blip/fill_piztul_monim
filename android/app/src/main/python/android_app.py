"""Android entry point: runs the same web_gui server the desktop and Docker
versions use, on a loopback port, for the app's WebView to load."""
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

_port = None
_lock = threading.Lock()


def start(data_dir: str) -> int:
    """Start the server (once per process) and return the port it listens on.
    `data_dir` is the app's private storage, already seeded with forms.json,
    templates/, configs/ and web/; generated documents go to its output/."""
    global _port
    with _lock:
        if _port is None:
            # web_gui reads these and resolves its relative paths at import time.
            os.environ["FORM_FILLER_HEADLESS"] = "1"
            os.chdir(data_dir)
            import web_gui

            web_gui.WEB_DIR = Path(data_dir) / "web"
            server = ThreadingHTTPServer(("127.0.0.1", 0), web_gui.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            _port = server.server_address[1]
        return _port

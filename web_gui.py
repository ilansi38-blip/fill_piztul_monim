"""Browser-based GUI: a tiny local web server (stdlib only) that serves
web/index.html and exposes the same pipeline gui.py uses as a JSON API.
Run it and it opens http://127.0.0.1:8765 in the default browser. It shuts
itself down a few minutes after the last browser tab is closed.

Set FORM_FILLER_HEADLESS=1 (as the Docker image does) to run it as a plain
server instead: no browser is opened, it never shuts itself down, and
"open" buttons download the file rather than launching Word. HOST/PORT can
be overridden with FORM_FILLER_HOST / FORM_FILLER_PORT."""
import base64
import json
import os
import re
import shutil
import tempfile
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import main as pipeline
import parser as field_parser

HOST = os.environ.get("FORM_FILLER_HOST", "127.0.0.1")
PORT = int(os.environ.get("FORM_FILLER_PORT", "8765"))
HEADLESS = os.environ.get("FORM_FILLER_HEADLESS") == "1"
WEB_DIR = Path(__file__).resolve().parent / "web"
OUTPUT_DIR = Path(pipeline.OUTPUT_DIR).resolve()
TEMPLATES_DIR = Path(pipeline.TEMPLATES_DIR).resolve()
STAGING_DIR = Path(tempfile.gettempdir()) / "fill_piztul_monim_uploads"
SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
DEFAULT_TIMESTAMP_COLUMN = "חותמת זמן"
IDLE_SHUTDOWN_SECONDS = 5 * 60  # browsers throttle background-tab timers, so be generous

# Friendly Hebrew names for forms that don't set "display_name" in forms.json.
KNOWN_DISPLAY_NAMES = {
    "Charging_Station_Inspection_Approval": "אישור בדיקת עמדת טעינה",
}

registry = pipeline.load_forms_registry()
rows_cache = {}  # form name -> rows as last shown to the browser, newest first
generate_lock = threading.Lock()  # fill_rows rewrites config files; never run two at once
last_ping = time.monotonic()


def display_name(form_name: str) -> str:
    form_def = registry.get(form_name, {})
    if form_def.get("display_name"):
        return form_def["display_name"]
    if form_name in KNOWN_DISPLAY_NAMES:
        return KNOWN_DISPLAY_NAMES[form_name]
    match = re.fullmatch(r"tofes[ _]?(\d+)", form_name, re.IGNORECASE)
    if match:
        return f"טופס {match.group(1)}"
    return form_name.replace("_", " ")


def _parse_timestamp(row: dict, form_def: dict) -> datetime:
    try:
        return datetime.strptime(
            row[form_def["timestamp_column"]],
            form_def.get("timestamp_format", "%d/%m/%Y %H:%M:%S"),
        )
    except (KeyError, ValueError):
        return datetime.min


def sheet_url(sheet_id: str | None) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""


def api_forms() -> list:
    return [
        {
            "name": name,
            "display_name": display_name(name),
            "has_sheet": bool(fdef.get("sheet_id")),
            "sheet_url": sheet_url(fdef.get("sheet_id")),
            "form_url": fdef.get("form_url", ""),
        }
        for name, fdef in registry.items()
    ]


# ---------- managing forms (add / edit / delete) ----------

def parse_sheet_id(text: str | None) -> str:
    text = (text or "").strip()
    match = SHEET_ID_PATTERN.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", text):
        return text  # a bare sheet ID
    raise ValueError("זה לא נראה כמו קישור לגיליון Google Sheets (צריך להכיל /spreadsheets/d/...).")


def _safe_form_key(text: str) -> str:
    key = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().strip(".")
    return key or "form"


def _template_path(form_name: str) -> Path:
    return TEMPLATES_DIR / f"{form_name}.docx"


def _staged_path(upload_id: str | None) -> Path:
    path = STAGING_DIR / f"{upload_id}.docx"
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id or "") or not path.is_file():
        raise ValueError("קובץ התבנית שהועלה לא נמצא. העלו אותו שוב.")
    return path


def api_upload_template(body: dict) -> dict:
    filename = body.get("filename") or "template.docx"
    if not filename.lower().endswith(".docx"):
        raise ValueError("יש להעלות קובץ Word מסוג docx (קובץ doc ישן יש לשמור קודם בפורמט docx).")
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = os.urandom(16).hex()
    path = STAGING_DIR / f"{upload_id}.docx"
    path.write_bytes(base64.b64decode(body.get("data") or ""))
    try:
        placeholders = list(field_parser.extract_keywords(str(path)))
    except Exception:
        path.unlink(missing_ok=True)
        raise ValueError("לא ניתן לקרוא את הקובץ. ודאו שזה מסמך Word תקין ושאינו מוגן בסיסמה.")
    return {"upload_id": upload_id, "placeholders": placeholders, "suggested_name": Path(filename).stem}


def api_sheet_columns(body: dict) -> dict:
    sheet_id = parse_sheet_id(body.get("sheet"))
    columns = pipeline.fetch_sheet_columns(sheet_id)
    if not columns:
        raise ValueError("הגיליון ריק: לא נמצאה שורת כותרות.")
    rows = pipeline.fetch_sheet_rows(sheet_id)
    return {"sheet_id": sheet_id, "columns": columns, "sample": rows[-1] if rows else {}}


def api_form_detail(form_name: str) -> dict:
    form_def = registry[form_name]
    template = _template_path(form_name)
    placeholders = list(field_parser.extract_keywords(str(template))) if template.is_file() else []
    return {
        "name": form_name,
        "display_name": display_name(form_name),
        "template_file": template.name if template.is_file() else "",
        "placeholders": placeholders,
        "sheet_url": sheet_url(form_def.get("sheet_id")),
        "form_url": form_def.get("form_url", ""),
        "timestamp_column": form_def.get("timestamp_column", DEFAULT_TIMESTAMP_COLUMN),
        "row_filter": form_def.get("row_filter"),
        "key_to_column": {key: column for column, key in form_def.get("column_to_key", {}).items()},
    }


def api_save_form(body: dict) -> dict:
    global registry
    current = pipeline.load_forms_registry()
    original_name = body.get("original_name")
    upload_id = body.get("upload_id")

    if original_name:
        if original_name not in current:
            raise ValueError("הטופס לא נמצא (אולי נמחק בינתיים).")
        form_name = original_name
        entry = dict(current[original_name])  # keeps extras like value_map
    else:
        if not upload_id:
            raise ValueError("יש להעלות קובץ תבנית Word.")
        base = _safe_form_key(body.get("name") or body.get("display_name") or "form")
        form_name, n = base, 2
        while form_name in current or _template_path(form_name).exists():
            form_name, n = f"{base}_{n}", n + 1
        entry = {}

    display = (body.get("display_name") or "").strip()
    if not display:
        raise ValueError("יש לתת לטופס שם.")
    sheet_id = parse_sheet_id(body.get("sheet"))
    form_url = (body.get("form_url") or "").strip()
    if form_url and not form_url.startswith(("http://", "https://")):
        raise ValueError("הקישור לטופס Google צריך להתחיל ב-https://")

    if upload_id:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(_staged_path(upload_id), _template_path(form_name))
        except PermissionError:
            raise ValueError("קובץ התבנית הקיים פתוח ב-Word. סגרו אותו ונסו שוב.")
    elif not _template_path(form_name).is_file():
        raise ValueError("לא נמצא קובץ תבנית לטופס זה. העלו קובץ Word.")

    template = _template_path(form_name)
    field_parser.merge_keywords(str(template), field_parser.config_path_for(template, pipeline.CONFIGS_DIR))

    entry["display_name"] = display
    entry["sheet_id"] = sheet_id
    if form_url:
        entry["form_url"] = form_url
    else:
        entry.pop("form_url", None)
    entry["timestamp_column"] = (body.get("timestamp_column") or DEFAULT_TIMESTAMP_COLUMN).strip()
    entry.setdefault("timestamp_format", "%d/%m/%Y %H:%M:%S")
    row_filter = body.get("row_filter") or {}
    if row_filter.get("column") and (row_filter.get("must_include") or "").strip():
        entry["row_filter"] = {"column": row_filter["column"], "must_include": row_filter["must_include"].strip()}
    else:
        entry.pop("row_filter", None)
    entry["column_to_key"] = {
        column: key for key, column in (body.get("key_to_column") or {}).items() if column
    }

    current[form_name] = entry
    pipeline.save_forms_registry(current)
    registry = current
    rows_cache.pop(form_name, None)
    if upload_id:
        _staged_path(upload_id).unlink(missing_ok=True)
    return {"name": form_name}


def api_delete_form(form_name: str) -> dict:
    """Removes the form from forms.json only -- its template, config and
    already-generated documents stay on disk."""
    global registry
    current = pipeline.load_forms_registry()
    current.pop(form_name, None)
    pipeline.save_forms_registry(current)
    registry = current
    rows_cache.pop(form_name, None)
    return {"ok": True}


def api_rows(form_name: str) -> dict:
    form_def = registry[form_name]
    sheet_id = form_def.get("sheet_id")
    if not sheet_id:
        rows_cache[form_name] = []
        return {"rows": [], "no_sheet": True}

    rows = pipeline.fetch_sheet_rows(sheet_id)
    rows = [row for row in rows if pipeline.row_matches_filter(row, form_def.get("row_filter"))]
    rows.sort(key=lambda row: _parse_timestamp(row, form_def), reverse=True)
    rows_cache[form_name] = rows

    timestamp_column = form_def["timestamp_column"]
    siblings = pipeline.sibling_forms(form_name, form_def, registry)
    return {
        "rows": [
            {
                "id": idx,
                "timestamp": row.get(timestamp_column, ""),
                "fields": [[k, v] for k, v in row.items() if v and k != timestamp_column],
                "also": [
                    display_name(name)
                    for name, sdef in siblings.items()
                    if pipeline.row_matches_filter(row, sdef.get("row_filter"))
                ],
            }
            for idx, row in enumerate(rows)
        ]
    }


def api_generate(form_name: str, ids: list) -> dict:
    form_def = registry[form_name]
    cached = rows_cache.get(form_name)
    if cached is None:
        raise ValueError("רשימת ההגשות לא נטענה. רעננו את הדף ונסו שוב.")
    rows = [cached[i] for i in ids if 0 <= i < len(cached)]
    if not rows:
        raise ValueError("לא נבחרו הגשות.")

    with generate_lock:
        try:
            all_results = pipeline.fill_rows_with_cascade(form_name, form_def, rows, registry)
        except PermissionError as exc:
            locked = Path(exc.filename).name if exc.filename else "אחד המסמכים"
            raise ValueError(f"הקובץ \"{locked}\" פתוח כרגע ב-Word. סגרו אותו ונסו שוב.")

    results = []
    for name, form_results in all_results.items():
        for _row, output_path in form_results:
            results.append({"form": display_name(name), "file": Path(output_path).name})
    return {"results": results}


def api_outputs() -> list:
    if not OUTPUT_DIR.exists():
        return []
    files = [p for p in OUTPUT_DIR.glob("*.docx") if not p.name.startswith("~$")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"file": p.name, "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")}
        for p in files[:40]
    ]


def _output_file(file_name: str) -> Path:
    target = (OUTPUT_DIR / file_name).resolve()
    if target.parent != OUTPUT_DIR or not target.is_file():
        raise ValueError("הקובץ לא נמצא בתיקיית הפלט.")
    return target


def open_output(file_name: str | None) -> dict:
    """Open a document (or the output folder) on this machine. When there's
    no desktop to open it on (headless / non-Windows), point the browser at a
    download link instead."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if HEADLESS or not hasattr(os, "startfile"):
        if not file_name:
            return {"ok": True, "folder": False}
        _output_file(file_name)
        return {"ok": True, "download": "/api/download?file=" + quote(file_name)}
    os.startfile(str(_output_file(file_name) if file_name else OUTPUT_DIR))
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # pythonw has no console

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _run(self, fn):
        try:
            self._json(fn())
        except Exception as exc:
            traceback.print_exc()
            self._json({"error": str(exc)}, status=500)

    def do_GET(self):
        global last_ping
        last_ping = time.monotonic()
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/forms":
            self._run(api_forms)
        elif url.path == "/api/rows":
            form_name = query.get("form", [""])[0]
            if form_name not in registry:
                self._json({"error": "טופס לא מוכר"}, status=404)
            else:
                self._run(lambda: api_rows(form_name))
        elif url.path == "/api/outputs":
            self._run(api_outputs)
        elif url.path == "/api/download":
            try:
                target = _output_file(query.get("file", [""])[0])
            except ValueError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/form":
            form_name = query.get("form", [""])[0]
            if form_name not in registry:
                self._json({"error": "טופס לא מוכר"}, status=404)
            else:
                self._run(lambda: api_form_detail(form_name))
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        global last_ping
        last_ping = time.monotonic()
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        path = urlparse(self.path).path
        if path == "/api/ping":
            self._json({"ok": True})
        elif path == "/api/generate":
            form_name = body.get("form")
            if form_name not in registry:
                self._json({"error": "טופס לא מוכר"}, status=404)
            else:
                self._run(lambda: api_generate(form_name, [int(i) for i in body.get("ids", [])]))
        elif path == "/api/template":
            self._run(lambda: api_upload_template(body))
        elif path == "/api/sheet-columns":
            self._run(lambda: api_sheet_columns(body))
        elif path == "/api/form/save":
            self._run(lambda: api_save_form(body))
        elif path == "/api/form/delete":
            self._run(lambda: api_delete_form(body.get("name")))
        elif path == "/api/open":
            self._run(lambda: open_output(body.get("file")))
        else:
            self._json({"error": "not found"}, status=404)


def _shutdown_when_idle(server: ThreadingHTTPServer):
    while True:
        time.sleep(30)
        if time.monotonic() - last_ping > IDLE_SHUTDOWN_SECONDS:
            server.shutdown()
            return


def main():
    url = f"http://{HOST}:{PORT}/"
    if HEADLESS:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        print(f"Serving on {url}", flush=True)
        server.serve_forever()
        return
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        # Already running (e.g. launched twice) -- just show it again.
        webbrowser.open(url)
        return
    threading.Thread(target=_shutdown_when_idle, args=(server,), daemon=True).start()
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()

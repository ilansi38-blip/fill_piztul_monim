# fill_piztul_monim — מילוי טפסים

Fills Word (`.docx`) templates from Google Forms submissions. Each form in
`forms.json` points at a template in `templates/` and the Google Sheet that
collects its responses; placeholders written as `__key__` in the template are
replaced with the matching answers, and the result is saved to `output/`.

## Project layout

| Path | Purpose |
| --- | --- |
| `main.py` | Pipeline + CLI: fetch sheet rows, map columns, fill templates |
| `parser.py` | Finds `__key__` placeholders and fills `.docx` files |
| `web_gui.py`, `web/` | Browser UI (stdlib HTTP server) |
| `pdf_export.py` | Optional PDF copies via Microsoft Word (Windows only) |
| `gui.py` | Older Tkinter desktop UI |
| `forms.json` | Registry of forms → template, sheet ID, column mapping |
| `templates/` | Source `.docx` templates |
| `configs/` | Per-template field values (`configs/<template>.json`) |

Google Sheets must be shared as "anyone with the link can view" so their CSV
export can be downloaded.

The web UI has three tabs: **מילוי טופס** (links to fill in each Google Form),
**הגשות** (pick submissions and create documents) and **מסמכים** (open, share or
delete what was created). The last downloaded copy of every sheet is kept in
`cache/`, so submissions still show without a connection. On a Windows machine
with Microsoft Word, each document is also saved as a PDF (`pdf_export.py`).

## Run locally (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.\Run_Form_Filler.bat          # web UI, opens http://127.0.0.1:8765
.venv\Scripts\python main.py   # CLI: fill the latest submission of every form
```

## Run with Docker

```bash
docker compose up -d --build
# open http://localhost:8765
```

`output/`, `templates/`, `configs/` and `forms.json` are mounted from the host,
so generated documents appear in `./output` and changes made in the UI persist.
In the container the "open" buttons download the document instead of launching
Word.

Without compose:

```bash
docker build -t form-filler .
docker run --rm -p 8765:8765 -v "$PWD/output:/app/output" form-filler
docker run --rm -v "$PWD/output:/app/output" form-filler python main.py   # CLI
```

## Android app

`android/` is an Android Studio / Gradle project that wraps the same web UI in
an app. The Python code runs on the phone itself (via
[Chaquopy](https://chaquo.com/chaquopy/)), so no server or PC is needed — only
an internet connection to read the Google Sheets. The build copies `main.py`,
`parser.py`, `web_gui.py`, `web/`, `templates/`, `configs/` and `forms.json`
from the repository root into the APK.

- **GitHub Actions:** every push to `main` builds a debug APK
  (`.github/workflows/android.yml`); download it from the run's *Artifacts*
  (`form-filler-apk`) and install it on the phone.
- **Locally:** open `android/` in Android Studio and press Run, or run
  `gradlew assembleDebug` in `android/` (APK lands in
  `android/app/build/outputs/apk/debug/`). Chaquopy needs Python 3.13 on the
  build machine; if it isn't the default `python`, add
  `buildPython=C:/path/to/python313/python.exe` to `android/local.properties`.

Generated documents are kept in the app's private storage; tapping one offers
to open it (Word, Google Docs…) or share it.

### Environment variables

| Variable | Default (local / Docker) | Meaning |
| --- | --- | --- |
| `FORM_FILLER_HEADLESS` | unset / `1` | Don't open a browser, never idle-shutdown, download instead of open |
| `FORM_FILLER_HOST` | `127.0.0.1` / `0.0.0.0` | Bind address |
| `FORM_FILLER_PORT` | `8765` | Port |

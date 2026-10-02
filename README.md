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
| `gui.py` | Older Tkinter desktop UI |
| `forms.json` | Registry of forms → template, sheet ID, column mapping |
| `templates/` | Source `.docx` templates |
| `configs/` | Per-template field values (`configs/<template>.json`) |

Google Sheets must be shared as "anyone with the link can view" so their CSV
export can be downloaded.

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

### Environment variables

| Variable | Default (local / Docker) | Meaning |
| --- | --- | --- |
| `FORM_FILLER_HEADLESS` | unset / `1` | Don't open a browser, never idle-shutdown, download instead of open |
| `FORM_FILLER_HOST` | `127.0.0.1` / `0.0.0.0` | Bind address |
| `FORM_FILLER_PORT` | `8765` | Port |

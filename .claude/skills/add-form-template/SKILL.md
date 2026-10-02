---
name: add-form-template
description: Use when the user wants to add, register, wire up, or hook up a new document/form template in this project (fill_piztul_monim) — e.g. "add a new template", "add a new form", "hook up tofes_X to a sheet". Walks through registering a new .docx template with its Google Sheet so it works in main.py and gui.py.
version: 1.0.0
---

# Add a new form template

This project fills Hebrew `.docx` templates from Google Sheet submissions. Layout:

- `templates/<name>.docx` — the template. `__placeholder__` markers anywhere
  in it (body text, tables, text boxes) get found by `parser.py`.
- `configs/<name>.json` — one JSON file per template holding its current
  field values; auto-created/synced by `parser.py`, never hand-written.
- `forms.json` — the registry. One entry per form: its Google Sheet ID, the
  timestamp column/format used to find the latest submission, and
  `column_to_key`, mapping sheet column names to `configs/<name>.json` keys.
- `main.py` (CLI) / `web_gui.py` (browser app, the main UI) / `gui.py` (old
  desktop app) — all read `forms.json` and just
  work for any form registered there. No code changes needed for a new form.

## Steps

1. **Get the new template.** If the user hasn't already pointed you at a
   `.docx` file in this conversation, ask for its path. Copy it into
   `templates/`, keeping its filename — the filename stem becomes the form's
   name/key everywhere (e.g. `templates/tofes_4.docx` -> form name `tofes_4`).

2. **Get the Google Sheet.** If the user hasn't given a Google Sheets URL,
   ask for it. Extract the sheet ID (the segment between `/d/` and the next
   `/` in the URL).

3. **Sync placeholders into a config.** Run:
   ```
   python parser.py templates/<name>.docx
   ```
   This creates/updates `configs/<name>.json` with every placeholder found,
   defaulting new keys to `""` and leaving any existing values untouched.

4. **Fetch a sample of the sheet.** Read
   `https://docs.google.com/spreadsheets/d/<sheet_id>/export?format=csv`
   (follow the redirect to the googleusercontent.com URL it 307s to) to see
   the real column headers and at least one real submission row.

5. **Confirm the timestamp column.** Google Forms responses default to a
   column named `חותמת זמן` with values like `08/08/2026 19:55:25` (format
   `%d/%m/%Y %H:%M:%S`). Check this column exists; if the sheet uses
   something different, ask the user or infer it from which column holds
   full datetime values.

6. **Build the column-to-key mapping by judgment, not exact string match.**
   For each key in `configs/<name>.json`, find the sheet column that clearly
   corresponds to it by meaning (e.g. `שם העסק` -> `שם_העסק`). Column
   headers and placeholder keys are rarely worded identically — read both
   lists and use context. When a match is genuinely ambiguous, ask the user
   rather than guessing.
   - Any config key with no sensible sheet counterpart (fields the inspector
     fills in by hand, on-site measurements, etc.) should stay unmapped —
     don't force a mapping just to fill every key.
   - Write mapping entries with clean, single-spaced column names.
     `map_row_to_config` in `main.py` already normalizes internal whitespace
     when matching, so it's fine if the sheet's real header has
     inconsistent double/extra spacing (this has happened before with
     Google Forms columns).
   - If the sheet has duplicate header columns (has happened before), flag
     it to the user — it's a form data-quality issue, not something to
     silently work around in code.

7. **Register the form in `forms.json`.** Add a new top-level entry:
   ```json
   "tofes_4": {
     "sheet_id": "...",
     "timestamp_column": "חותמת זמן",
     "timestamp_format": "%d/%m/%Y %H:%M:%S",
     "column_to_key": { "...": "..." }
   }
   ```

8. **Test end-to-end.** Run `python main.py <name>` and verify the actual
   output docx, not just that the script exited cleanly:
   - No leftover `__placeholders__` anywhere (unmapped ones get blanked, not
     left literal).
   - Table rows with no input for this submission got removed; rows that
     did get data stayed.
   - Values landed in the fields you expect.
   Read the paragraphs/tables directly (e.g. via `parser._iter_paragraphs`
   and walking raw `w:tbl`/`w:tr` elements) to confirm, the way this has
   been checked for every other form added to this project.

9. **Report back**: how many placeholders were found, how many got mapped
   vs. left for manual entry, and confirmation the test run looked correct.
   The new form appears automatically in the web app's form list — no GUI
   changes needed.

## Note: the user can also do this themselves

`web_gui.py` has a "הוספת טופס חדש" (add form) wizard and a per-form settings
(pencil) button: upload the .docx, paste the Google Form + Sheet links, and
map placeholders to columns with auto-suggestions. It writes the same
`forms.json` entry (plus optional `display_name` and `form_url` keys). Use
this skill when the user wants Claude to do it, or for things the wizard
doesn't cover (e.g. `value_map`).

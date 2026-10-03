import argparse
import csv
import io
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import parser as field_parser

FORMS_REGISTRY_PATH = "forms.json"
TEMPLATES_DIR = field_parser.TEMPLATES_DIR
CONFIGS_DIR = field_parser.CONFIGS_DIR
OUTPUT_DIR = "output"


def load_forms_registry(registry_path: str = FORMS_REGISTRY_PATH) -> dict:
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def sheet_csv_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


def _download_sheet_csv(sheet_id: str) -> str:
    with urllib.request.urlopen(sheet_csv_url(sheet_id), timeout=15) as response:
        raw = response.read().decode("utf-8-sig")
    if raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        # A private sheet answers with Google's sign-in page instead of CSV.
        raise ValueError(
            "לא ניתן לקרוא את הגיליון. ודאו שהוא משותף כ'כל מי שקיבל את הקישור' (צפייה)."
        )
    return raw


def fetch_sheet_rows(sheet_id: str) -> list:
    """Download the sheet as CSV and return one dict per row (column -> value)."""
    rows = list(csv.DictReader(io.StringIO(_download_sheet_csv(sheet_id))))
    return [{k.strip(): v for k, v in row.items() if k} for row in rows]


def fetch_sheet_columns(sheet_id: str) -> list:
    """The sheet's header row (works even before the form has any responses)."""
    header = next(csv.reader(io.StringIO(_download_sheet_csv(sheet_id))), [])
    columns = []
    for column in header:
        column = column.strip()
        if column and column not in columns:
            columns.append(column)
    return columns


def save_forms_registry(registry: dict, registry_path: str = FORMS_REGISTRY_PATH) -> None:
    tmp_path = Path(registry_path).with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(registry_path)


def get_latest_row(rows: list, timestamp_column: str, timestamp_format: str) -> dict:
    """Return the row with the most recent timestamp column."""
    return max(
        rows,
        key=lambda row: datetime.strptime(row[timestamp_column], timestamp_format),
    )


def _normalize_column(name: str) -> str:
    """Collapse runs of whitespace to a single space. Google Forms headers
    are sometimes inconsistently double-spaced (e.g. "אמפר  לוח 7" vs
    "אמפר לוח 1"), which would otherwise break an exact-string match."""
    return re.sub(r"\s+", " ", name).strip()


def row_matches_filter(row: dict, row_filter: dict | None) -> bool:
    """Some forms share one sheet with a multi-select question (e.g. "איזה
    עוד טפסים") whose answer is a comma-separated list of chosen options
    (e.g. "טופס 6, טופס 8, טופס 10, טופס 11"). A form with a `row_filter` in
    forms.json (`{"column": ..., "must_include": ...}`) only applies to rows
    where that exact option was one of the ones picked -- matched as a whole
    comma-separated item, not a substring, so "טופס 1" can't accidentally
    match inside "טופס 10" or "טופס 11". Forms without a row_filter apply to
    every row (e.g. the sheet's own base form)."""
    if not row_filter:
        return True
    normalized_row = {_normalize_column(column): value for column, value in row.items()}
    value = normalized_row.get(_normalize_column(row_filter["column"]), "")
    selected_options = [option.strip() for option in value.split(",")]
    return row_filter["must_include"] in selected_options


def map_row_to_config(row: dict, column_to_key: dict, value_map: dict | None = None) -> dict:
    """Translate a sheet row's columns into fields_config.json keys. `value_map`
    (from forms.json, e.g. {"יש": "✓"}) substitutes an exact raw answer with a
    different value on the way in -- used for checkbox-style questions whose
    Google Forms answer text (e.g. "יש") should render in the docx as the
    symbol the template's own instructions ask for, not the literal word."""
    normalized_row = {_normalize_column(column): value for column, value in row.items()}
    mapped = {}
    for column, key in column_to_key.items():
        value = normalized_row.get(_normalize_column(column))
        if not value:
            continue
        if value_map and value in value_map:
            value = value_map[value]
        mapped[key] = value
    return mapped


def build_output_path(form_name: str, row: dict, timestamp_column: str, output_dir: str = OUTPUT_DIR) -> str:
    safe_timestamp = row[timestamp_column].replace("/", "-").replace(":", ".").replace(" ", "_")
    return str(Path(output_dir) / f"{form_name}_{safe_timestamp}.docx")


def fill_rows(form_name: str, form_def: dict, rows: list) -> list:
    """Fill one output docx per row in `rows`, applying them in chronological
    order. Every sheet-mapped key is blanked before each row is applied, so a
    question the submitter left empty stays empty instead of inheriting the
    answer from an earlier submission; only keys the sheet doesn't feed (set
    by hand in the config file) carry over. Saves the form's config to
    reflect the state after the last row. Returns a list of (row,
    output_path) in the order the rows were applied.
    """
    template_path = str(Path(TEMPLATES_DIR) / f"{form_name}.docx")
    config_path = field_parser.config_path_for(template_path, CONFIGS_DIR)
    timestamp_column = form_def["timestamp_column"]
    timestamp_format = form_def.get("timestamp_format", "%d/%m/%Y %H:%M:%S")

    config = field_parser.load_config(config_path)
    results = []
    ordered_rows = sorted(rows, key=lambda row: datetime.strptime(row[timestamp_column], timestamp_format))
    for row in ordered_rows:
        mapped_values = map_row_to_config(row, form_def["column_to_key"], form_def.get("value_map"))
        config.update(dict.fromkeys(form_def["column_to_key"].values(), ""))
        config.update(mapped_values)
        output_path = build_output_path(form_name, row, timestamp_column)
        field_parser.fill_document(template_path, dict(config), output_path)
        results.append((row, output_path))

    field_parser.save_config(config, config_path)
    return results


def sibling_forms(form_name: str, form_def: dict, registry: dict) -> dict:
    """Other forms in the registry that share this form's Google Sheet."""
    sheet_id = form_def.get("sheet_id")
    return {
        name: fdef
        for name, fdef in registry.items()
        if name != form_name and fdef.get("sheet_id") == sheet_id
    }


def fill_rows_with_cascade(form_name: str, form_def: dict, rows: list, registry: dict) -> dict:
    """Fill `rows` for form_name, and for each row, also fill any sibling
    form (one sharing the same sheet) whose row_filter matches that row.
    This is how e.g. a single tofes_3 submission that also checked "טופס 6"
    automatically produces a tofes_6 document too, straight from that same
    row's data -- no separate submission needed. Returns
    {form_name: [(row, output_path), ...], ...} for every form that ended up
    with at least one row filled.
    """
    results = {form_name: fill_rows(form_name, form_def, rows)}
    for sibling_name, sibling_def in sibling_forms(form_name, form_def, registry).items():
        matching_rows = [row for row in rows if row_matches_filter(row, sibling_def.get("row_filter"))]
        if matching_rows:
            results[sibling_name] = fill_rows(sibling_name, sibling_def, matching_rows)
    return results


def run_form(form_name: str, form_def: dict, registry: dict) -> None:
    sheet_id = form_def.get("sheet_id")
    if not sheet_id:
        print(f"[{form_name}] skipped: no sheet_id configured in {FORMS_REGISTRY_PATH}")
        return

    timestamp_column = form_def["timestamp_column"]
    timestamp_format = form_def.get("timestamp_format", "%d/%m/%Y %H:%M:%S")

    rows = fetch_sheet_rows(sheet_id)
    rows = [row for row in rows if row_matches_filter(row, form_def.get("row_filter"))]
    if not rows:
        print(f"[{form_name}] skipped: no submissions match this form's row_filter")
        return

    latest_row = get_latest_row(rows, timestamp_column, timestamp_format)
    all_results = fill_rows_with_cascade(form_name, form_def, [latest_row], registry)

    for name, results in all_results.items():
        for row, output_path in results:
            print(f"[{name}] submission ({row[timestamp_column]}): filled copy saved to: {output_path}")


def main():
    arg_parser = argparse.ArgumentParser(
        description="Fetch each form's latest Google Sheet submission, update "
        "its field config, and fill a fresh copy of its template. Forms are "
        "declared in forms.json -- add a template file to templates/ plus an "
        "entry there to register a new form, no code changes needed."
    )
    arg_parser.add_argument(
        "form_name", nargs="?", default=None,
        help="Only run this one form (must match a key in forms.json). Omit to run all configured forms.",
    )
    args = arg_parser.parse_args()

    registry = load_forms_registry()

    if args.form_name:
        if args.form_name not in registry:
            raise SystemExit(f"'{args.form_name}' is not in {FORMS_REGISTRY_PATH}")
        run_form(args.form_name, registry[args.form_name], registry)
    else:
        for form_name, form_def in registry.items():
            run_form(form_name, form_def, registry)


if __name__ == "__main__":
    main()

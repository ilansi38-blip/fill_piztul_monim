import os
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import Tk, StringVar, messagebox
from tkinter import ttk

import main as pipeline

WINDOW_TITLE = "מילוי טפסים - Piztul Monim"


def _parse_timestamp(row: dict, form_def: dict) -> datetime:
    timestamp_column = form_def["timestamp_column"]
    timestamp_format = form_def.get("timestamp_format", "%d/%m/%Y %H:%M:%S")
    try:
        return datetime.strptime(row[timestamp_column], timestamp_format)
    except (KeyError, ValueError):
        return datetime.min


def _row_summary(row: dict, form_def: dict) -> str:
    timestamp_column = form_def["timestamp_column"]
    parts = [f"{key}: {value}" for key, value in row.items() if value and key != timestamp_column]
    return ", ".join(parts)


class App(Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1000x600")

        self.registry = pipeline.load_forms_registry()
        self.current_rows = []  # rows currently shown in the tree, newest first

        self._build_layout()
        if self.registry:
            first_form = next(iter(self.registry))
            self.form_list.selection_set(first_form)
            self._on_form_selected()

    def _build_layout(self):
        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        # --- left: forms list ---
        left = ttk.Frame(container)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        ttk.Label(left, text="טפסים", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        self.form_list = ttk.Treeview(left, show="tree", height=15, selectmode="browse")
        self.form_list.pack(fill="y", expand=True)
        for form_name in self.registry:
            self.form_list.insert("", "end", iid=form_name, text=form_name)
        self.form_list.bind("<<TreeviewSelect>>", lambda e: self._on_form_selected())

        ttk.Button(left, text="רענון גיליון", command=self._on_refresh).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="פתח תיקיית פלט", command=self._on_open_output_folder).pack(fill="x", pady=(4, 0))

        # --- right: submissions for the selected form ---
        right = ttk.Frame(container)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self.status_var = StringVar(value="")
        ttk.Label(right, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        columns = ("timestamp", "summary")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("timestamp", text="תאריך שליחה")
        self.tree.heading("summary", text="תוכן ההגשה")
        self.tree.column("timestamp", width=150, anchor="w")
        self.tree.column("summary", width=700, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")

        button_row = ttk.Frame(right)
        button_row.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(button_row, text="צור מסמכים עבור הבחירה", command=self._on_generate).pack(side="left")
        ttk.Label(button_row, text="  (ניתן לבחור כמה שורות עם Ctrl/Shift)").pack(side="left")

        self.log = ttk.Treeview(right, columns=("log",), show="headings", height=6)
        self.log.heading("log", text="יומן פעולות")
        self.log.column("log", width=850, anchor="w")
        self.log.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

    def _current_form_name(self):
        selection = self.form_list.selection()
        return selection[0] if selection else None

    def _log(self, message: str):
        self.log.insert("", "end", values=(message,))
        self.log.yview_moveto(1)

    def _on_form_selected(self):
        self._load_rows_for_current_form()

    def _on_refresh(self):
        self._load_rows_for_current_form()

    def _load_rows_for_current_form(self):
        form_name = self._current_form_name()
        if not form_name:
            return
        form_def = self.registry[form_name]
        self.tree.delete(*self.tree.get_children())
        self.current_rows = []

        sheet_id = form_def.get("sheet_id")
        if not sheet_id:
            self.status_var.set(f"{form_name} - לא הוגדר גיליון עבור טופס זה")
            return

        self.status_var.set(f"{form_name} - טוען הגשות...")
        self.update_idletasks()
        try:
            rows = pipeline.fetch_sheet_rows(sheet_id)
        except Exception as exc:
            self.status_var.set(f"{form_name} - שגיאה בטעינת הגיליון")
            messagebox.showerror("שגיאה בטעינת הגיליון", str(exc))
            return

        rows = [row for row in rows if pipeline.row_matches_filter(row, form_def.get("row_filter"))]
        rows.sort(key=lambda row: _parse_timestamp(row, form_def), reverse=True)
        self.current_rows = rows

        timestamp_column = form_def["timestamp_column"]
        for idx, row in enumerate(rows):
            self.tree.insert(
                "", "end", iid=str(idx),
                values=(row.get(timestamp_column, ""), _row_summary(row, form_def)),
            )
        self.status_var.set(f"{form_name} - {len(rows)} הגשות נמצאו")

    def _on_generate(self):
        form_name = self._current_form_name()
        if not form_name:
            return
        selected_ids = self.tree.selection()
        if not selected_ids:
            messagebox.showwarning("לא נבחרו הגשות", "בחר לפחות הגשה אחת ליצירת מסמך.")
            return

        form_def = self.registry[form_name]
        rows = [self.current_rows[int(i)] for i in selected_ids]

        try:
            all_results = pipeline.fill_rows_with_cascade(form_name, form_def, rows, self.registry)
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("שגיאה ביצירת המסמכים", str(exc))
            return

        total = 0
        for name, results in all_results.items():
            for row, output_path in results:
                self._log(f"[{name}] נוצר: {output_path}")
                total += 1
        messagebox.showinfo("הושלם", f"נוצרו {total} מסמכים בתיקיית output.")

    def _on_open_output_folder(self):
        folder = Path(pipeline.OUTPUT_DIR).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))


def main():
    try:
        app = App()
        app.mainloop()
    except Exception as exc:
        traceback.print_exc()
        messagebox.showerror("שגיאה", f"האפליקציה נתקלה בשגיאה ותיסגר:\n{exc}")


if __name__ == "__main__":
    main()

"""Optional PDF copies of the filled documents, rendered by Microsoft Word
(so the PDF looks exactly like the .docx). Only available on a Windows machine
with Word installed -- not in Docker and not in the Android app."""
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

# 17 = wdExportFormatPDF. Paths travel through a UTF-8 JSON file because they
# are usually Hebrew, which doesn't survive the command line reliably.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$jobs = Get-Content -Raw -Encoding UTF8 -LiteralPath '%s' | ConvertFrom-Json
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    foreach ($job in $jobs) {
        $doc = $word.Documents.Open($job.src, $false, $true)
        try { $doc.ExportAsFixedFormat($job.dst, 17) } finally { $doc.Close($false) }
    }
} finally {
    $word.Quit()
}
"""


def available() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
    except OSError:
        return False
    return True


def convert(docx_paths: list) -> list:
    """Write a .pdf next to each .docx and return the PDF paths. Raises
    RuntimeError if Word couldn't do it."""
    jobs = [
        {"src": str(Path(p).resolve()), "dst": str(Path(p).resolve().with_suffix(".pdf"))}
        for p in docx_paths
    ]
    if not jobs:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)
        jobs_file = f.name
    try:
        script = _SCRIPT % jobs_file.replace("'", "''")
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ],
            capture_output=True,
            timeout=60 + 30 * len(jobs),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc))
    finally:
        os.unlink(jobs_file)
    missing = [job["dst"] for job in jobs if not Path(job["dst"]).is_file()]
    if result.returncode != 0 or missing:
        raise RuntimeError("Word לא הצליח לייצר PDF.")
    return [job["dst"] for job in jobs]

"""Render docs/report/REPORT.md to PDF with a headless Chromium browser (Chrome or Edge).

  uv run --with markdown --with pypdf python scripts/report_pdf.py [--out docs/report/REPORT.pdf]

The page budget is 10 pages; the script prints the page count and exits 1 above it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/report/REPORT.md"
MAX_PAGES = 10

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 9.6pt;
       line-height: 1.38; color: #111; }
h1 { font-size: 16pt; margin: 0 0 6pt; }
h2 { font-size: 12pt; margin: 12pt 0 4pt; border-bottom: 1px solid #bbb; padding-bottom: 2pt;
     break-after: avoid; }
p { margin: 0 0 5pt; }
ul { margin: 0 0 5pt; padding-left: 16pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 7pt; font-size: 8.4pt;
        break-inside: avoid; }
th, td { border: 1px solid #c8c8c8; padding: 2pt 4pt; text-align: left; vertical-align: top; }
th { background: #f0f0f0; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.4pt; }
"""


def browser() -> str:
    candidates = [
        os.environ.get("CHROME", ""),
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    sys.exit("no Chrome or Edge found; set CHROME to a Chromium-based browser")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs/report/REPORT.pdf"))
    args = ap.parse_args()
    body = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    html = (
        f'<!doctype html><html><head><meta charset="utf-8"><title>GigBid R&amp;D report</title>'
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )
    out = Path(args.out).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                browser(),
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={Path(tmp) / 'profile'}",
                f"--print-to-pdf={out}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    pages = len(PdfReader(str(out)).pages)
    print(f"{out}: {pages} pages (budget {MAX_PAGES})")
    if pages > MAX_PAGES:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Render the README's screenshots from a green Windows CI run.

The window shots are the release workflow's own (artifact ``gui-screenshots``,
taken on a 1366x768 screen while it drives the packaged app). The sheet views
are rendered here from that same run's workbooks (artifact ``smoke-test``):
each sheet is copied into a one-sheet workbook, printed to PDF by LibreOffice
with grid lines and row/column headings, rasterised and trimmed.

    gh run download RUN_ID -n gui-screenshots -D shots/gui
    gh run download RUN_ID -n smoke-test -D shots/smoke
    python tools/render_screenshots.py shots

Needs LibreOffice (``soffice``), ``pdftoppm`` (poppler), openpyxl and Pillow.
Writes docs/screenshots/.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"

#: CI window shot -> README name.
WINDOW = {f"{n}-{name}.png": f"window-{n}-{name}.png" for n, name in (
    (1, "empty"), (2, "genomes-loaded"), (3, "settings-open"), (4, "fastq-notice"),
    (5, "running"), (6, "finished"), (7, "databases"))}


def summary_rows(path: Path) -> int:
    """The Summary down to its "Settings used" section (the run details follow)."""
    ws = load_workbook(path)["Summary"]
    labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    return (labels.index("Run") if "Run" in labels else 80) - 1


def jobs(results: Path) -> list[tuple[str, str, int, int, str]]:
    """(workbook, sheet, rows, columns, output name) for every sheet view."""
    return [
        ("HS11286/HS11286.xlsx", "Summary", summary_rows(results / "HS11286/HS11286.xlsx"), 2,
         "02-genome-summary"),
        # Category ... Gene, Confident call, Closest allele, Database, Identity, Coverage
        ("HS11286/HS11286.xlsx", "AMR_genes", 30, 11, "03-genome-amr-genes"),
        ("HS11286/HS11286.xlsx", "Point_mutations", 6, 15, "04-genome-point-mutations"),
        ("HS11286/HS11286.xlsx", "Plasmids", 6, 11, "05-genome-plasmids"),
        ("HS11286/HS11286.xlsx", "Pivot", 48, 16, "06-genome-pivot"),
        ("Cumulative_results.xlsx", "Summary", 4, 12, "07-cumulative-summary"),
        ("Cumulative_results.xlsx", "AMR_matrix", 5, 34, "08-cumulative-amr-matrix"),
        ("Cumulative_results.xlsx", "Mutations_matrix", 6, 14, "09-cumulative-mutations-matrix"),
        # The Typing sheet's header is row 4, under two explanatory rows.
        ("USA300/USA300.xlsx", "Typing", 20, 8, "10-genome-typing"),
        ("Cumulative_results.xlsx", "Typing_matrix", 5, 20, "11-cumulative-typing-matrix"),
    ]


def trim(img: Image.Image, pad: int = 12) -> Image.Image:
    box = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, "white")).getbbox()
    if not box:
        return img
    left, top, right, bottom = box
    return img.crop((max(left - pad, 0), max(top - pad, 0),
                     min(right + pad, img.width), min(bottom + pad, img.height)))


def render(results: Path, tmp: Path) -> None:
    for book, sheet, rows, cols, name in jobs(results):
        wb = load_workbook(results / book)
        for ws in list(wb):
            if ws.title != sheet:
                wb.remove(ws)
        ws = wb[sheet]
        rows, cols = min(rows, ws.max_row), min(cols, ws.max_column)
        ws.print_area = f"A1:{get_column_letter(cols)}{rows}"
        ws.page_setup.orientation = "portrait" if sheet == "Summary" else "landscape"
        ws.page_setup.paperSize = 8  # A3
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.print_options.gridLines = True
        ws.print_options.headings = True
        for side in ("left", "right", "top", "bottom"):
            setattr(ws.page_margins, side, 0.25)
        src = tmp / f"{name}.xlsx"
        wb.save(src)
        subprocess.run(["soffice", f"-env:UserInstallation=file://{tmp}/lo", "--headless",
                        "--convert-to", "pdf", "--outdir", str(tmp), str(src)],
                       check=True, capture_output=True, timeout=180)
        subprocess.run(["pdftoppm", "-png", "-r", "130", "-f", "1", "-l", "1", "-singlefile",
                        str(tmp / f"{name}.pdf"), str(tmp / name)], check=True)
        img = trim(Image.open(tmp / f"{name}.png"))
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name}.png {img.size[0]}x{img.size[1]}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    shots = Path(argv[0])
    results = next(shots.glob("smoke/**/smoke-results"), None)
    if results is None:
        print(f"no smoke-results folder under {shots}/smoke")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst in WINDOW.items():
        shutil.copy2(shots / "gui" / src, OUT / dst)
        print(dst)
    with tempfile.TemporaryDirectory() as tmp:
        render(results, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Recalculate the latest extract in two templates (e.g. original vs fixed) and list score changes.

    python compare_scores.py "templates/002 - Safety Health Report.xlsx" "templates/002 - Safety Health Report (fixed).xlsx"
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from build_workbook import load_csvs, skipped_projects  # noqa: E402
from common import ROOT, load_config  # noqa: E402
from recalc import recalc_libreoffice  # noqa: E402
from tabs import TABS  # noqa: E402
from workbook_writer import read_template_rows, write_workbook  # noqa: E402

COLS = {"E": "Overall Score", "AA": "Score4 (Daily)", "AG": "Score2 (Surveys)", "AK": "Score3 (Obs)", "AO": "Score (UTV)",
        "AB": "Total3 Closed", "AC": "Open", "AH": "Total2", "AI": "Open2"}


def latest_csv_dir(cfg, date=None) -> Path:
    base = ROOT / cfg["output_dir"]
    if date:
        return base / date / "csv"
    dirs = sorted(p for p in base.glob("*/csv") if (p / "daily_log.csv").exists())
    return dirs[-1]


def values(template: Path, data: dict, work: Path, tag: str, shrink: bool) -> dict:
    import openpyxl
    warnings.filterwarnings("ignore", module="openpyxl")
    out = work / f"{tag}.xlsx"
    write_workbook(template, out, data, shrink_all=shrink, numeric_project_number=True)
    calc = recalc_libreoffice(out, work)
    wb = openpyxl.load_workbook(calc, data_only=True)
    ws, sc = wb["Safety Health Report"], wb["Scorecard"]
    rows = {}
    for r in range(20, ws.max_row + 1):
        if ws[f"A{r}"].value is None:
            continue
        rows[r] = {"Project #": ws[f"A{r}"].value, "Name": ws[f"C{r}"].value, **{c: ws[f"{c}{r}"].value for c in COLS}}
    scorecard = {(r, c): sc[f"{c}{r}"].value for r in range(5, 46) for c in "ABCDEGHJKMNPQ"}
    return {"table1": rows, "scorecard": scorecard}


SCORE_COLS = {"E", "AA", "AG", "AK", "AO"}


def fmt(v, col=""):
    if col in SCORE_COLS and isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:.1%}"
    if isinstance(v, float):
        return f"{v:.1f}"
    return "" if v is None else str(v)


def compare(original: Path, fixed: Path, cfg: dict, date: str | None = None) -> str:
    csv_dir = latest_csv_dir(cfg, date)
    data = load_csvs(csv_dir)
    carry = skipped_projects(csv_dir)
    for key in TABS:
        data[key] += read_template_rows(original, key, carry) if carry else []
    with tempfile.TemporaryDirectory() as tmp:
        a = values(original, data, Path(tmp), "original", shrink=False)
        b = values(fixed, data, Path(tmp), "fixed", shrink=True)
    lines = [f"Score comparison using {csv_dir} (LibreOffice, numeric verification copies)", "",
             "| Project | Name | " + " | ".join(COLS.values()) + " |", "|" + "---|" * (len(COLS) + 2)]
    changed = 0
    for r, row in a["table1"].items():
        nb = b["table1"].get(r, {})
        cells = []
        diff = False
        for c in COLS:
            x, y = row.get(c), nb.get(c)
            same = x == y or (isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) < 1e-9)
            cells.append(fmt(x, c) if same else f"**{fmt(x, c)} → {fmt(y, c)}**")
            diff |= not same
        changed += diff
        lines.append(f"| {row['Project #']} | {row['Name']} | " + " | ".join(cells) + " |")
    sc_err = sum(1 for v in a["scorecard"].values() if isinstance(v, str) and v.startswith("#"))
    sc_err_b = sum(1 for v in b["scorecard"].values() if isinstance(v, str) and v.startswith("#"))
    lines += ["", f"Projects with any change: {changed}", f"Scorecard error cells: {sc_err} → {sc_err_b}"]
    text = "\n".join(lines)
    out = csv_dir.parent / "score_comparison.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nSaved {out}")
    return text


if __name__ == "__main__":
    cfg = load_config()
    compare(Path(sys.argv[1]), Path(sys.argv[2]), cfg, sys.argv[3] if len(sys.argv) > 3 else None)

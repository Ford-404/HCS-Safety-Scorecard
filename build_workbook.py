"""Stage 4: write the extracted CSVs into a copy of the template, recalculate, and check for errors.

    python build_workbook.py                     # uses output/<today>/csv
    python build_workbook.py --date 2026-11-09

Output: output/Safety Health Report YYYY-MM-DD.xlsx and output/<date>/checks.txt
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import shutil
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from common import ROOT, load_config, project_number_of, read_table1, setup_logging  # noqa: E402
from recalc import excel_available, recalc  # noqa: E402
from tabs import TABS  # noqa: E402
from workbook_writer import read_template_rows, write_workbook  # noqa: E402

log = logging.getLogger("build")
ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#NAME?", "#NUM!", "#NULL!")
CHECK_SHEETS = ("Safety Health Report", "Scorecard")


def load_csvs(csv_dir: Path) -> dict:
    data = {}
    for key, spec in TABS.items():
        rows = []
        with open(csv_dir / f"{key}.csv", encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                for c in spec.get("date_columns", []):
                    r[c] = dt.date.fromisoformat(r[c]) if r.get(c) else None
                for c in spec.get("int_columns", []):
                    r[c] = int(r[c]) if r.get(c) not in (None, "") else None
                for c in spec["columns"]:
                    if r.get(c) == "":
                        r[c] = None
                rows.append(r)
        data[key] = rows
    return data


def skipped_projects(csv_dir: Path) -> set[str]:
    """Table1 projects the extract could not read (not visible to the app)."""
    p = csv_dir / "problems.txt"
    out = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "not visible to the Procore app" in line:
                out.add(line.split()[0])
    return out


def sheet_values(path: Path) -> dict:
    import openpyxl
    warnings.filterwarnings("ignore", module="openpyxl")
    wb = openpyxl.load_workbook(path, data_only=True)
    out = {}
    for name in CHECK_SHEETS:
        ws = wb[name]
        out[name] = {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None}
    return out


def find_errors(values: dict) -> dict:
    return {s: sorted((k for k, v in cells.items() if isinstance(v, str) and v.strip() in ERRORS), key=_cell_key)
            for s, cells in values.items()}


def _cell_key(ref):
    import re
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (int(m.group(2)), len(m.group(1)), m.group(1))


def consistency_checks(values: dict, data: dict, table1: list[dict]) -> list[str]:
    """Confirm the COUNTIFS in Table1 really match the text project numbers we wrote."""
    shr = values["Safety Health Report"]
    out = []
    count = lambda key, pn, **f: sum(1 for r in data[key] if r["Project Number"] == pn and all(r.get(k) == v for k, v in f.items()))
    for row in table1:
        pn = project_number_of(row)
        if not pn:
            continue
        r = row["_row"]
        checks = [("AP", "Forms Started", count("incident_forms", pn)),
                  ("AQ", "Reports Started", count("incidents", pn)),
                  ("AR", "Reports Open", count("incidents", pn, Status="Open"))]
        for col, label, expected in checks:
            got = shr.get(f"{col}{r}")
            if got != expected:
                out.append(f"{pn} {label} ({col}{r}): workbook={got} data={expected}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="run date YYYY-MM-DD (default today)")
    ap.add_argument("--csv-dir", help="folder with the six CSVs (default output/<date>/csv)")
    args = ap.parse_args(argv)
    cfg = load_config()
    setup_logging("build")
    run_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    template = ROOT / cfg["template"]
    out_root = ROOT / cfg["output_dir"]
    run_dir = out_root / run_date.isoformat()
    csv_dir = Path(args.csv_dir) if args.csv_dir else run_dir / "csv"
    final = out_root / f"Safety Health Report {run_date.isoformat()}.xlsx"
    scratch = run_dir / "_work"
    scratch.mkdir(parents=True, exist_ok=True)

    data = load_csvs(csv_dir)
    table1 = read_table1(template)
    notes = []

    # Projects in Table1 that the Procore app cannot see: keep their existing rows from the template
    carry = skipped_projects(csv_dir)
    if carry:
        for key in TABS:
            old = read_template_rows(template, key, carry)
            data[key].extend(old)
            if old:
                notes.append(f"Carried forward {len(old)} existing {key} rows for {', '.join(sorted(carry))} (not visible to the Procore app)")

    shrink = bool(cfg["workbook"].get("shrink_all_tables"))
    engine = cfg["workbook"].get("recalc_engine", "auto")
    refs = write_workbook(template, final, data, shrink_all=shrink)
    log.info("Wrote %s (%.1f MB)", final.name, final.stat().st_size / 1e6)

    if engine in ("auto", "excel") and excel_available():
        used, calc_path = recalc(final, "excel", scratch)
        values = sheet_values(final)
    elif engine == "none":
        used, values = "none", None
    else:
        # LibreOffice does not match text project numbers ("401814") against Table1's numbers the
        # way Excel does, so recalculate a verification copy with numeric project numbers.
        twin = scratch / "verify_numeric.xlsx"
        write_workbook(template, twin, data, shrink_all=shrink, numeric_project_number=True)
        used, calc_path = recalc(twin, "libreoffice", scratch)
        values = sheet_values(calc_path)
        # Store the recalculated values as the file's cached values (Excel still recalculates on open)
        write_workbook(template, final, data, shrink_all=shrink, cached_values=values)
        notes.append("Recalculated with LibreOffice (verification copy with numeric project numbers); "
                     "values stored in the workbook, and Excel recalculates again on open.")

    lines = [f"Safety Health Report build {run_date.isoformat()}", f"Workbook: {final}",
             f"Size: {final.stat().st_size / 1e6:.2f} MB", f"Recalc engine: {used}", "",
             "Table refs: " + ", ".join(f"{k}={v}" for k, v in refs.items()),
             "Rows: " + ", ".join(f"{k}={len(v)}" for k, v in data.items()), ""]
    lines += notes
    status = "OK"
    if values:
        import openpyxl  # baseline: errors already present in the template as last saved by Excel
        warnings.filterwarnings("ignore", module="openpyxl")
        base = find_errors(sheet_values(template))
        errs = find_errors(values)
        for sheet in CHECK_SHEETS:
            new = [c for c in errs[sheet] if c not in base[sheet]]
            pre = [c for c in errs[sheet] if c in base[sheet]]
            lines.append(f"\n{sheet}: {len(errs[sheet])} error cells ({len(pre)} already in template, {len(new)} new)")
            if new:
                status = "ERRORS"
                lines.append("  NEW: " + ", ".join(f"{c}={values[sheet][c]}" for c in new[:60]))
            if pre:
                lines.append("  pre-existing: " + ", ".join(pre[:60]) + (" ..." if len(pre) > 60 else ""))
        mism = consistency_checks(values, data, table1)
        lines.append(f"\nCOUNTIF match check (Forms/Reports per project vs data): {'all match' if not mism else str(len(mism)) + ' mismatches'}")
        lines += ["  " + m for m in mism]
        if mism:
            status = "ERRORS"
        (run_dir / "table1_values.json").write_text(json.dumps(values, default=str, indent=0), encoding="utf-8")
    lines.insert(1, f"Status: {status}")
    (run_dir / "checks.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for l in lines:
        log.info(l)
    shutil.rmtree(scratch, ignore_errors=True)
    return final, status, values


if __name__ == "__main__":
    main()

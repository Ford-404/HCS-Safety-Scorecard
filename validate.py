"""Stage 3: compare extracted CSVs with the data tabs currently in the template (the manual export).

    python validate.py [--date YYYY-MM-DD]

Writes output/<date>/validation_report.md. Every difference is put in a category:
  newer          record dated after the manual export was taken (expected)
  changed        same record, a field changed in Procore since the export (e.g. closed since)
  only_template  in the export but not returned by Procore today (deleted, renumbered, or outside the
                 date range the script pulls, e.g. daily logs before the Mobilization Date)
  only_api       returned by Procore, dated before the export, but not in the export
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from build_workbook import load_csvs  # noqa: E402
from common import ROOT, load_config, project_number_of, read_table1, setup_logging  # noqa: E402
from tabs import TABS  # noqa: E402
from workbook_writer import read_template_rows  # noqa: E402

# key used to pair a template row with an API row, the date that defines "newer", fields compared
SPEC = {
    "daily_log": (lambda r: str(r["Date"]), "Date", ["Completed?"]),
    "safety_survey": (lambda r: str(r["Inspection #"]), "Due Date",
                      ["Status", "Date Closed", "Closed By", "Assignee(s)", "No Response", "# Of Observations", "At Risk Items", "Due Date"]),
    "observations": (lambda r: str(r["#"]), "Date Created", ["Category", "Status", "Date Created", "Column3"]),
    "utv": (lambda r: f'{r["Date Created"]}', "Date Created", ["Status", "Date Closed", "Created By", "Closed By"]),
    "incident_forms": (lambda r: f'{r["Date"]}|{(r["Title"] or "").strip()}', "Date", ["Description"]),
    "incidents": (lambda r: str(r["#"]), "Incident Date", ["Status", "Incident Date", "Title", "Recordable"]),
}


def norm(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        v = " ".join(v.replace("\xa0", " ").split())
        return v or None
    return v


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--csv-dir")
    args = ap.parse_args(argv)
    cfg = load_config()
    setup_logging("validate")
    run_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    run_dir = ROOT / cfg["output_dir"] / run_date.isoformat()
    csv_dir = Path(args.csv_dir) if args.csv_dir else run_dir / "csv"
    template = ROOT / cfg["template"]
    api = load_csvs(csv_dir)
    table1 = read_table1(template)
    pns = [p for p in dict.fromkeys(project_number_of(r) for r in table1) if p]
    extracted = {r["Project Number"] for rows in api.values() for r in rows}
    old = {k: [r for r in read_template_rows(template, k, set(pns))] for k in TABS}
    # Each tab was exported on its own day: cutoff = latest date in that tab (Table1 projects only)
    cutoffs = {k: max((norm(r.get(SPEC[k][1])) for r in old[k] if norm(r.get(SPEC[k][1]))), default=run_date) for k in TABS}
    mob = {project_number_of(r): norm(r.get("Mobilization Date")) for r in table1 if project_number_of(r)}

    out = [f"# Stage 3 validation: Procore API vs manual export", "",
           f"Run {run_date}. Each data tab in the template was exported on its own date; the latest date in each tab is used as its "
           f"cutoff (" + ", ".join(f"{k} {v}" for k, v in cutoffs.items()) + "), so records after that are expected to be new. Only Table1 projects are compared "
           f"(the export also holds rows for {len({str(r['Project Number']) for k in TABS for r in read_template_rows(template, k, None)} - set(pns))} projects that are not in Table1; the formulas never read them).", ""]
    totals = collections.Counter()
    details = []
    summary_rows = []
    for key, spec in TABS.items():
        keyf, datef, fields = SPEC[key]
        cutoff = cutoffs[key]
        for pn in pns:
            if pn not in extracted:
                continue
            t_rows = [r for r in old[key] if str(r["Project Number"]) == pn]
            a_rows = [r for r in api[key] if r["Project Number"] == pn]
            t_map = {keyf(r): r for r in t_rows}
            a_map = {keyf(r): r for r in a_rows}
            cats = collections.Counter()
            notes = []
            for k, a in a_map.items():
                d = norm(a.get(datef)) or norm(a.get("Date Closed"))
                if k in t_map:
                    t = t_map[k]
                    for f in fields:
                        if norm(t.get(f)) != norm(a.get(f)):
                            cats["changed"] += 1
                            notes.append(f"{key} {pn} [{k}] {f}: export={norm(t.get(f))!r} → procore={norm(a.get(f))!r}")
                elif d and d > cutoff:
                    cats["newer"] += 1
                else:
                    cats["only_api"] += 1
                    notes.append(f"{key} {pn} [{k}] in Procore (dated {d}) but not in export")
            for k, t in t_map.items():
                if k not in a_map:
                    d = norm(t.get(datef))
                    why = ""
                    if key == "daily_log" and mob.get(pn) and d and d < mob[pn]:
                        why = " (before Mobilization Date - not pulled; does not affect scores)"
                        cats["only_template_before_mob"] += 1
                    else:
                        cats["only_template"] += 1
                    notes.append(f"{key} {pn} [{k}] in export (dated {d}) but not returned by Procore{why}")
            t_dates = [norm(r.get(datef)) for r in t_rows if norm(r.get(datef))]
            a_dates = [norm(r.get(datef)) for r in a_rows if norm(r.get(datef)) and norm(r.get(datef)) <= cutoff]
            st = lambda rows: dict(collections.Counter(norm(r.get("Status")) for r in rows)) if "Status" in spec["columns"] else ""
            if t_rows or a_rows:
                summary_rows.append((key, pn, len(t_rows), len(a_rows), sum(1 for r in a_rows if norm(r.get(datef)) and norm(r.get(datef)) <= cutoff),
                                     f"{min(t_dates) if t_dates else ''}–{max(t_dates) if t_dates else ''}",
                                     f"{min(a_dates) if a_dates else ''}–{max(a_dates) if a_dates else ''}",
                                     st(t_rows), st([r for r in a_rows if norm(r.get(datef)) and norm(r.get(datef)) <= cutoff]), dict(cats)))
            totals.update({f"{key}:{c}": n for c, n in cats.items()})
            details += notes

    out.append("## Totals by category")
    out.append("")
    out.append("| Tab | newer | changed | only in export | only in export (before mobilization) | only in Procore |")
    out.append("|---|---|---|---|---|---|")
    for key in TABS:
        g = lambda c: totals.get(f"{key}:{c}", 0)
        out.append(f"| {key} | {g('newer')} | {g('changed')} | {g('only_template')} | {g('only_template_before_mob')} | {g('only_api')} |")
    out += ["", "## By project", "",
            "| Tab | Project | Export rows | Procore rows (all) | Procore rows ≤ export date | Export date range | Procore date range (≤ export) | Export status counts | Procore status counts (≤ export) | Differences |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary_rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    out += ["", "## Every difference (excluding 'newer')", ""]
    out += [f"- {n}" for n in details] or ["(none)"]
    path = run_dir / "validation_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Validation report: {path}")
    for key in TABS:
        print(key, {c.split(':')[1]: n for c, n in totals.items() if c.startswith(key + ':')})
    return path


if __name__ == "__main__":
    main()

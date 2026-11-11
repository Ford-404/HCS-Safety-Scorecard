"""Send the most recent scorecard email again, without calling Procore.

Uses the latest output/Safety Health Report <date>.xlsx (and output/<date>/table1_values.json if present),
and sends through the method in config.yaml (Outlook by default) to email.to.

    python send_test_email.py              # latest run
    python send_test_email.py --date 2026-11-10
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from common import ROOT, load_config  # noqa: E402
from emailer import build_html, send, table1_rows  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="which run to send (default: latest in output/)")
    args = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    out = ROOT / cfg["output_dir"]
    # Runs are found by their workbook (output/Safety Health Report YYYY-MM-DD.xlsx)
    runs = sorted(p.stem.replace("Safety Health Report ", "") for p in out.glob("Safety Health Report *.xlsx"))
    if not runs:
        print(f"No workbook found. Put 'Safety Health Report YYYY-MM-DD.xlsx' in {out}")
        return 1
    run = args.date or runs[-1]
    workbook = out / f"Safety Health Report {run}.xlsx"
    values_file = out / run / "table1_values.json"
    if values_file.exists():
        values = json.loads(values_file.read_text(encoding="utf-8"))
    else:  # read the scores stored in the workbook itself
        from build_workbook import sheet_values
        values = sheet_values(workbook)
    print(f"Sending the scorecard from {workbook.name}")
    run_date = dt.date.fromisoformat(run[:10])
    body = build_html(table1_rows(values), run_date, cfg["report"].get("score_threshold"),
                      ["Test send: this is the scorecard from an earlier run, re-sent without pulling new Procore data."])
    subject = "[TEST] " + cfg["report"]["subject"].format(date=run_date.strftime("%m/%d/%Y"))
    cfg["email"]["enabled"] = True  # this script exists to send
    print(send(cfg, subject, body, workbook, out / run))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Weekly run: Procore -> CSVs -> workbook -> recalculate -> checks -> email.

    python run_weekly.py              # the scheduled command
    python run_weekly.py --no-email   # build everything, do not send (still saves email preview)

Exit code 0 = report built (and sent if enabled); 1 = failed (a failure notice is emailed if email is enabled).
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from common import ROOT, load_config, setup_logging  # noqa: E402

log = logging.getLogger("weekly")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--date", help="run date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    run_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    lock = ROOT / "data" / "run.lock"
    lock.parent.mkdir(exist_ok=True)
    if lock.exists() and (dt.datetime.now().timestamp() - lock.stat().st_mtime) < 6 * 3600:
        print("Another run is in progress (data/run.lock). Exiting.")
        return 1
    lock.write_text(str(os.getpid()))
    try:
        import build_workbook
        import extract
        from emailer import build_html, send, table1_rows

        ex, csv_dir = extract.main(["--date", run_date.isoformat()])
        log_path = setup_logging("weekly")
        final, status, values = build_workbook.main(["--date", run_date.isoformat()])
        run_dir = ROOT / cfg["output_dir"] / run_date.isoformat()
        if status != "OK":
            raise RuntimeError(f"workbook checks failed, see {run_dir / 'checks.txt'}")
        notes = [n.replace("not visible to the Procore app - skipped", "not visible to the Procore app - last export's rows carried forward")
                 for n in ex.problems]
        threshold = cfg["report"].get("score_threshold")
        body = build_html(table1_rows(values), run_date, threshold, notes)
        subject = cfg["report"]["subject"].format(date=run_date.strftime("%m/%d/%Y"))
        if args.no_email:
            cfg["email"]["enabled"] = False
        result = send(cfg, subject, body, final, run_dir)
        log.info("Email: %s", result)
        log.info("Done: %s", final)
        return 0
    except Exception as exc:  # noqa: BLE001
        logging.getLogger().exception("Weekly run failed")
        try:
            if cfg["email"].get("enabled") and not args.no_email:
                from emailer import send
                # Failure notices go only to email.failure_to (falls back to email.to if not set)
                cfg["email"] = {**cfg["email"], "to": cfg["email"].get("failure_to") or cfg["email"]["to"], "cc": []}
                body =(f"<p>The HCS Safety Health Report run for {run_date} failed:</p><pre>{exc}</pre>"
                        f"<pre style='color:#666'>{traceback.format_exc()[-3000:]}</pre><p>Logs are in {ROOT / 'logs'} on the report PC.</p>")
                send(cfg, f"FAILED: HCS Safety Health Report {run_date}", body, None, ROOT / cfg["output_dir"] / run_date.isoformat())
        except Exception:  # noqa: BLE001
            logging.getLogger().exception("Could not send failure notice")
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

"""Stage 2: pull the six Procore data sets for every Table1 project and write one CSV per tab.

Read-only: only GET requests are sent to the Procore API.

    python extract.py                 # all Table1 projects -> output/<date>/csv/*.csv
    python extract.py --only 401814   # one or more projects (for testing)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from common import ROOT, html_to_text, load_config, project_number_of, read_table1, setup_logging, to_local_date  # noqa: E402
from procore_client import ProcoreClient, ProcoreError  # noqa: E402
from tabs import TABS  # noqa: E402

log = logging.getLogger("extract")

OBS_STATUS = {"initiated": "Initiated", "ready_for_review": "Ready For Review", "not_accepted": "Not Accepted",
              "closed": "Closed", "open": "Open"}


def title_status(s) -> str:
    if not s:
        return ""
    s = str(s)
    return OBS_STATUS.get(s, s.replace("_", " ").title() if s.islower() else s)


def name_of(person) -> str:
    return (person or {}).get("name") or ""


class Extractor:
    def __init__(self, cfg: dict, client: ProcoreClient, run_date: dt.date):
        self.cfg = cfg
        self.c = client
        self.tz = cfg["timezone"]
        self.today = run_date
        self.rows = {k: [] for k in TABS}
        self.counts = []      # (project #, tool, count / status)
        self.problems = []    # human-readable list of skips and failures
        pc = cfg["procore"]
        self.survey_tpl = set(pc["safety_survey_templates"])
        self.utv_tpl = set(pc["utv_templates"])
        self.form_tpl = set(pc["incident_form_templates"])
        self.obs_cf = pc["observation_type_custom_field"]
        dl = cfg["daily_log"]
        self.cache_path = ROOT / dl["cache_file"]
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    # ---------------------------------------------------------------- per tool
    def inspections(self, pid, pn, pname, region):
        lists = self.c.get_all(f"/rest/v1.0/projects/{pid}/checklist/lists")
        lists = [x for x in lists if not x.get("deleted")]
        surveys = sorted((x for x in lists if x.get("list_template_name") in self.survey_tpl),
                         key=lambda x: (int(x["identifier"]) if str(x.get("identifier") or "").isdigit() else 10**9, x.get("number") or 0))
        utvs = sorted((x for x in lists if x.get("list_template_name") in self.utv_tpl), key=lambda x: x.get("created_at") or "")
        for x in surveys:
            self.rows["safety_survey"].append({
                "Project Number": pn,
                "Inspection Template Name": x.get("list_template_name"),
                "Project Name": pname,
                # identifier is the number users see in Procore (and in the manual export); `number` is internal
                "Inspection #": str(x.get("identifier") or x.get("number") or ""),
                "Assignee(s)": ", ".join(name_of(i) for i in (x.get("inspectors") or [])),
                "No Response": max(0, (x.get("item_count") or 0) - (x.get("inspected_item_count") or 0)),
                "Due Date": to_local_date(x.get("due_at"), self.tz),
                "Status": x.get("status") or "",
                "Date Closed": to_local_date(x.get("closed_at"), self.tz),
                "Closed By": name_of(x.get("closed_by")),
                "Project Region": region,
                "# Of Observations": x.get("observations_count") or 0,
                "At Risk Items": x.get("deficient_item_count") or 0,
            })
        for x in utvs:
            self.rows["utv"].append({
                "Inspection Template Name": x.get("list_template_name"),
                "Project Number": pn,
                "Project Name": pname,
                "Status": x.get("status") or "",
                "Date Created": to_local_date(x.get("created_at"), self.tz),
                "Date Closed": to_local_date(x.get("closed_at"), self.tz),
                "Created By": name_of(x.get("created_by")),
                "Closed By": name_of(x.get("closed_by")),
            })
        return len(surveys), len(utvs)

    def observations(self, pid, pn, pname):
        items = [o for o in self.c.get_all("/rest/v1.0/observations/items", {"project_id": pid}) if not o.get("deleted_at")]
        items.sort(key=lambda o: int(o["number"]) if str(o.get("number", "")).isdigit() else 0)
        for o in items:
            t = o.get("type") or {}
            cf = ((o.get("custom_fields") or {}).get(self.obs_cf) or {}).get("value")
            label = cf.get("label", "") if isinstance(cf, dict) else (cf or "")
            category = t.get("category") or ((o.get("category") or {}).get("name") or "").replace("_", " ").title()
            self.rows["observations"].append({
                "Project Number": pn, "Project Name": pname, "#": str(o.get("number") or ""),
                "Category": category, "Status": title_status(o.get("status")),
                "Date Created": to_local_date(o.get("created_at"), self.tz),
                "Column3": label, "Column2": None, "Column1": None,  # Column1 = formula, written by the workbook step
            })
        return len(items)

    def incidents(self, pid, pn, pname):
        items = [i for i in self.c.get_all(f"/rest/v1.0/projects/{pid}/incidents") if not i.get("deleted_at")]
        items.sort(key=lambda i: int(i["number"]) if str(i.get("number", "")).isdigit() else 0)
        for i in items:
            self.rows["incidents"].append({
                "Project Number": pn, "Project Name": pname, "#": str(i.get("number") or ""),
                "Status": title_status(i.get("status")),
                "Incident Date": to_local_date(i.get("event_date"), self.tz),
                "Title": i.get("title") or "",
                "Recordable": "Yes" if i.get("recordable") else "No",
                "Description": html_to_text(i.get("description")),
            })
        return len(items)

    def incident_forms(self, pid, pn, pname):
        forms = [f for f in self.c.get_all(f"/rest/v1.0/projects/{pid}/forms")
                 if not f.get("deleted") and f.get("form_template_name") in self.form_tpl]
        forms.sort(key=lambda f: f.get("created_at") or "")
        for f in forms:
            self.rows["incident_forms"].append({
                "Template Name": f.get("form_template_name"), "Project Number": pn, "Project Name": pname,
                "Date": to_local_date(f.get("created_at"), self.tz),
                "Title": f.get("name") or "", "Description": f.get("description") or "",
            })
        return len(forms)

    def daily_logs(self, pid, pn, pname, start: dt.date):
        """Completed daily logs only (matches the manual export, and Table1 counts every row).

        The header endpoint takes a single date, so completion status is cached in
        data/daily_log_cache.json. A completed day is final; days not yet completed are
        re-checked while they are within `refresh_days`.
        """
        refresh_from = self.today - dt.timedelta(days=self.cfg["daily_log"]["refresh_days"])
        cache = self.cache.setdefault(pn, {})
        fetched = 0
        d = start
        while d <= self.today:
            key = d.isoformat()
            if key not in cache or (cache[key] is False and d >= refresh_from):
                try:
                    h = self.c.get(f"/rest/v1.0/projects/{pid}/daily_log_headers", {"log_date": key})
                    cache[key] = bool(h.get("completed"))
                except ProcoreError as e:
                    if e.status != 404:  # 404 = no header for that date
                        raise
                    cache[key] = False
                fetched += 1
                if fetched % 100 == 0:
                    self.save_cache()
                    log.info("  %s daily logs: %s dates checked so far (up to %s)", pn, fetched, key)
            d += dt.timedelta(days=1)
        done = sorted(k for k, v in cache.items() if v and start.isoformat() <= k <= self.today.isoformat())
        for k in done:
            self.rows["daily_log"].append({"Project Number": pn, "Project Name": pname,
                                           "Date": dt.date.fromisoformat(k), "Completed?": "Yes"})
        return len(done), fetched

    def save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=0, sort_keys=True))
        tmp.replace(self.cache_path)

    # ---------------------------------------------------------------- driver
    def run(self, table1: list[dict], only: set[str] | None):
        projects = self.c.get_all("/rest/v1.0/projects", {"company_id": self.c.company_id, "filters[by_status]": "All"}, per_page=300)
        by_number = {}
        for p in projects:
            by_number.setdefault(str(p.get("project_number") or "").strip(), p)
        seen = set()
        skip = {str(s) for s in self.cfg.get("skip_projects") or []}
        region_map = self.cfg.get("region_map") or {}
        for row in table1:
            pn = project_number_of(row)
            raw = row.get("Project #")
            if pn is None:
                if raw not in (None, ""):
                    self.problems.append(f"Table1 row {row['_row']}: project number '{raw}' ({row.get('Project Name')}) is not a number - skipped")
                continue
            if pn in seen or (only and pn not in only):
                continue
            seen.add(pn)
            if pn in skip:
                self.problems.append(f"{pn}: in skip_projects - skipped")
                continue
            p = by_number.get(pn)
            if not p:
                self.problems.append(f"{pn} ({row.get('Project Name')}): not visible to the Procore app - skipped")
                log.warning("%s not visible to the Procore app - skipped", pn)
                continue
            pid = p["id"]
            try:
                detail = self.c.get(f"/rest/v1.0/projects/{pid}", {"company_id": self.c.company_id})
            except ProcoreError as e:
                self.problems.append(f"{pn}: project detail failed (HTTP {e.status}) - skipped")
                continue
            pname = detail.get("name") or p.get("name")
            # Dates are shown in the project's own time zone in Procore (and in the manual export)
            self.tz = detail.get("tz_name") or self.cfg["timezone"]
            region = (detail.get("project_region") or {}).get("name") or ""
            mapped = region_map.get(region)
            if row.get("Region") and mapped and mapped != row.get("Region"):
                self.problems.append(f"{pn}: Procore region '{region}' maps to '{mapped}' but Table1 says '{row.get('Region')}'")
            log.info("Project %s %s (Procore id %s, %s)", pn, pname, pid, region)

            mob = row.get("Mobilization Date")
            start = mob.date() if isinstance(mob, dt.datetime) else (mob if isinstance(mob, dt.date) else
                                                                    self.today - dt.timedelta(days=self.cfg["daily_log"]["default_lookback_days"]))
            tools = [
                ("inspections", lambda: self.inspections(pid, pn, pname, region)),
                ("observations", lambda: self.observations(pid, pn, pname)),
                ("incidents", lambda: self.incidents(pid, pn, pname)),
                ("incident_forms", lambda: self.incident_forms(pid, pn, pname)),
                ("daily_log", lambda: self.daily_logs(pid, pn, pname, start)),
            ]
            for tool, fn in tools:
                try:
                    n = fn()
                except ProcoreError as e:
                    msg = f"{pn} {tool}: HTTP {e.status} - {'no access' if e.status in (401, 403) else 'failed'}"
                    self.problems.append(msg)
                    self.counts.append((pn, pname, tool, f"ERROR {e.status}"))
                    log.error(msg)
                    continue
                if tool == "inspections":
                    self.counts += [(pn, pname, "safety_survey", n[0]), (pn, pname, "utv", n[1])]
                    log.info("  safety_survey=%s utv=%s", *n)
                elif tool == "daily_log":
                    self.counts.append((pn, pname, "daily_log", n[0]))
                    log.info("  daily_log completed=%s (%s dates fetched, from %s)", n[0], n[1], start)
                else:
                    self.counts.append((pn, pname, tool, n))
                    log.info("  %s=%s", tool, n)
            self.save_cache()
        self.save_cache()


def write_csvs(rows: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, spec in TABS.items():
        with open(out_dir / f"{key}.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=spec["columns"])
            w.writeheader()
            for r in rows[key]:
                w.writerow({k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in r.items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="project numbers to extract (default: all in Table1)")
    ap.add_argument("--date", help="run date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    cfg = load_config()
    log_path = setup_logging("extract")
    run_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    template = ROOT / cfg["template"]
    table1 = read_table1(template)
    client = ProcoreClient(str(ROOT / ".env"))
    ex = Extractor(cfg, client, run_date)
    ex.run(table1, set(args.only) if args.only else None)

    out_dir = ROOT / cfg["output_dir"] / run_date.isoformat() / "csv"
    write_csvs(ex.rows, out_dir)
    with open(ROOT / "logs" / f"counts_{run_date.isoformat()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Project Number", "Project Name", "Tool", "Records"])
        w.writerows(ex.counts)
    (out_dir / "problems.txt").write_text("\n".join(ex.problems) + ("\n" if ex.problems else ""), encoding="utf-8")
    log.info("Totals: %s", {k: len(v) for k, v in ex.rows.items()})
    log.info("API requests: %s", client.request_count)
    for p in ex.problems:
        log.warning("PROBLEM: %s", p)
    log.info("CSVs in %s, log %s", out_dir, log_path)
    return ex, out_dir


if __name__ == "__main__":
    main()

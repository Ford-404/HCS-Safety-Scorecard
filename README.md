# HCS Safety Health Report automation

Every week this pulls safety data from Procore (read-only), writes it into the Safety Health Report
workbook, recalculates it, and emails the scores plus the workbook. The workbook's formulas and
scoring logic are unchanged. The script replaces the manual Procore export and paste.

```
python run_weekly.py
  1. extract.py        Procore -> output/<date>/csv/*.csv   (one CSV per data tab, exact column order)
  2. build_workbook.py CSVs -> output/Safety Health Report <date>.xlsx, recalculated and error-checked
  3. email             Scorecard as an HTML table + workbook attached (or saved to output/<date>/ when email is off)
```

## Setup on the always-on Windows PC

1. Install **Python 3.11+** from python.org (tick "Add python.exe to PATH"). Excel and Outlook desktop
   should be installed and signed in. LibreOffice is only needed if Excel isn't installed.
2. Copy this folder to the PC, e.g. `C:\HCS\hcs-safety-report`, and put `002 - Safety Health Report.xlsx` in `templates\`.
3. In PowerShell from that folder:
   ```
   powershell -ExecutionPolicy Bypass -File scheduling\setup_windows.ps1
   ```
4. Open `.env` and fill in the keys (below).
5. Test without sending: `.\.venv\Scripts\python.exe run_weekly.py --no-email`
   - The **first run takes about 8 hours.** Procore only returns Daily Log completion one date per call
     (about 7,600 dates across all projects), and this app is allowed about 1,000 calls an hour. The script
     pauses until each hourly limit resets. The results are cached in `data\daily_log_cache.json`, so
     weekly runs after that use about 700–900 calls and take about 10–20 minutes. **Copy `data\daily_log_cache.json`
     from the cloud test run to the PC to skip the long first run.**
   - Check `output\<date>\checks.txt` (should say `Status: OK`), the workbook, and `output\<date>\email.html`.
6. Turn on email (see below), then schedule it:
   ```
   powershell -ExecutionPolicy Bypass -File scheduling\install_task.ps1            # Monday 06:00
   powershell -ExecutionPolicy Bypass -File scheduling\install_task.ps1 -Day Friday -Time 05:30
   ```
   The PC's time zone should be Central so 06:00 means 6:00 AM Central. The task runs as the signed-in
   user (needed for Outlook), so lock the PC rather than signing out. It wakes the PC, and runs late
   if the PC was off at 6:00.

## `.env` keys (never commit this file)

| Key | What |
|---|---|
| `PROCORE_CLIENT_ID` | Client ID of the HCS read-only Procore app (DMSA) |
| `PROCORE_CLIENT_SECRET` | Its client secret |
| `PROCORE_COMPANY_ID` | `9593` (Hillwood Construction Services, L.P.) |
| `PROCORE_ENV` | `production` (or `sandbox` for testing) |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Only if `email.method: smtp` |
| `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET` | Only if `email.method: graph` |

The Procore app needs **Admin on Incidents, Forms and Observations**, otherwise private records are
hidden from it. It only ever sends GET requests. The one POST is the OAuth token request.

## Everyday changes (all in `config.yaml`)

**Change the distribution list:** edit `email.to` / `email.cc`, e.g.
```yaml
email:
  enabled: true
  method: outlook
  to: ["safety-team@hillwood.com", "someone@hillwood.com"]
```
Start with just yourself, then add people.

**Set the flag threshold:** `report.score_threshold: 0.70` flags every project whose Overall Score is
below 70% at the top of the email. `null` turns flagging off.

**Add a project:** add a row to Table1 in the template (`templates\002 - Safety Health Report.xlsx`,
"Safety Health Report" tab) with its Procore project number in **Project #**, plus Region, Status,
Mobilization Date and Substantial Completion as you do today. That's all. The next run picks it up.
The project must be one the Procore app can see (active projects), and its number must be a real
number, not "TBD". To exclude a project without deleting its row, add its number to `skip_projects`.

**Update manual columns** (Team Size, Status, dates, UTV dates, 3rd Party Reports, etc.): edit them in
the template as usual. The script never writes to them. Each week's output is a fresh copy of the template.

**Region names:** `region_map` maps Procore regions ("HCS CALIFORNIA") to report regions ("West").
The extract log lists any project where Procore and Table1 disagree.

## What's where

| Path | |
|---|---|
| `run_weekly.py` | The scheduled command |
| `extract.py` | Stage 2: Procore → CSV. `--only 401814` for one project |
| `validate.py` | Stage 3: compares an extract with the manual export in the template → `output/<date>/validation_report.md` |
| `build_workbook.py` | Stage 4: writes and recalculates the workbook, then checks it → `output/<date>/checks.txt` |
| `apply_fixes.py`, `compare_scores.py` | Stage 5: proposed formula fixes on a **copy** of the template, and their score impact (not used unless you adopt them) |
| `docs/field-map.md` | Every workbook column → Procore field |
| `docs/stage5-proposals.md` | Workbook problems found and proposed fixes |
| `logs/` | One log per run, plus `counts_<date>.csv` (records per project and tool) |
| `output/` | Weekly workbooks, CSVs, checks, email previews |
| `data/daily_log_cache.json` | Daily Log completion cache. Safe to delete (the next run rebuilds it, slowly) |

## How the workbook is written

- Only the six "- Procore Data" tabs are rewritten. The tab names, table names, headers and column
  order are unchanged, and project numbers stay as **text** like today. The file is rewritten at the XML
  level, so images, comments, data validation and the Scorecard's dynamic arrays are kept exactly.
- The workbook drops from about 12 MB to about 0.5 MB.
- **Table6 (Safety Survey) and Table18 (Observations) still run to row 1,048,576.** Table1's COUNTIFS
  pair them with `'Daily Log - Procore Data'!C:C`, and COUNTIFS needs equal-sized ranges. Shrinking
  them would make those formulas return `#VALUE!`. The Stage 5 fix removes this; then set
  `workbook.shrink_all_tables: true`. The size saving already comes from not storing empty rows.
- **Recalculation:** on Windows the script uses Excel itself (recalculate and save). Without Excel it
  uses LibreOffice on a verification copy with numeric project numbers, because LibreOffice, unlike
  Excel, won't match text "401814" against the number 401814. The values are stored in the workbook,
  and Excel recalculates again whenever the file is opened.
- **Projects the app can't see** (currently 405010, which is inactive in Procore) keep their existing
  rows from the template, so their scores don't drop to zero. This is noted in the email.
- Daily Log contains **completed days only** (like the manual export), because "Complete Total2" counts every row.

## Email options

| Method | Pros | Cons |
|---|---|---|
| `outlook` (default) | Nothing to set up; sends from your mailbox; appears in Sent Items | PC user must stay signed in with Outlook working |
| `graph` | Fully unattended; can send from a shared mailbox | Needs IT to create an Entra app with Mail.Send |
| `smtp` | Simple | SMTP AUTH is usually disabled in Microsoft 365 |

Set `email.enabled: false` to build everything without sending. The message is saved as
`output/<date>/email.eml` and `email.html`. If a run fails and email is enabled, a failure notice
goes to the same list.

## Troubleshooting

- `checks.txt` says ERRORS: it lists each new error cell. `#REF!` cells on the Scorecard already exist in
  the template and are listed as pre-existing (see Stage 5).
- "not visible to the Procore app": give the app access to that project in Procore (Company Admin →
  App Management), or add it to `skip_projects`.
- Runs are slow or show "Rate limited": that's normal on the first run. The app gets about 1,000
  Procore calls an hour, and the script waits for the limit to reset. If a weekly run starts hitting it,
  lower `daily_log.refresh_days` in config.yaml.

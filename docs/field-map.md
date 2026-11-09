# Field map: workbook columns → Procore API

Stage 1 discovery, run 2026-11-09 against **401814 ACN4 - Celestica TI** (Procore project id `3433495`),
company **Hillwood Construction Services, L.P.** (`9593`), production. All calls were GET except the OAuth token request.
Raw responses are in `samples/` (gitignored; they contain names and incident details).

**Update 2026-11-09 (after the app was given Admin on Incidents, Forms and Observations):** all six tabs now return data. Re-verified rows are marked ✅ below.

Legend: ✅ verified against the workbook's existing rows · ⚠️ mapping found but not yet verified · ❌ blocked / no API source

**Common to all tabs**
- `Project Number` ← `GET /rest/v1.0/projects?company_id=9593` → `project_number` (already a string, e.g. `"401814"`, written as text) ✅
- `Project Name` ← same → `name` ✅
- **Dates**: the API returns UTC timestamps (`2026-04-16T13:49:03Z`). Converting to `America/Chicago` (the project's `tz_name`) and keeping only the date matches the workbook. Converting the UTC value directly would shift some dates by a day.

## 1. Daily Log - Procore Data (Table19)

Endpoint: `GET /rest/v1.0/projects/{id}/daily_log_headers?log_date=YYYY-MM-DD`. Only one date per call. Date-range params return 404.

| Column | Source | |
|---|---|---|
| Project Number / Project Name | project | ✅ |
| Date | `log_date` | ✅ |
| Completed? | `completed` → `Yes` / `No` | ✅ |

Notes:
- The header endpoint returns a record for every date, including weekends (e.g. 2026-04-04, `completed: false`). Every one of the 43 workbook rows for 401814 is `Yes`, and the first is 3/31, the first completed date. So the current export appears to **list completed days only**. I'll confirm this in Stage 3.
- Cost: one call per project per day. A full rebuild of about 30 projects × 1 year is roughly 11k calls, which is about 3 hours at Procore's ~3,600 requests/hour limit. **Plan:** cache completed dates locally and fetch only the last ~14 days each week, so a weekly run makes ~420 calls.
- `GET /projects/{id}/daily_logs?filters[start_date]&filters[end_date]` works, but it returns the log *contents* (weather, manpower, etc.), not completion status.

## 2. Safety Survey - Procore Data (Table6)

Endpoint: `GET /rest/v1.0/projects/{id}/checklist/lists`, filtered to `list_template_name == "Site Safety Inspection"`. **The item counts are already on the list record, so the per-item endpoint isn't needed.**
For 401814, inspections #1–9 match the workbook on every column. The API has 24, because the workbook export stops in mid-May.

| Column | Source | |
|---|---|---|
| Project Number / Project Name | project | ✅ |
| Inspection Template Name | `list_template_name` | ✅ |
| Inspection # | `number` (as text) | ✅ |
| Assignee(s) | `inspectors[].name`, joined with `, ` | ⚠️ matches on 401814, but it's always the same person as Closed By there. Check on other projects in Stage 3 |
| No Response | `item_count − inspected_item_count` | ✅ (0 on all 9) |
| Due Date | `due_at` → Central date | ✅ |
| Status | `status` (`Closed`, …) | ✅ |
| Date Closed | `closed_at` → Central date | ✅ |
| Closed By | `closed_by.name` | ✅ |
| Project Region | project → `project_region.name` (e.g. `HCS TEXAS`) | ✅ |
| # Of Observations | `observations_count` | ✅ |
| At Risk Items | `deficient_item_count` | ✅ (9/9) |

## 3. Observations - Procore Data (Table18)

Endpoint: `GET /rest/v1.0/observations/items?project_id={id}` (query-based, not path-based).

| Column | Source | |
|---|---|---|
| Project Number / Project Name | project | ✅ |
| # | `number` | ✅ |
| Category | `type.category` (`Safety`, `Quality`, `Environmental`, `Work to Complete`, `Commissioning`) | ✅ (#6 is `Commissioning` in the workbook and `Quality` in Procore today, so it was recategorized after the export) |
| Status | `status`: `closed`→`Closed`, `initiated`→`Initiated`, `ready_for_review`→`Ready for Review` | ✅ (#3 and #5 were Initiated at export and are closed now) |
| Date Created | `created_at` → Central date | ✅ |
| Column3 | company custom field `custom_field_87826.value.label` (e.g. "Fall Protection", "Housekeeping"). Blank on non-safety types | ✅ (6/6) |
| Column2 | blank | — |
| Column1 | formula kept: `=IF([@Status]="Closed","Closed","Open")` | — |

~~Visibility problem~~ fixed: 111 observations visible on 401814, numbered from #1.

## 4. UTV - Procore Data (Table3)

Endpoint: same as #2, filtered to `list_template_name == "UTV Checklist"`. The 3 workbook rows for 401814 match. The API has 6 (3 are newer than the export).

| Column | Source | |
|---|---|---|
| Inspection Template Name | `list_template_name` | ✅ |
| Project Number / Project Name | project | ✅ |
| Status | `status` | ✅ |
| Date Created | `created_at` → Central date | ✅ |
| Date Closed | `closed_at` → Central date | ✅ |
| Created By | `created_by.name` | ✅ |
| Closed By | `closed_by.name` | ✅ |

## 5. Incident Forms - Procore Data (Table4)

Endpoint: `GET /rest/v1.0/projects/{id}/forms`, filtered to `form_template_name == "Incident Report"`.

| Column | Source | |
|---|---|---|
| Template Name | `form_template_name` | ✅ |
| Project Number / Project Name | project | ✅ |
| Date | `created_at` → Central date | ✅ |
| Title | `name` | ✅ |
| Description | `description` | ✅ |

- **The Forms API returns form records, not their contents.** List and detail (`/forms/{id}`) return the same fields: name, description, template, created_at, created_by, and a fillable PDF/attachment. The answers typed into the form aren't exposed as data. The workbook only uses this tab for a count by project (column B), so that's fine for scoring.
- ~~Zero Incident Report forms visible~~ fixed: 404032 shows 8, and the 6 in the workbook match on date, title and description (2 are newer).

## 6. Incidents Tab - Procore Data (Table5)

Endpoint: `GET /rest/v1.0/projects/{id}/incidents`.

| Column | Source | |
|---|---|---|
| # | `number` | ✅ |
| Status | `status`, title-cased | ✅ (#3 was Open at export, closed now) |
| Incident Date | `event_date` → Central date | ✅ |
| Title | `title` | ✅ |
| Recordable | `recordable` (true/false) → `Yes` / `No` | ✅ |
| Description | `description` is **HTML**; strip the tags and convert `&nbsp;` to plain text | ✅ |

~~Returned 0 incidents~~ fixed: 401814 shows 13, and the 3 in the workbook match. Configuration endpoint now returns 200.

## Blockers to fix in Procore: RESOLVED 2026-11-09

The app's service account can't see private and restricted records in three tools. The API is still read-only. The service account just needs a higher permission level on these tools:

| Tool | Symptom | Likely fix (Company Admin → App Management / the DMSA's permission template) |
|---|---|---|
| Incidents | 0 records, 403 on configuration | **Admin** on Incidents (private incidents are visible only to Admin) |
| Forms | Incident Report forms invisible | **Admin** on Forms, or make the Incident Report template non-private |
| Observations | gaps in numbering, #1–6 missing on 401814 | **Admin** on Observations (Standard/Read Only users can't see private observations, or ones not assigned to them) |

The app only sends GET requests, so Admin on these tools still can't change anything through this script. If your policy allows it, set it in the permission template the DMSA uses and apply it to all projects.

## Other findings

- **405010** is in Table1 but isn't visible to the app (not in the 70 projects returned). It may be inactive, or not added to the app.
- **Lone Oak 85 Bldg 2** exists in Procore as **405019**. That may be one of the two "TBD" rows.
- The Procore docs site (developers.procore.com) is blocked from this cloud session, so these mappings come from live responses, not the docs.
- No signed URLs (`thumbnail_url`, attachments) are stored or used.

# Stage 3: API extract vs the manual export

Run 2026-11-10 against all 31 Table1 projects the app can see. The full per-project tables and every
individual difference are in `output/2026-11-09/validation_report.md`, made by `python validate.py --date 2026-11-09`.

Each data tab in the template was exported on a different day (Daily Log to 5/23, Observations to 5/26,
UTV to 5/27, Incidents to 5/21, Incident Forms to 5/07, Safety Survey to about 5/27). Anything dated after
that is expected to be new. That covers almost all the rows the API has and the export doesn't:
1,766 daily logs, 230 surveys, 1,467 observations, 533 UTV, 28 forms and 46 incidents.

## Two bugs found and fixed during validation

| Problem | Effect before fix | Fix |
|---|---|---|
| Inspection # used Procore's internal `number`. The export (and the Procore screen) shows `identifier`. They differ wherever an inspection was ever deleted | 168 surveys paired with the wrong row (dates 5–10 days off) | Use `identifier` |
| Dates were converted to Central Time for every project. Procore shows them in the **project's** time zone (15 Eastern, 5 Pacific projects) | Due/closed dates 1 day early on NE/SE projects | Use each project's `tz_name` |

Also, the "Ready for Review" status is spelled "Ready For Review" to match the export.

## Every remaining difference, explained

| Tab | Count | What it is | Explanation |
|---|---|---|---|
| Daily Log | 51 days in Procore, not in the export | Days completed **after** the export | Sampled 5: e.g. 401811 3/12 completed 9/21/2026, 404034 4/24 completed 9/10/2026, 401806 5/15 completed 6/29. Late completions count once they're done, which is correct |
| Daily Log | 8 days in the export, not pulled | Days before the project's Mobilization Date | The script starts at the Mobilization Date. Table1 only counts days from mobilization on, so **no score effect** |
| Safety Survey | 6 changed | Surveys open at export, closed since (401799 #16–18, 401808 #31, 401818 #1, 404030 #27) | Status / Date Closed / Closed By / No Response updated in Procore |
| Safety Survey | 1 date changed | 401808 #30 closed 5/22 → 6/29 | Reopened and closed again |
| Safety Survey | 1 No Response 115 → 1 | 401807 #3 | Filled in after the export |
| Safety Survey | 1 in export only | 401808 #19 | Deleted in Procore |
| Safety Survey | 6 in Procore only | 401810 #14, 401814 #10 (due 5/28), 405017 #5, #20, #21, 405018 #1 | Created after the export. Some have no due date yet |
| Observations | 40 status changes | 30 Initiated → Closed, 9 Ready For Review → Closed | Closed since the export |
| Observations | 7 category / 11 type changes | Mostly 404030: Environmental → Safety with a hazard type added; 401814 #6 Commissioning → Quality | Recategorized in Procore after the export |
| Observations | 1 in export only | 401797 #20 | Deleted in Procore |
| UTV | 3 changed | 401807 4/25 and 5/20, 401810 5/27 | Closed since the export |
| UTV | 5 in export only | 401810, created 5/22–5/26 | No longer in Procore (deleted). 401810 has a new closed inspection on 5/27 |
| UTV | 1 in Procore only | 401815 5/27 | Created on the export day, after the export |
| Incidents | 5 status changes | 401806 #1, 401810 #1, 401814 #3, 404030 #3, 562097 #4 | Open → Closed since the export |
| Incident Forms | 0 | — | All 17 forms in the export match on date, title and description |

No differences come from the mapping itself: every field of every paired record matches unless it changed in Procore.

## Not compared

- **405010**: the app can't see it (inactive in Procore). Its existing rows are carried forward.
- **Lone Oak / Westport 16**: "TBD" numbers (Procore has 405019 / 401820).
- The export also holds rows for 22 projects that aren't in Table1. The formulas never read them, and the script doesn't write them.

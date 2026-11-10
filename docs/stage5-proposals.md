# Stage 5: workbook fixes (proposed, not applied)

The template has **not** been changed. `apply_fixes.py` writes a separate copy,
`templates/002 - Safety Health Report (fixed).xlsx`, so you can review the fixes in Excel. The weekly run keeps
using the original until you change `template:` in `config.yaml`.

| # | Problem | Proposal | Changes scores? | How |
|---|---|---|---|---|
| 1 | Scorecard detail columns point at the wrong projects | Look up by position in Table1 | Only the Scorecard tab (it currently shows wrong numbers) | `apply_fixes.py` (default) |
| 2 | Mixed-size COUNTIFS ranges force two tables to 1,048,576 rows, and the end-date test reads unrelated Daily Log rows | Use each table's own columns | Yes, slightly (see impact below) | `apply_fixes.py` (default) |
| 3 | "Open" surveys are always 0, so the Score2 "minus % open" penalty never applies | Count open surveys by Due Date | Yes, lowers projects with open surveys | `apply_fixes.py --only scorecard countifs open-penalty` |
| 4 | 401812 appears twice | Delete the "Gateway 70 & 71" row | Removes a TBD row | Manual (Excel) |
| 5 | Lone Oak / Westport 16 have "TBD" numbers | 405019 / 401820 | They get pulled once Active | Manual (Excel) |
| 6 | 3rd Party Reports row dated 1936 | 3/20/1936 → 3/20/2026 | No (dates aren't used in scoring) | Manual (Excel) |

---

## 1. Scorecard rows point at the wrong Table1 rows

Scorecard columns A–D are one dynamic array (`=Table1[Project #]`, etc.) that lists Table1 in order
on rows 5–37. Columns E–Q are plain references to fixed `'Safety Health Report'` rows that were never
updated when Table1 rows were inserted or deleted:

- **12 rows show `#REF!`** (rows 5–8, 18, 19, 25, 28, 32, 39, 43, 44) because the rows they pointed to were deleted.
- **The other 24 rows in the project list (rows 9–37) show another project's numbers. None are aligned.** Example: Scorecard row 9 is labelled
  401805 (Westport 15) but its numbers come from Table1 row 20 (401797 Project Aero). The offset changes
  down the sheet.
- Rows 38, 40, 41, 42 and 45 have numbers but no project label (the project list ends at row 37).

A lookup by project number (XLOOKUP/INDEX-MATCH, as the brief suggested) would still be wrong for 401812,
which is in Table1 twice. Both rows would show the first one's numbers. Since columns A–D already list
Table1 in order, the robust fix is to take the **same position** from Table1:

```
E5  =INDEX(Table1[Complete Total2],ROW()-ROW($A$4))     (Daily Reports: complete)
G5  =INDEX(Table1[Week Days],ROW()-ROW($A$4))           (Daily Reports: of)
H5  =INDEX(Table1[Total3 Closed],ROW()-ROW($A$4))       (Surveys)
J5  =INDEX(Table1[Weeks],ROW()-ROW($A$4))
K5  =INDEX(Table1[Total2],ROW()-ROW($A$4))              (Observations)
M5  =INDEX(Table1[Team Size],…)*INDEX(Table1[Weeks],…)
N5  =IF(INDEX(Table1[Total Closed],…)="N/A",0,INDEX(Table1[Total Closed],…))      (UTV)
P5  =IF(INDEX(Table1[Weekdays Onsite],…)="N/A",0,INDEX(Table1[Weekdays Onsite],…))
Q5  =INDEX(Table1[Reports Started],ROW()-ROW($A$4))     (Incidents)
```
These are filled down rows 5–37, and rows 38–45 are cleared. Adding or removing Table1 rows can no longer break it.
If Table1 grows past 33 projects, fill the formulas down further. The spilled A–D columns grow by themselves.

The weekly **email doesn't depend on this fix**: it's built from Table1's values directly.

## 2. COUNTIFS with mismatched ranges (Total3 Closed, Open, Total2, Open2)

Today, for example:
```
Total3 Closed = COUNTIFS('Safety Survey - Procore Data'!A:A, [@Project #],
                         Table6[[#All],[Date Closed]], ">="&[@Mobilization Date],
                         'Daily Log - Procore Data'!C:C, "<="&[@Substantial Completion])
```
- COUNTIFS needs every range to be the same size. Columns `A:A` and `C:C` are 1,048,576 rows, so
  **Table6 and Table18 have to extend to row 1,048,576.** That's why they do, and why the file was 12 MB.
  If they're shortened, all four columns become `#VALUE!`.
- The third pair tests the **Daily Log tab's date on the same row number**, not the survey's or
  observation's own date. So the "before Substantial Completion" filter is effectively random: a survey
  on row 300 is counted only if Daily Log row 300 happens to have a date before this project's
  Substantial Completion. Rows below the end of the Daily Log data are never counted.

Proposal: use only the table's own columns:
```
Total3 Closed = COUNTIFS(Table6[Project Number],[@Project #], Table6[Date Closed],">="&[@Mobilization Date], Table6[Date Closed],"<="&[@Substantial Completion])
Total2        = COUNTIFS(Table18[Project Number],[@Project #], Table18[Date Created],">="&[@Mobilization Date], Table18[Date Created],"<="&[@Substantial Completion])
Open2         = Total2 − (same COUNTIFS with Table18[Status],"Closed")
Open          = same as Total3 Closed with Table6[Status],"Open"   (behaviour unchanged, see #3)
```
After applying this, set `workbook.shrink_all_tables: true` in config.yaml so every table is sized to its data.

## 3. Open-survey penalty never applies (optional, changes scores)

Score2 = surveys closed per week **minus the share of surveys still open** (Explanation tab: "minus the
percent of open Site Safety Surveys"). But "Open" only counts surveys whose **Date Closed** is in the
window, and an open survey never has a Date Closed, so Open is always 0 and the penalty never applies.
Proposal: count open surveys by **Due Date** in the window:
```
Open = IF([@Total3 Closed]>0, COUNTIFS(Table6[Status],"Open", Table6[Project Number],[@Project #],
          Table6[Due Date],">="&[@Mobilization Date], Table6[Due Date],"<="&[@Substantial Completion]), "N/A")
```
This is a scoring-policy decision, so it's a separate opt-in (`--only scorecard countifs open-penalty`).

## 4–6. Data entry fixes (do these in Excel; they're in your manual columns)

- **401812 twice:** "Alliance Gateway 71" (row 31, Active, dated) and "Gateway 70 & 71" (row 35, no status or dates,
  shows TBD). Procore has 401811 Alliance Gateway 70 (already in Table1) and 401812 Alliance Gateway 71.
  **Delete the "Gateway 70 & 71" row.**
- **TBD project numbers:** Procore has **405019 Lone Oak 85 Bldg 2** and **401820 Westport 16 - Shell**.
  Put those in Project # (rows 51–52) so they're pulled once they're Active.
- **1936 date:** 3rd Party Reports row 2: 401799, **3/20/1936**, score 0.928. This is almost certainly 3/20/2026.
- **405010 Cecil Commerce Center Bldg. E** (Active Complete): inactive in Procore, so the app can't see it.
  The weekly run carries its existing rows forward. Either change its Status to "Complete" (it then shows N/A)
  or give the app access to inactive projects.
- **Region check:** confirm `HCS MIDSOUTH → EC` in `config.yaml` (the other regions map one-to-one).

## Score impact (measured 2026-11-10 with the full extract)

Full tables: `output/2026-11-09/score_comparison_countifs_scorecard.md` and `..._with_open_penalty.md`.

**Fixes 1 + 2 (recommended):** all 108 Scorecard error cells are gone, and the Scorecard shows the right project on every row.
Overall Score changes for 9 projects. Every change comes from the row-position bug in the COUNTIFS:

| Project | Overall today → fixed | Why |
|---|---|---|
| 405010 Cecil Commerce Center | 25.7% → 68.2% | Its 31 closed surveys and 83 observations are counted at all (today: 0, because the Daily Log rows at the same row numbers are dated after its 6/30/2025 completion) |
| 562097 SCC II - Infrastructure | 25.9% → 40.4% | 70 closed surveys counted instead of 17, and 158 observations instead of 86 |
| 401810 WP24 - Steel Dragon TI | 100% → 96.3% | 24 closed surveys in the window instead of 33 (9 were closed after Substantial Completion) |
| 401811 Alliance Gateway 70 | 59.9% → 46.0% | Records after its 9/11/2026 Substantial Completion are no longer counted |
| 401805 Westport 15 | 47.8% → 44.9% | Same: records after 8/7/2026 excluded |
| 401797, 401799, 401806 | −0.4 points each | One observation each after Substantial Completion |
| 404032 Kuser Rd | no change to the score | Observation count 122 → 120 (score was already capped at 100%) |

The current results depend on how rows happen to be sorted, which is also true of the manual export, so
**I recommend fix 2 as a bug fix, not a policy change.**

**Fix 3 (open-survey penalty, a policy decision):** three more projects drop slightly because they have an open survey:
401808 Medline 89.6% → 88.9%, 401815 Project 10x 66.6% → 63.6%, 401803 Embraer (N/A, not Active).

"""Stage 5 (opt-in): apply the proposed formula fixes to a COPY of the template.

Nothing here runs as part of run_weekly.py. The original template is never modified.

    python apply_fixes.py                       # writes templates/002 - Safety Health Report (fixed).xlsx
    python apply_fixes.py --only scorecard      # just one fix: scorecard | countifs | open-penalty
    python apply_fixes.py --compare             # also report how every project's scores change

To adopt the fixed copy: review it in Excel, then point `template:` in config.yaml at it
and set workbook.shrink_all_tables: true. See docs/stage5-proposals.md.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from common import ROOT, load_config  # noqa: E402
from workbook_writer import locate_parts  # noqa: E402

TR = "Table1[[#This Row],[{}]]"
PN, MOB, SC = TR.format("Project '#"), TR.format("Mobilization Date"), TR.format("Substantial Completion")

# --- Fix A: COUNTIFS ranges. Every range now comes from the same table, so the data tables can be
# sized to their real data, and the date window uses each record's own date (today the end-of-window
# test reads the Daily Log tab's dates by row position, which is unrelated data).
COUNTIFS_FIX = {
    "Total3 Closed": f'COUNTIFS(Table6[Project Number],{PN},Table6[Date Closed],">="&{MOB},Table6[Date Closed],"<="&{SC})',
    # Same result as today (counts closed-dated rows with Status "Open" = always 0) but with consistent ranges
    "Open": f'IF({TR.format("Total3 Closed")}>0,COUNTIFS(Table6[Status],"Open",Table6[Project Number],{PN},Table6[Date Closed],">="&{MOB},Table6[Date Closed],"<="&{SC}),"N/A")',
    "Total2": f'COUNTIFS(Table18[Project Number],{PN},Table18[Date Created],">="&{MOB},Table18[Date Created],"<="&{SC})',
    "Open2": f'IF({TR.format("Total2")}>0,({TR.format("Total2")})-(COUNTIFS(Table18[Project Number],{PN},Table18[Status],"Closed",Table18[Date Created],">="&{MOB},Table18[Date Created],"<="&{SC})),"N/A")',
}
# --- Fix B (changes scores): count open surveys by Due Date so the "minus % open" penalty in Score2 works
OPEN_PENALTY_FIX = {
    "Open": f'IF({TR.format("Total3 Closed")}>0,COUNTIFS(Table6[Status],"Open",Table6[Project Number],{PN},Table6[Due Date],">="&{MOB},Table6[Due Date],"<="&{SC}),"N/A")',
}
# --- Fix C: Scorecard detail columns follow the spilled project list (A5:A37 = Table1 in order)
SCORECARD_FIX = {
    "E": "INDEX(Table1[Complete Total2],ROW()-ROW($A$4))",
    "G": "INDEX(Table1[Week Days],ROW()-ROW($A$4))",
    "H": "INDEX(Table1[Total3 Closed],ROW()-ROW($A$4))",
    "J": "INDEX(Table1[Weeks],ROW()-ROW($A$4))",
    "K": "INDEX(Table1[Total2],ROW()-ROW($A$4))",
    "M": "INDEX(Table1[Team Size],ROW()-ROW($A$4))*INDEX(Table1[Weeks],ROW()-ROW($A$4))",
    "N": 'IF(INDEX(Table1[Total Closed],ROW()-ROW($A$4))="N/A",0,INDEX(Table1[Total Closed],ROW()-ROW($A$4)))',
    "P": 'IF(INDEX(Table1[Weekdays Onsite],ROW()-ROW($A$4))="N/A",0,INDEX(Table1[Weekdays Onsite],ROW()-ROW($A$4)))',
    "Q": "INDEX(Table1[Reports Started],ROW()-ROW($A$4))",
}


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def fix_table1(sheet_xml: str, table_xml: str, formulas: dict) -> tuple[str, str]:
    cols = re.findall(r'<tableColumn\b[^>]*\bname="([^"]+)"', table_xml)
    ref = re.search(r'<table\b[^>]*\bref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', table_xml)
    first_col, first_row, last_row = _col_index(ref.group(1)), int(ref.group(2)), int(ref.group(4))
    for name, formula in formulas.items():
        xml_name = escape(name)
        idx = cols.index(xml_name)
        f_xml = escape(formula)
        # calculated column definition
        pat = re.compile(r'(<tableColumn\b[^>]*\bname="%s"[^>]*>\s*<calculatedColumnFormula>).*?(</calculatedColumnFormula>)' % re.escape(xml_name), re.S)
        table_xml, n = pat.subn(lambda m: m.group(1) + f_xml + m.group(2), table_xml)
        # some columns (e.g. Total3 Closed) hold plain cell formulas with no calculated-column definition
        assert n == 1 or re.search(r'<tableColumn\b[^>]*\bname="%s"[^>]*/>' % re.escape(xml_name), table_xml), f"column {name} not found"
        # every cell in the column
        letter = _letters(first_col + idx)
        for r in range(first_row + 1, last_row + 1):
            cell = re.compile(r'<c r="%s%d"([^>/]*)>.*?</c>' % (letter, r), re.S)
            sheet_xml, n = cell.subn(lambda m: '<c r="%s%d"%s><f>%s</f></c>' % (letter, r, _strip_type(m.group(1)), f_xml), sheet_xml)
    return sheet_xml, table_xml


def _strip_type(attrs: str) -> str:
    return re.sub(r'\s+t="[^"]*"', "", attrs)


def _letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def fix_scorecard(sheet_xml: str, first=5, last=37, clear_to=45) -> str:
    def set_cell(xml, ref, formula):
        pat = re.compile(r'<c r="%s"([^>/]*)(?:/>|>.*?</c>)' % ref, re.S)
        def repl(m):
            attrs = re.sub(r'\s+t="[^"]*"|\s+cm="[^"]*"', "", m.group(1))
            return f'<c r="{ref}"{attrs}><f>{escape(formula)}</f></c>' if formula else f'<c r="{ref}"{attrs}/>'
        xml, n = pat.subn(repl, xml, count=1)
        return xml
    for r in range(first, clear_to + 1):
        for col, f in SCORECARD_FIX.items():
            sheet_xml = set_cell(sheet_xml, f"{col}{r}", f if r <= last else None)
        if r > last:  # rows below the project list held stray copies
            for col in "FILO":
                sheet_xml = set_cell(sheet_xml, f"{col}{r}", None)
    return sheet_xml


def apply(template: Path, out: Path, which: set[str]) -> Path:
    with zipfile.ZipFile(template) as zf:
        parts = locate_parts(zf)
        changed = {}
        shr_part, shr_tables = parts["Safety Health Report"]
        t1_part = shr_tables["Table1"]
        formulas = {}
        if "countifs" in which:
            formulas.update(COUNTIFS_FIX)
        if "open-penalty" in which:
            formulas.update(OPEN_PENALTY_FIX)
        if formulas:
            s, t = fix_table1(zf.read(shr_part).decode("utf-8"), zf.read(t1_part).decode("utf-8"), formulas)
            changed[shr_part], changed[t1_part] = s.encode("utf-8"), t.encode("utf-8")
        if "scorecard" in which:
            sc_part = parts["Scorecard"][0]
            changed[sc_part] = fix_scorecard(zf.read(sc_part).decode("utf-8")).encode("utf-8")
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        if 'fullCalcOnLoad="1"' not in wb_xml:
            changed["xl/workbook.xml"] = re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', wb_xml, count=1).encode("utf-8")
        changed["xl/_rels/workbook.xml.rels"] = re.sub(r'<Relationship\b[^>]*Target="calcChain.xml"[^>]*/>', "", zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")).encode("utf-8")
        changed["[Content_Types].xml"] = re.sub(r'<Override\b[^>]*PartName="/xl/calcChain.xml"[^>]*/>', "", zf.read("[Content_Types].xml").decode("utf-8")).encode("utf-8")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
            for item in zf.infolist():
                if item.filename == "xl/calcChain.xml":
                    continue
                o.writestr(item, changed.get(item.filename, zf.read(item.filename)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=["scorecard", "countifs", "open-penalty"])
    ap.add_argument("--out")
    ap.add_argument("--compare", action="store_true", help="recalculate original vs fixed with the latest extract and list score changes")
    ap.add_argument("--date", help="extract date to compare with (default: latest in output/)")
    args = ap.parse_args(argv)
    cfg = load_config()
    template = ROOT / cfg["template"]
    which = set(args.only or ["scorecard", "countifs"])  # open-penalty changes scores: opt in explicitly
    out = Path(args.out) if args.out else template.with_name(template.stem + " (fixed).xlsx")
    apply(template, out, which)
    print(f"Wrote {out} with fixes: {', '.join(sorted(which))}")
    if args.compare:
        from compare_scores import compare
        compare(template, out, cfg, args.date)


if __name__ == "__main__":
    main()

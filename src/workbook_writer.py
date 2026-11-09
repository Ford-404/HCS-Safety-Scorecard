"""Rewrite the six Procore data tables inside a copy of the template, at the XML level.

Only these parts change:
  - the <sheetData> and <dimension> of the six data sheets
  - the ref / autoFilter ref of their six tables
  - calcChain.xml is dropped and fullCalcOnLoad is set, so Excel recalculates on open
Everything else (formulas, Table1, Scorecard, images, comments, data validation, dynamic-array
metadata, styles) is copied byte-for-byte. openpyxl is deliberately not used for writing because
it drops parts of this workbook (images, dynamic-array metadata).
"""
from __future__ import annotations

import datetime as dt
import logging
import posixpath
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from tabs import TABS

log = logging.getLogger(__name__)
EXCEL_EPOCH = dt.date(1899, 12, 30)
MAX_ROW = 1048576
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _rels(zf: zipfile.ZipFile, part: str) -> dict:
    base, name = posixpath.split(part)
    rel_path = posixpath.join(base, "_rels", name + ".rels")
    out = {}
    if rel_path in zf.namelist():
        xml = zf.read(rel_path).decode("utf-8")
        for m in re.finditer(r"<Relationship\b[^>]*>", xml):
            tag = m.group(0)
            rid = re.search(r'\bId="([^"]+)"', tag).group(1)
            tgt = re.search(r'\bTarget="([^"]+)"', tag).group(1)
            out[rid] = posixpath.normpath(posixpath.join(base, tgt)) if not tgt.startswith("/") else tgt.lstrip("/")
    return out


def locate_parts(zf: zipfile.ZipFile) -> dict:
    """sheet name -> (sheet xml part, {table name: table xml part})"""
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    wb_rels = _rels(zf, "xl/workbook.xml")
    out = {}
    for m in re.finditer(r'<sheet\b[^>]*\bname="([^"]+)"[^>]*\br:id="([^"]+)"', wb):
        name = m.group(1).replace("&amp;", "&")
        part = wb_rels[m.group(2)]
        tables = {}
        for tgt in _rels(zf, part).values():
            if "/tables/" in tgt:
                tx = zf.read(tgt).decode("utf-8")
                tables[re.search(r'<table\b[^>]*\bname="([^"]+)"', tx).group(1)] = tgt
        out[name] = (part, tables)
    return out


def _row2_styles(sheet_xml: str) -> dict:
    m = re.search(r'<row r="2"[^>]*>(.*?)</row>', sheet_xml, re.S)
    styles = {}
    if m:
        for c in re.finditer(r'<c r="([A-Z]+)2"([^>]*?)(/?)>', m.group(1)):
            s = re.search(r'\bs="(\d+)"', c.group(2))
            if s:
                styles[c.group(1)] = s.group(1)
    return styles


def _cell(ref: str, value, style: str | None, formula: str | None = None) -> str:
    s = f' s="{style}"' if style else ""
    if formula is not None:
        v = "" if value is None else f"<v>{escape(str(value))}</v>"
        return f'<c r="{ref}"{s} t="str"><f>{escape(formula)}</f>{v}</c>'
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return f'<c r="{ref}"{s}><v>{(value - EXCEL_EPOCH).days}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    text = escape(_ILLEGAL.sub("", str(value)))[:32767]
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def build_sheet(sheet_xml: str, columns: list[str], rows: list[dict], formulas: dict,
                numeric_project_number: bool) -> tuple[str, int]:
    """Return (new sheet xml, last data row)."""
    head = re.search(r"<sheetData\s*/>|<sheetData>", sheet_xml)
    end = sheet_xml.find("</sheetData>")
    header_row = re.search(r'<row r="1"[^>]*>.*?</row>', sheet_xml, re.S).group(0)
    styles = _row2_styles(sheet_xml)
    parts = ["<sheetData>", header_row]
    letters = [col_letter(i) for i in range(len(columns))]
    for n, row in enumerate(rows, start=2):
        cells = []
        for col, L in zip(columns, letters):
            v = row.get(col)
            if col == "Project Number" and numeric_project_number and v not in (None, ""):
                v = int(v)
            f = formulas.get(col)
            if f is not None:
                v = "Closed" if row.get("Status") == "Closed" else "Open"
            cells.append(_cell(f"{L}{n}", v, styles.get(L), f))
        parts.append(f'<row r="{n}">' + "".join(cells) + "</row>")
    parts.append("</sheetData>")
    last = max(1, len(rows) + 1)
    tail = sheet_xml[end + len("</sheetData>"):] if end >= 0 else sheet_xml[head.end():]
    new = sheet_xml[:head.start()] + "".join(parts) + tail
    new = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:{letters[-1]}{last}"/>', new, count=1)
    return new, last


def set_table_ref(table_xml: str, ncols: int, last_row: int) -> str:
    ref = f"A1:{col_letter(ncols - 1)}{last_row}"
    table_xml = re.sub(r'(<table\b[^>]*\bref=")[^"]+(")', rf"\g<1>{ref}\2", table_xml, count=1)
    table_xml = re.sub(r'(<autoFilter\b[^>]*\bref=")[^"]+(")', rf"\g<1>{ref}\2", table_xml, count=1)
    return table_xml


def write_workbook(template: Path, out_path: Path, data: dict, *, shrink_all: bool = False,
                   numeric_project_number: bool = False, cached_values: dict | None = None) -> dict:
    """Write `data` ({tab key: [row dicts]}) into a copy of `template`. Returns {tab: table ref}."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    replaced, refs = {}, {}
    with zipfile.ZipFile(template) as zf:
        parts = locate_parts(zf)
        for key, spec in TABS.items():
            sheet_part, tables = parts[spec["sheet"]]
            table_part = tables[spec["table"]]
            sheet_xml = zf.read(sheet_part).decode("utf-8")
            rows = data.get(key, [])
            new_sheet, last = build_sheet(sheet_xml, spec["columns"], rows, spec.get("formulas", {}), numeric_project_number)
            # A table needs at least one data row
            table_last = last if last > 1 else 2
            if not shrink_all and spec["table"] in ("Table6", "Table18"):
                table_last = MAX_ROW  # see config.yaml: COUNTIFS pairs these with full-column ranges
            replaced[sheet_part] = new_sheet.encode("utf-8")
            replaced[table_part] = set_table_ref(zf.read(table_part).decode("utf-8"), len(spec["columns"]), table_last).encode("utf-8")
            refs[spec["table"]] = f"A1:{col_letter(len(spec['columns']) - 1)}{table_last}"
            log.info("%s: %s rows, %s ref %s", spec["sheet"], len(rows), spec["table"], refs[spec["table"]])

        if cached_values:
            for sheet_name, values in cached_values.items():
                part = parts[sheet_name][0]
                xml = (replaced.get(part) or zf.read(part)).decode("utf-8")
                replaced[part] = patch_cached_values(xml, values).encode("utf-8")

        # calcChain lists formula cells; drop it so Excel rebuilds it, and force a full recalc on open
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        if 'fullCalcOnLoad="1"' not in wb_xml:
            wb_xml = re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', wb_xml, count=1)
        replaced["xl/workbook.xml"] = wb_xml.encode("utf-8")
        rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        replaced["xl/_rels/workbook.xml.rels"] = re.sub(r'<Relationship\b[^>]*Target="calcChain.xml"[^>]*/>', "", rels).encode("utf-8")
        ct = zf.read("[Content_Types].xml").decode("utf-8")
        replaced["[Content_Types].xml"] = re.sub(r'<Override\b[^>]*PartName="/xl/calcChain.xml"[^>]*/>', "", ct).encode("utf-8")

        tmp = out_path.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for item in zf.infolist():
                if item.filename == "xl/calcChain.xml":
                    continue
                data_bytes = replaced.get(item.filename)
                out.writestr(item, data_bytes if data_bytes is not None else zf.read(item.filename))
        tmp.replace(out_path)
    return refs


def _serial(v):
    if isinstance(v, dt.datetime):
        d = v - dt.datetime(1899, 12, 30)
        return d.days + d.seconds / 86400
    if isinstance(v, dt.date):
        return (v - EXCEL_EPOCH).days
    if isinstance(v, dt.time):
        return (v.hour * 3600 + v.minute * 60 + v.second) / 86400
    return v


def patch_cached_values(sheet_xml: str, values: dict) -> str:
    """Replace the cached <v> of formula cells with recalculated values ({"E20": value})."""
    def repl(m):
        ref, attrs, body = m.group(1), m.group(2), m.group(3)
        if ref not in values or "<f" not in body:
            return m.group(0)
        v = values[ref]
        attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
        f = re.search(r"<f\b[^>]*/>|<f\b[^>]*>.*?</f>", body, re.S).group(0)
        if v is None:
            return f'<c r="{ref}"{attrs}>{f}</c>'
        if isinstance(v, bool):
            return f'<c r="{ref}"{attrs} t="b">{f}<v>{int(v)}</v></c>'
        if isinstance(v, str) and v.startswith("#"):
            return f'<c r="{ref}"{attrs} t="e">{f}<v>{escape(v)}</v></c>'
        v = _serial(v)
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"{attrs}>{f}<v>{v}</v></c>'
        return f'<c r="{ref}"{attrs} t="str">{f}<v>{escape(str(v))}</v></c>'
    return re.sub(r'<c r="([A-Z]+\d+)"([^>/]*)>(.*?)</c>', repl, sheet_xml, flags=re.S)


def read_template_rows(template: Path, key: str, project_numbers: set[str] | None) -> list[dict]:
    """Existing rows of one data tab for the given projects (used to carry forward projects the
    Procore app cannot see, so their scores do not drop to zero)."""
    import warnings
    import openpyxl
    warnings.filterwarnings("ignore", module="openpyxl")
    spec = TABS[key]
    wb = openpyxl.load_workbook(template, read_only=True)
    ws = wb[spec["sheet"]]
    pn_idx = spec["columns"].index("Project Number")
    out, blank = [], 0
    for r in ws.iter_rows(min_row=2, max_col=len(spec["columns"]), values_only=True):
        if all(v in (None, "") for k, v in enumerate(r) if spec["columns"][k] != "Column1"):
            blank += 1
            if blank > 200:
                break
            continue
        blank = 0
        if project_numbers is None or str(r[pn_idx]).strip() in project_numbers:
            row = dict(zip(spec["columns"], r))
            row["Project Number"] = str(row["Project Number"]).strip()
            for c in spec.get("date_columns", []):
                if isinstance(row.get(c), dt.datetime):
                    row[c] = row[c].date()
            out.append(row)
    wb.close()
    return out

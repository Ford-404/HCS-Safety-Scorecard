"""Shared helpers: config, logging, Table1 project list, date handling."""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import sys
import warnings
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def setup_logging(name: str) -> Path:
    (ROOT / "logs").mkdir(exist_ok=True)
    path = ROOT / "logs" / f"{name}_{dt.datetime.now():%Y-%m-%d_%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return path


def to_local_date(value, tz: str) -> dt.date | None:
    """Procore timestamp (UTC ISO) or plain date string -> local calendar date."""
    if not value:
        return None
    s = str(value)
    if "T" not in s:
        return dt.date.fromisoformat(s[:10])
    stamp = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return stamp.astimezone(ZoneInfo(tz)).date()


def html_to_text(value) -> str:
    """Incident descriptions come back as HTML; the workbook holds plain text."""
    if not value:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", str(value))
    s = re.sub(r"(?i)</(p|div|li|h\d)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def read_table1(template: Path) -> list[dict]:
    """Rows of Table1 ('Safety Health Report' tab): project number and the manual columns we need."""
    import openpyxl
    from openpyxl.utils import range_boundaries

    warnings.filterwarnings("ignore", module="openpyxl")
    wb = openpyxl.load_workbook(template, read_only=False, data_only=True)
    ws = wb["Safety Health Report"]
    ref = ws.tables["Table1"].ref
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    headers = [ws.cell(min_row, c).value for c in range(min_col, max_col + 1)]
    rows = []
    for r in range(min_row + 1, max_row + 1):
        vals = {h: ws.cell(r, c).value for h, c in zip(headers, range(min_col, max_col + 1))}
        vals["_row"] = r
        rows.append(vals)
    return rows


def project_number_of(row: dict) -> str | None:
    v = row.get("Project #")
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s if s.isdigit() else None

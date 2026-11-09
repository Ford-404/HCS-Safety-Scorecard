"""Recalculate a workbook so TODAY()-based formulas have current values.

- excel:       Excel desktop via COM (Windows only). Recalculates and saves in place; keeps every
               Excel feature. Preferred on the always-on PC.
- libreoffice: headless LibreOffice. Writes a recalculated *copy* used only for reading values
               (LibreOffice re-saving would drop Excel-only features, so its file is never shipped).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if os.path.exists(p):
            return p
    return None


def excel_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def recalc_excel(path: Path) -> Path:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(str(Path(path).resolve()), UpdateLinks=0)
        xl.CalculateFull()
        wb.Save()
        wb.Close(SaveChanges=False)
    finally:
        xl.Quit()
        pythoncom.CoUninitialize()
    return Path(path)


def recalc_libreoffice(path: Path, out_dir: Path) -> Path:
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) not found")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof:
        user = Path(prof) / "user"
        user.mkdir(parents=True)
        (user / "registrymodifications.xcu").write_text(_XCU, encoding="utf-8")
        src = out_dir / ("_lo_in_" + Path(path).name.replace(" ", "_"))
        shutil.copyfile(path, src)
        cmd = [soffice, f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--norestore",
               "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out_dir / "_lo_out"), str(src)]
        log.info("LibreOffice recalc: %s", Path(path).name)
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
        src.unlink(missing_ok=True)
        result = out_dir / "_lo_out" / src.name
        if not result.exists():
            raise RuntimeError("LibreOffice produced no output")
        final = out_dir / ("recalc_" + Path(path).name)
        shutil.move(result, final)
        shutil.rmtree(out_dir / "_lo_out", ignore_errors=True)
        return final


def recalc(path: Path, engine: str, scratch: Path) -> tuple[str, Path | None]:
    """Returns (engine used, path of a file whose cached values are current)."""
    if engine in ("auto", "excel") and excel_available():
        return "excel", recalc_excel(path)
    if engine == "excel":
        raise RuntimeError("Excel recalculation requested but Excel/pywin32 is not available")
    if engine in ("auto", "libreoffice"):
        return "libreoffice", recalc_libreoffice(path, scratch)
    return "none", None

"""Build the weekly email (Scorecard as an HTML table, workbook attached) and send it.

The table is built from Table1's recalculated values, so it is correct even while the Scorecard
tab's own formulas still point at the wrong rows (see docs/stage5-proposals.md).

Send methods (config.yaml -> email.method):
  outlook  Outlook desktop on this PC (pywin32). Simplest; the PC user must be signed in to Outlook.
  graph    Microsoft Graph sendMail with an Entra app (GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET in .env,
           tenant_id + from in config). Runs unattended; needs IT to grant Mail.Send.
  onedrive Saves the email into a work-OneDrive folder; a Power Automate flow sends it from your mailbox
           (works with the new Outlook; see docs/power-automate-flow.md).
  smtp     SMTP AUTH (SMTP_USERNAME / SMTP_PASSWORD in .env). Often disabled in Microsoft 365.
With email.enabled: false nothing is sent; the message is saved to output/<date>/email.html and .eml.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)

NA = ("N/A", "TBD", None, "")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct(v):
    n = _num(v)
    return f"{n:.0%}" if n is not None else html.escape(str(v if v not in (None, "") else "—"))


def _int(v):
    n = _num(v)
    return f"{n:,.0f}" if n is not None else html.escape(str(v if v not in (None, "") else "—"))


def table1_rows(values: dict) -> list[dict]:
    """Rebuild Table1 rows (header row 19) from {"A19": "Project #", "A20": 401797, ...}."""
    shr = values["Safety Health Report"]
    cols = {}
    for ref, v in shr.items():
        m = re.match(r"([A-Z]+)19$", ref)
        if m and v:
            cols[m.group(1)] = str(v)
    rows = []
    r = 20
    while f"A{r}" in shr or f"C{r}" in shr:
        rows.append({name: shr.get(f"{col}{r}") for col, name in cols.items()})
        r += 1
    return rows


def build_html(rows: list[dict], run_date: dt.date, threshold: float | None, notes: list[str]) -> str:
    def score(r):
        return _num(r.get("Overall Score"))

    flagged = [r for r in rows if threshold is not None and score(r) is not None and score(r) < threshold]
    flagged.sort(key=score)
    th = "padding:4px 8px;border:1px solid #c8c8c8;background:#1f3864;color:#fff;font-weight:600;text-align:left"
    td = "padding:4px 8px;border:1px solid #d9d9d9"

    def color(v):
        n = _num(v)
        if n is None:
            return "#f2f2f2"
        if threshold is not None and n < threshold:
            return "#f8cbad"
        return "#c6efce" if n >= 0.9 else ("#ffeb9c" if n >= 0.7 else "#f8cbad")

    def table(rs):
        head = ["Project #", "Region", "Project", "Status", "Overall", "Daily Reports", "Surveys", "Observations", "UTV", "Incidents (open)"]
        out = ['<table style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:12px">',
               "<tr>" + "".join(f'<th style="{th}">{h}</th>' for h in head) + "</tr>"]
        for r in rs:
            cells = [
                _int(r.get("Project #")) if _num(r.get("Project #")) is None else str(int(r["Project #"])),
                html.escape(str(r.get("Region") or "")), html.escape(str(r.get("Project Name") or "")),
                html.escape(str(r.get("Status3") or "")),
            ]
            score_cells = [
                (r.get("Overall Score"), _pct(r.get("Overall Score"))),
                (r.get("Score4"), f'{_pct(r.get("Score4"))} <span style="color:#666">({_int(r.get("Complete Total2"))} of {_int(r.get("Week Days"))})</span>'),
                (r.get("Score2"), f'{_pct(r.get("Score2"))} <span style="color:#666">({_int(r.get("Total3 Closed"))} of {_int(r.get("Weeks"))})</span>'),
                (r.get("Score3"), f'{_pct(r.get("Score3"))} <span style="color:#666">({_int(r.get("Total2"))})</span>'),
                (r.get("Score"), _pct(r.get("Score"))),
            ]
            row = "".join(f'<td style="{td}">{c}</td>' for c in cells)
            row += "".join(f'<td style="{td};background:{color(v)}">{t}</td>' for v, t in score_cells)
            row += f'<td style="{td}">{_int(r.get("Reports Started"))} ({_int(r.get("Reports Open"))})</td>'
            out.append(f"<tr>{row}</tr>")
        out.append("</table>")
        return "\n".join(out)

    scored = [r for r in rows if r.get("Project Name")]
    scored.sort(key=lambda r: (score(r) is None, -(score(r) or 0)))
    parts = [f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:13px">',
             f"<h2 style=\"margin:0 0 4px\">HCS Safety Health Report – {run_date:%B %d, %Y}</h2>",
             "<p style=\"margin:0 0 12px;color:#555\">Pulled from Procore automatically. Workbook attached.</p>"]
    if threshold is not None:
        if flagged:
            parts.append(f'<h3 style="color:#c00000;margin:12px 0 4px">⚠ {len(flagged)} project(s) below {threshold:.0%}</h3>')
            parts.append(table(flagged))
        else:
            parts.append(f'<p style="color:#2e7d32"><b>No active project is below {threshold:.0%}.</b></p>')
    parts.append('<h3 style="margin:16px 0 4px">All projects</h3>')
    parts.append(table(scored))
    parts.append('<p style="color:#666;font-size:11px;margin-top:8px">Score colors: green ≥ 90%, yellow 70–89%, red below 70%'
                 + (f" or below the {threshold:.0%} threshold" if threshold is not None else "")
                 + ". N/A = not Active; TBD = Mobilization/Substantial Completion dates missing.</p>")
    if notes:
        parts.append('<p style="color:#666;font-size:11px">Run notes:<br>' + "<br>".join(html.escape(n) for n in notes) + "</p>")
    parts.append("</div>")
    return "\n".join(parts)


def build_message(cfg: dict, subject: str, html_body: str, attachment: Path | None) -> EmailMessage:
    e = cfg["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = ", ".join(e.get("to") or [])
    if e.get("cc"):
        msg["Cc"] = ", ".join(e["cc"])
    if e.get("from"):
        msg["From"] = e["from"]
    msg.set_content("This report is best viewed as HTML. The workbook is attached.")
    msg.add_alternative(html_body, subtype="html")
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=attachment.name)
    return msg


def send(cfg: dict, subject: str, html_body: str, attachment: Path | None, save_dir: Path) -> str:
    e = cfg["email"]
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "email.html").write_text(html_body, encoding="utf-8")
    msg = build_message(cfg, subject, html_body, attachment)
    (save_dir / "email.eml").write_bytes(bytes(msg))
    if not e.get("enabled"):
        return f"email disabled in config: saved {save_dir / 'email.eml'}"
    if not e.get("to"):
        raise RuntimeError("email.enabled is true but email.to is empty")
    method = e.get("method", "outlook")
    if method == "outlook":
        import win32com.client
        ol = win32com.client.Dispatch("Outlook.Application")
        mail = ol.CreateItem(0)
        mail.To = "; ".join(e["to"])
        if e.get("cc"):
            mail.CC = "; ".join(e["cc"])
        mail.Subject = subject
        mail.HTMLBody = html_body
        if attachment:
            mail.Attachments.Add(str(attachment.resolve()))
        mail.Send()
    elif method == "smtp":
        s = e["smtp"]
        with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=60) as smtp:
            if s.get("starttls", True):
                smtp.starttls()
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    elif method == "graph":
        _send_graph(cfg, subject, html_body, attachment)
    elif method == "onedrive":
        return _send_onedrive(cfg, subject, html_body, attachment)
    else:
        raise ValueError(f"unknown email.method {method}")
    return f"sent via {method} to {', '.join(e['to'])}"


def onedrive_folder(cfg) -> Path:
    """<work OneDrive>/<email.onedrive.folder>. Windows sets OneDriveCommercial for the work OneDrive."""
    od = cfg["email"].get("onedrive") or {}
    root = od.get("root") or os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive")
    if not root:
        raise RuntimeError("Work OneDrive folder not found. Set email.onedrive.root in config.yaml "
                           "(e.g. C:\\Users\\you\\OneDrive - Company).")
    return Path(root) / od.get("folder", "HCS Safety Report")


def _send_onedrive(cfg, subject, html_body, attachment):
    """Hand the email to the Power Automate flow (docs/power-automate-flow.md).

    Writes the attachment to <folder>/Attachments, then a message file to <folder>/Outbox. The flow
    triggers on the new message file, waits for the attachment to sync, and sends the email.
    """
    import json
    import shutil

    e = cfg["email"]
    base = onedrive_folder(cfg)
    att_dir, outbox = base / "Attachments", base / "Outbox"
    att_dir.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")  # unique per message
    if attachment is None:  # e.g. a failure notice: the flow always attaches a file, so attach a short note
        att_name = f"run-notes ({stamp}).txt"
        (att_dir / att_name).write_text(html.unescape(re.sub(r"<[^>]+>", "", html_body)), encoding="utf-8")
    else:
        att_name = f"{attachment.stem} ({stamp}){attachment.suffix}"
        shutil.copyfile(attachment, att_dir / att_name)
    message = {"to": "; ".join(e["to"]), "cc": "; ".join(e.get("cc") or []), "subject": subject,
               "html": html_body, "attachment": att_name}
    tmp = outbox.parent / f".message {stamp}.tmp"  # write elsewhere, then move in, so the flow never sees half a file
    tmp.write_text(json.dumps(message), encoding="utf-8")
    final = outbox / f"message {stamp}.json"
    shutil.move(str(tmp), final)
    return f"handed to Power Automate via {final} (sends to {message['to']} once OneDrive syncs)"


def _send_graph(cfg, subject, html_body, attachment):
    import requests
    e = cfg["email"]
    tenant = e["graph"]["tenant_id"]
    tok = requests.post(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data={
        "client_id": os.environ["GRAPH_CLIENT_ID"], "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}, timeout=30)
    tok.raise_for_status()
    rcpt = lambda xs: [{"emailAddress": {"address": a}} for a in xs or []]
    message = {"subject": subject, "body": {"contentType": "HTML", "content": html_body},
               "toRecipients": rcpt(e["to"]), "ccRecipients": rcpt(e.get("cc"))}
    if attachment:
        message["attachments"] = [{"@odata.type": "#microsoft.graph.fileAttachment", "name": attachment.name,
                                   "contentBytes": base64.b64encode(attachment.read_bytes()).decode()}]
    r = requests.post(f"https://graph.microsoft.com/v1.0/users/{e['from']}/sendMail",
                      headers={"Authorization": f"Bearer {tok.json()['access_token']}"},
                      json={"message": message, "saveToSentItems": True}, timeout=60)
    r.raise_for_status()

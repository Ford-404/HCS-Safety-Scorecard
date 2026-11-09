"""Stage 1: save raw JSON samples for one project. Read-only (GET only)."""
import json, logging, sys
from pathlib import Path
from procore_client import ProcoreClient, ProcoreError

logging.basicConfig(level=logging.WARNING)
OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)
c = ProcoreClient(str(OUT.parent / ".env"))
P = int(sys.argv[1]) if len(sys.argv) > 1 else 3433495  # 401814 ACN4 - Celestica TI

def save(name, path, params=None, all_pages=False):
    try:
        data = c.get_all(path, params) if all_pages else c.get(path, params)
    except ProcoreError as e:
        data = {"_error": e.status, "_url": e.url, "_body": str(e)[:500]}
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, default=str))
    return data

save("projects_list", "/rest/v1.0/projects", {"company_id": c.company_id}, all_pages=True)
save("project_detail", f"/rest/v1.0/projects/{P}", {"company_id": c.company_id})
save("daily_logs_week", f"/rest/v1.0/projects/{P}/daily_logs", {"filters[start_date]": "2026-05-04", "filters[end_date]": "2026-05-08"})
save("daily_log_header_2026-05-05", f"/rest/v1.0/projects/{P}/daily_log_headers", {"log_date": "2026-05-05"})
save("checklist_list_templates", f"/rest/v1.0/projects/{P}/checklist/list_templates", all_pages=True)
lists = save("checklist_lists", f"/rest/v1.0/projects/{P}/checklist/lists", all_pages=True)
for tmpl in ("Site Safety Inspection", "UTV Checklist"):
    hit = next((l for l in lists if (l.get("list_template_name") or l.get("name") or "").startswith(tmpl)), None)
    if hit:
        slug = tmpl.split()[0].lower()
        save(f"checklist_list_detail_{slug}", f"/rest/v1.0/projects/{P}/checklist/lists/{hit['id']}")
        save(f"checklist_items_{slug}", f"/rest/v1.0/checklist/items", {"project_id": P, "list_id": hit["id"]}, all_pages=True)
save("observations_items", "/rest/v1.0/observations/items", {"project_id": P}, all_pages=True)
save("incidents", f"/rest/v1.0/projects/{P}/incidents", all_pages=True)
save("form_templates", f"/rest/v1.0/projects/{P}/form_templates", all_pages=True)
forms = save("forms", f"/rest/v1.0/projects/{P}/forms", all_pages=True)
if forms:
    save("form_detail", f"/rest/v1.0/projects/{P}/forms/{forms[0]['id']}")
print("saved:", sorted(p.name for p in OUT.glob("*.json")))

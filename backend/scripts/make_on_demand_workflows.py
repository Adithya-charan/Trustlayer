"""Builds the on-demand copies of the three approved n8n workflows from the originals in n8n/.

Each copy is identical to its original except the triggers: the Schedule and Manual-test nodes are replaced by ONE header-authenticated
Webhook trigger. The copies contain no schedule, so publishing one cannot start a schedule. The originals are never modified.
Run from the repo root:  backend/.venv/Scripts/python.exe -m backend.scripts.make_on_demand_workflows   (or from backend/: python -m scripts.make_on_demand_workflows)"""
import copy
import json
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.assistant.n8n import APPROVED, TRIGGER_HEADER  # noqa: E402

SRC = ROOT / "n8n"
OUT = SRC / "on-demand"
FILES = {"scheduled-scan": "scheduled-scan.workflow.json", "security-alerts": "security-alerts.workflow.json", "summary-report": "summary-report.workflow.json"}
CREDENTIAL = "TrustLayer Trigger Key"  # the n8n Header Auth credential: header name X-TrustLayer-Trigger-Key, value = N8N_TRIGGER_SECRET


def build(key: str) -> dict:
    wf = json.loads((SRC / FILES[key]).read_text(encoding="utf-8"))
    out = copy.deepcopy(wf)
    path = APPROVED[key][1]
    first = out["connections"]["Schedule"]  # what the schedule used to start
    out["nodes"] = [n for n in out["nodes"] if n["name"] not in ("Schedule", "Manual test")]
    for gone in ("Schedule", "Manual test"):
        out["connections"].pop(gone, None)
    trigger = {
        "parameters": {"httpMethod": "POST", "path": path, "authentication": "headerAuth", "responseMode": "onReceived", "options": {}},
        "name": "Trigger", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 380],
        "webhookId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"trustlayer/{path}")),
        "credentials": {"httpHeaderAuth": {"id": "", "name": CREDENTIAL}},
    }
    out["nodes"].insert(0, trigger)
    out["connections"] = {"Trigger": first, **out["connections"]}
    out["name"] = f"{wf['name']} (on demand)"
    out["active"] = False
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for key in FILES:
        target = OUT / FILES[key].replace(".workflow.json", ".on-demand.workflow.json")
        target.write_text(json.dumps(build(key), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
    print(f"Header Auth credential to create in n8n: name '{CREDENTIAL}', header '{TRIGGER_HEADER}'.")


if __name__ == "__main__":
    main()

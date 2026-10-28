"""Static checks on the exported n8n workflows (no n8n instance needed).
Runtime behaviour of the endpoints they call is covered in test_core.py."""
import json
import pathlib

import pytest

DIR = pathlib.Path(__file__).resolve().parents[2] / "n8n"
FILES = sorted(DIR.glob("*.workflow.json"))


def test_workflows_exist():
    assert {f.name.split(".")[0] for f in FILES} == {"scheduled-scan", "security-alerts", "summary-report"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_workflow_safety(path):
    text = path.read_text(encoding="utf-8")
    wf = json.loads(text)
    # no secrets or real keys in the export
    assert "dev-only" not in text and "n8n-secret" not in text and "npg_" not in text
    for n in wf["nodes"]:
        if n["type"] != "n8n-nodes-base.httpRequest":
            continue
        p = n["parameters"]
        assert p["authentication"] == "genericCredentialType" and p["genericAuthType"] == "httpHeaderAuth"
        assert "credentials" in n and n["credentials"]["httpHeaderAuth"]["name"]
        if n.get("retryOnFail"):  # bounded retries only
            assert n["maxTries"] <= 3 and n["waitBetweenTries"] >= 1000
            assert n["onError"] == "continueErrorOutput"  # failure routes to an explicit branch


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_failure_path_reported(path):
    wf = json.loads(path.read_text(encoding="utf-8"))
    conns = wf["connections"]
    guarded = [n["name"] for n in wf["nodes"] if n.get("retryOnFail") or n.get("onError") == "continueErrorOutput"]
    for name in guarded:
        outs = conns[name]["main"]
        assert len(outs) >= 2 and outs[1], f"{name} has no error branch"
        assert any(c["node"] == "Report failure" for c in outs[1]), f"{name} error branch must report the failure"
    names = {n["name"] for n in wf["nodes"]}
    assert {"Report failure", "Fail execution"} <= names
    # after reporting, the n8n execution itself must be marked failed (no green runs for failed work)
    assert [c["node"] for c in conns["Report failure"]["main"][0]] == ["Fail execution"]
    stop = next(n for n in wf["nodes"] if n["name"] == "Fail execution")
    assert stop["type"] == "n8n-nodes-base.stopAndError" and "{{" not in stop["parameters"]["errorMessage"]  # static message only


def test_response_validation_present():
    alerts = json.loads((DIR / "security-alerts.workflow.json").read_text(encoding="utf-8"))
    code = next(n for n in alerts["nodes"] if n["name"] == "Select alerts")["parameters"]["jsCode"]
    assert "throw new Error" in code and "Array.isArray(body)" in code
    summary = json.loads((DIR / "summary-report.workflow.json").read_text(encoding="utf-8"))
    code = next(n for n in summary["nodes"] if n["name"] == "Build report")["parameters"]["jsCode"]
    assert "throw new Error" in code and "window_hours" in code
    fetch = next(n for n in summary["nodes"] if n["name"] == "Fetch summary")
    # full-response mode yields exactly one item (even for an empty body) without alwaysOutputData, which would also fire on errors
    assert fetch["parameters"]["options"]["response"]["response"]["fullResponse"] is True and not fetch.get("alwaysOutputData")
    ev = next(n for n in alerts["nodes"] if n["name"] == "Fetch high-severity events")
    assert ev["parameters"]["options"]["response"]["response"]["fullResponse"] is True and not ev.get("alwaysOutputData")


def test_scan_workflow_is_idempotent():
    wf = json.loads((DIR / "scheduled-scan.workflow.json").read_text(encoding="utf-8"))
    start = next(n for n in wf["nodes"] if n["name"] == "Start scan")
    assert any(h["name"] == "Idempotency-Key" for h in start["parameters"]["headerParameters"]["parameters"])

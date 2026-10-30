"""Static checks on the generated on-demand n8n workflows (no n8n instance needed)."""
import json
import pathlib

import pytest

from app.assistant.n8n import APPROVED, TRIGGER_HEADER
from scripts.make_on_demand_workflows import FILES, OUT, SRC, build

KEYS = sorted(APPROVED)


def load(key):
    return json.loads((OUT / FILES[key].replace(".workflow.json", ".on-demand.workflow.json")).read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", KEYS)
def test_on_demand_copy_is_safe(key):
    wf = load(key)
    text = json.dumps(wf)
    types = [n["type"] for n in wf["nodes"]]
    assert "n8n-nodes-base.scheduleTrigger" not in types and "n8n-nodes-base.manualTrigger" not in types  # publishing cannot start a schedule
    hooks = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
    assert len(hooks) == 1
    p = hooks[0]["parameters"]
    assert p["path"] == APPROVED[key][1] and p["httpMethod"] == "POST"
    assert p["authentication"] == "headerAuth" and p["responseMode"] == "onReceived"  # authenticated; answers "started", not "succeeded"
    assert hooks[0]["credentials"]["httpHeaderAuth"]["name"] == "TrustLayer Trigger Key"
    assert wf["active"] is False and wf["name"].endswith("(on demand)")
    assert "dev-only" not in text and "n8n-secret" not in text and TRIGGER_HEADER not in text  # no secrets or header values baked in
    names = {n["name"] for n in wf["nodes"]}
    for src, targets in wf["connections"].items():
        assert src in names
        assert all(t["node"] in names for branch in targets["main"] for t in branch)  # no dangling connections
    assert wf["connections"]["Trigger"]["main"][0][0]["node"] == "Config"


@pytest.mark.parametrize("key", KEYS)
def test_copy_matches_original_except_triggers(key):
    original = json.loads((SRC / FILES[key]).read_text(encoding="utf-8"))
    wf = load(key)
    keep = lambda w: {n["name"]: n for n in w["nodes"] if n["name"] not in ("Schedule", "Manual test", "Trigger")}  # noqa: E731
    assert keep(wf) == keep(original)  # same logic, same node settings, same retries and error branches
    assert not (set(original["connections"]) - {"Schedule", "Manual test"}) ^ (set(wf["connections"]) - {"Trigger"})


@pytest.mark.parametrize("key", KEYS)
def test_generated_files_are_up_to_date(key):
    """If an original changes, regenerate (python -m scripts.make_on_demand_workflows); this fails until the copy is refreshed."""
    assert load(key) == build(key)


def test_originals_still_have_their_schedule_triggers():
    for key in KEYS:
        types = [n["type"] for n in json.loads((SRC / FILES[key]).read_text(encoding="utf-8"))["nodes"]]
        assert "n8n-nodes-base.scheduleTrigger" in types  # the originals are untouched and unpublished

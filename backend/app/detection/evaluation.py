"""Detection evaluation: rules-only vs ML-only vs hybrid on the synthetic labelled data in eval_data.py.

Run (from backend/, HF_HOME pointing at the model cache if you use a non-default one):
    .venv/Scripts/python.exe -m app.detection.evaluation --split both --tag baseline
Results are measured, never edited. Each run writes a NEW timestamped JSON under evaluation_results/ (old baselines are kept) and prints a diff against the
previous run. If the ML model is unavailable, ML-only and hybrid rows are reported as unavailable, not estimated.

Three evaluation units, never mixed into one score:
  entity  exact-span + category match on free text (also a looser "overlap" match, reported separately)
  value   which structured categories a single cell contains (set comparison)
  column  is the column sensitive (binary), from name heuristics + values
Scopes: `full` scores every gold category (a config that cannot detect a category takes false negatives);
        `in_scope` scores only the categories the config is designed for, so coverage differences do not masquerade as quality differences."""
import argparse
import datetime as dt
import glob
import json
import os
import time

from app.detection import eval_data as D
from app.detection import ml
from app.detection.engine import analyze, detect_text
from app.detection.rules import ML_CATEGORIES, RULE_CATEGORIES

CONFIGS = {
    "rules_only": {"rules": True, "ml": False, "name": True, "scope": set(RULE_CATEGORIES) & set(D.CATS)},
    "ml_only": {"rules": False, "ml": True, "name": False, "scope": set(ML_CATEGORIES)},
    "hybrid": {"rules": True, "ml": True, "name": True, "scope": (set(RULE_CATEGORIES) | set(ML_CATEGORIES)) & set(D.CATS)},
}
VALUE_CATS = {"EMAIL", "PHONE", "CARD_NUMBER", "IP_ADDRESS", "GOVERNMENT_ID"}
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "evaluation_results")


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f)}


def _r(x):
    return None if x is None else round(x, 4)


def aggregate(per_cat: dict) -> dict:
    """Micro (pooled counts) and macro (mean of per-category scores that are defined)."""
    tp = sum(c["tp"] for c in per_cat.values())
    fp = sum(c["fp"] for c in per_cat.values())
    fn = sum(c["fn"] for c in per_cat.values())
    macro = {}
    for k in ("precision", "recall", "f1"):
        vals = [c[k] for c in per_cat.values() if c[k] is not None]
        macro[k] = _r(sum(vals) / len(vals)) if vals else None
    return {"micro": prf(tp, fp, fn), "macro": macro}


def _count(gold: set, pred: set, cats, per_cat, overlap=False, examples=None, ctx=None):
    """gold/pred: sets of (start, end, category) or (key, category). Updates per_cat counts."""
    g = {x for x in gold if x[-1] in cats}
    p = {x for x in pred if x[-1] in cats}
    matched_g, matched_p = set(), set()
    for gi in g:
        for pi in p:
            if pi in matched_p:
                continue
            same = gi == pi or (overlap and len(gi) == 3 and gi[2] == pi[2] and gi[0] < pi[1] and pi[0] < gi[1])
            if same:
                matched_g.add(gi)
                matched_p.add(pi)
                break
    for x in matched_g:
        per_cat[x[-1]]["tp"] += 1
    for x in g - matched_g:
        per_cat[x[-1]]["fn"] += 1
        if examples is not None:
            examples["fn"].append({"item": ctx, "category": x[-1]})
    for x in p - matched_p:
        per_cat[x[-1]]["fp"] += 1
        if examples is not None:
            examples["fp"].append({"item": ctx, "category": x[-1]})


def _blank(cats):
    return {c: {"tp": 0, "fp": 0, "fn": 0} for c in cats}


def _finish(per_cat):
    return {c: prf(v["tp"], v["fp"], v["fn"]) for c, v in per_cat.items()}


def eval_entities(cfg: dict, split: str, overlap: bool = False) -> dict:
    items = D.text_items(split)
    cats = sorted(D.CATS)
    out = {}
    for scope_name, scope in (("full", set(cats)), ("in_scope", cfg["scope"])):
        per, ex = _blank(sorted(scope)), {"fp": [], "fn": []}
        for i, (text, gold) in enumerate(items):
            errs: list = []
            pred = {(f.start, f.end, f.category) for f in detect_text(text, use_ml=cfg["ml"], ml_error=errs, use_rules=cfg["rules"])}
            if cfg["ml"] and errs:
                raise ml.MLUnavailable(errs[0])
            _count(set(gold), pred, scope, per, overlap, ex, {"split": split, "index": i})
        res = _finish(per)
        out[scope_name] = {"per_category": res, **aggregate(res), "examples": {k: v[:8] for k, v in ex.items()}}
    return out


def eval_values(cfg: dict, split: str) -> dict:
    data = D.DEV_VALUES if split == "dev" else D.HELD_OUT_VALUES
    out = {}
    for scope_name, scope in (("full", VALUE_CATS), ("in_scope", cfg["scope"] & VALUE_CATS)):
        per, ex = _blank(sorted(scope)), {"fp": [], "fn": []}
        for i, (val, gold) in enumerate(data):
            pred = {(i, f.category) for f in detect_text(val or "", use_ml=cfg["ml"], use_rules=cfg["rules"])}
            _count({(i, c) for c in gold}, pred, scope, per, False, ex, {"split": split, "index": i})
        res = _finish(per)
        out[scope_name] = {"per_category": res, **aggregate(res), "examples": {k: v[:8] for k, v in ex.items()}}
    return out


def eval_columns(cfg: dict, split: str) -> dict:
    data = D.DEV_COLUMNS if split == "dev" else D.HELD_OUT_COLUMNS
    tp = fp = fn = tn = 0
    ex = {"fp": [], "fn": []}
    for name, values, gold_sens, _cat in data:
        res = analyze([name], [[v] for v in values] or [[None]], use_ml=cfg["ml"], use_rules=cfg["rules"], use_name=cfg["name"])
        pred = res["columns"][0]["status"] in ("detected", "suspected") and res["columns"][0]["category"] is not None
        if pred and gold_sens:
            tp += 1
        elif pred:
            fp += 1
            ex["fp"].append({"column": name})
        elif gold_sens:
            fn += 1
            ex["fn"].append({"column": name})
        else:
            tn += 1
    return {"sensitive_column": {**prf(tp, fp, fn), "tn": tn}, "examples": ex}


def run(split: str, tag: str) -> dict:
    splits = ["dev", "held_out"] if split == "both" else [split]
    ml_ok = ml.available()
    st = ml.status()
    report = {"tag": tag, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "splits": splits, "dataset_version": D.DATASET_VERSION,
              "ml_status": {k: st[k] for k in ("model", "state", "error", "threshold")},
              "dataset": {"text_items": {s: len(D.text_items("dev" if s == "dev" else "held")) for s in splits},
                          "note": "synthetic; see eval_data.py annotation rules"},
              "configs": {}}
    for name, cfg in CONFIGS.items():
        if cfg["ml"] and not ml_ok:
            report["configs"][name] = {"available": False, "reason": st["error"]}
            continue
        entry = {"available": True, "categories_in_scope": sorted(cfg["scope"]), "splits": {}}
        for s in splits:
            sp = "dev" if s == "dev" else "held"
            t0 = time.perf_counter()
            entry["splits"][s] = {"entity_exact": eval_entities(cfg, sp), "entity_overlap": eval_entities(cfg, sp, overlap=True),
                                  "value": eval_values(cfg, sp), "column": eval_columns(cfg, sp),
                                  "runtime_seconds": None}
            entry["splits"][s]["runtime_seconds"] = round(time.perf_counter() - t0, 2)
        report["configs"][name] = entry
    return report


def previous(tag: str) -> dict | None:
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as fh:
        return json.load(fh)


def _f1(report, cfg, split, scope="full", unit="entity_exact"):
    try:
        return report["configs"][cfg]["splits"][split][unit][scope]["micro"]["f1"]
    except (KeyError, TypeError):
        return None


def diff(old: dict | None, new: dict) -> list[str]:
    if not old:
        return ["No previous baseline to compare against."]
    lines = []
    if old.get("dataset_version", "1") != new.get("dataset_version"):
        lines.append(f"NOTE: dataset version changed ({old.get('dataset_version', '1')} -> {new.get('dataset_version')}); scores below are not like-for-like.")
    for cfg in CONFIGS:
        for s in new["splits"]:
            a, b = _f1(old, cfg, s), _f1(new, cfg, s)
            if a is None or b is None:
                continue
            flag = "  <-- REGRESSION" if b < a - 1e-9 else ""
            lines.append(f"{cfg:<11} {s:<8} entity-exact micro F1 {a:.4f} -> {b:.4f}{flag}")
    return lines or ["Previous baseline has no comparable results."]


def markdown(report: dict) -> str:
    rows = ["| Config | Split | Scope | Precision | Recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|---|---|"]
    for cfg, e in report["configs"].items():
        if not e.get("available"):
            rows.append(f"| {cfg} | - | - | unavailable | unavailable | unavailable | - | - | - |")
            continue
        for s, d in e["splits"].items():
            for scope in ("full", "in_scope"):
                m = d["entity_exact"][scope]["micro"]
                rows.append(f"| {cfg} | {s} | {scope} | {m['precision']} | {m['recall']} | {m['f1']} | {m['tp']} | {m['fp']} | {m['fn']} |")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "held_out", "both"], default="both")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    old = previous(a.tag)
    rep = run(a.split, a.tag)
    print(markdown(rep))
    print("\nChange vs previous baseline:")
    print("\n".join(diff(old, rep)))
    if not a.no_save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{a.tag}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2)
        print("\nSaved", os.path.normpath(path))


if __name__ == "__main__":
    main()

# Detection evaluation

Command (from `backend/`; `HF_HOME` only if the model cache is not in the default location):

```
.venv/Scripts/python.exe -m app.detection.evaluation --split both --tag <name>
```

Code: `app/detection/evaluation.py`; labelled data and annotation rules: `app/detection/eval_data.py`. Every run writes a new timestamped JSON to `backend/evaluation_results/` (earlier baselines are kept) and prints a diff against the previous run. If the ML model cannot load, the ML-only and hybrid rows say "unavailable"; nothing is estimated. Tests: `tests/test_detection.py` (metric maths, zero denominators, exact-span vs overlap matching, reproducibility, unavailable model).

Recorded runs (all kept, none overwritten): `20261030-200347-baseline-v1.json` (dataset v1), `20261030-200834-baseline-v2.json` (v2), `20261030-204437-baseline-v3.json` (v3, current). Model: `urchade/gliner_multi_pii-v1`, threshold 0.5, CPU, one run each (the rules are deterministic; the model is deterministic on CPU for fixed input, but a single run is not a variance estimate).

## Setup

- Configurations: **Rules only** (regex + validators + column-name heuristics), **ML only** (GLiNER, PERSON/LOCATION/ORGANIZATION, no name heuristics), **Hybrid** (both, merged by the rules in `docs/DETECTION.md`).
- Units, never mixed: *entity* (exact span + category on free text), *value* (which structured categories a cell holds), *column* (sensitive or not).
- Scopes: **full** scores all 8 gold categories, so a configuration that cannot detect a category takes false negatives; **in_scope** scores only the categories the configuration is built for (rules: EMAIL, PHONE, CARD_NUMBER, IP_ADDRESS, GOVERNMENT_ID; ML: PERSON, LOCATION, ORGANIZATION). Coverage differences and quality differences are separate.
- Data (v3): 33 dev + 28 held-out text items (including empty, null, malformed, duplicate, nested and ambiguous cases), 18 + 14 value items, 10 + 10 column items. DEV was used while writing the rules; HELD_OUT was written before the first evaluation run.

## Results (entity level, exact span, micro-averaged)

| Config | Split | Scope | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|---|---|
| rules_only | dev | full | 1.0 | 0.586 | 0.739 | 17 | 0 | 12 |
| rules_only | dev | in_scope | 1.0 | 1.0 | 1.0 | 17 | 0 | 0 |
| rules_only | held_out | full | 1.0 | 0.571 | 0.727 | 16 | 0 | 12 |
| rules_only | held_out | in_scope | 1.0 | 1.0 | 1.0 | 16 | 0 | 0 |
| ml_only | dev | full | 0.476 | 0.345 | 0.400 | 10 | 11 | 19 |
| ml_only | dev | in_scope | 0.476 | 0.833 | 0.606 | 10 | 11 | 2 |
| ml_only | held_out | full | 0.611 | 0.393 | 0.478 | 11 | 7 | 17 |
| ml_only | held_out | in_scope | 0.611 | 0.917 | 0.733 | 11 | 7 | 1 |
| hybrid | dev | full | 0.794 | 0.931 | 0.857 | 27 | 7 | 2 |
| hybrid | held_out | full | 0.844 | 0.964 | 0.900 | 27 | 5 | 1 |

Other units, held-out: value-level F1 (rule categories) rules 0.933, hybrid 0.933 (ML-only has no structured categories: undefined). Column-level sensitive-column F1: rules 1.0, ML-only 0.60, hybrid 1.0. Dev column-level: rules 0.833, ML-only 0.444, hybrid 0.857. Overlap-tolerant entity F1 (held-out, full): rules 0.727, ML-only 0.522, hybrid 0.933. Runtime for a split: rules 0.01 s; ML-only and hybrid 14-26 s on CPU (dominated by the model).

Hybrid per category, held-out (P / R / F1): CARD_NUMBER, EMAIL, GOVERNMENT_ID, IP_ADDRESS, PHONE all 1.0; PERSON 0.80 / 1.0 / 0.89; ORGANIZATION 0.67 / 0.67 / 0.67; LOCATION 0.50 / 1.0 / 0.67.

## What the measurements say

- Hybrid beats rules alone on held-out data (0.900 vs 0.727 entity F1, 0.933 vs 0.727 overlap-tolerant) **because the rules cannot detect names, places or organisations at all**; on the categories the rules do cover, hybrid equals rules (the ML spans are suppressed where rules fire). The gain is coverage, bought with precision loss: hybrid precision is 0.84 vs 1.0, and it is 14-26 s of CPU per split instead of 0.01 s.
- ML-only is weak on its own (F1 0.73 even in its own scope, precision 0.61). The model labels many things we did not annotate.
- Inspecting every remaining hybrid disagreement (v3): all are model behaviour or boundary choices, not label errors: `finance team` and `branch` tagged as organisations, `She` and `I` tagged as persons, `300.1.1.1` and `Build 999.10.10.10` tagged as locations, `name@@example.com` tagged as a person (malformed e-mail), `Initech hardware` instead of `Initech`, `221B Baker Street, London` as one span where we labelled two, and the word "jordan" in a list tagged as a place (a deliberately ambiguous item). These are real weaknesses of the model on short synthetic text.
- Label correction (v2 -> v3): "UK" in "for the UK desk" is a country name; annotation rule 3 labels it LOCATION and v1/v2 had omitted it. Fixing it moved hybrid held-out F1 0.881 -> 0.900 and ML-only 0.444 -> 0.478, and rules held-out *down* 0.744 -> 0.727 (the rules cannot find it, so it became a false negative). Only that label was changed. Because the correction was made after the held-out set had been scored, that set is no longer a clean untouched hold-out.
- The column-level result changed little between rules and hybrid because the dev/held-out columns are small and clean.
- Dataset v1 had no GOVERNMENT_ID items and hid a real rule bug (a 16-digit number failing Luhn was partly matched as a 12-digit id). It was found by a unit test, fixed (`rules.AADHAAR_GROUPED`), and the dataset was extended to v2. v1 and v2 scores are not like-for-like, and the diff prints that warning.

## Limitations

Synthetic, small (about 60 text items), mostly clean English, written by the same people who wrote the rules, so the 1.0 in-scope rule scores say the rules do what we designed, not that they will on real data. No confidence intervals. One model checkpoint and one threshold; no threshold tuning was done. Runtime is wall-clock on this CPU, and memory use was not measured. These numbers do not establish production accuracy.

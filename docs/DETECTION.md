# Hybrid PII detection

Code: `backend/app/detection/`. API: `POST /api/b1/upload/analyze`, `GET /api/b1/upload/latest`, `GET /api/b1/detection/status`. UI: Data Discovery > "Analyse a CSV dataset" (Admin / Security Admin, the same role that may scan a database).

The core path (upload, detection, risk, masking, assistant answers, evaluation) is plain Python and FastAPI. It does not call n8n, Presidio, a vector store or any external service except, optionally, Groq for phrasing and the one-time Hugging Face model download.

## Pipeline

CSV bytes -> `csvio.parse_csv` (size, UTF-8, binary, header, duplicate columns, ragged rows) -> per column: rule detectors on every value + ML on up to `DETECTION_ML_MAX_VALUES` unique text values -> `hybrid.merge` -> column decision -> `risk.assess` -> result (counts, categories, sources, risk; never cell values). The file is never written to disk. Only the result is kept, in memory, per user, for one hour (so the assistant can answer questions); it is lost on restart.

## Detectors

| Category | Detector | Evidence |
|---|---|---|
| EMAIL | regex | pattern |
| PHONE | international / US / Indian-mobile layouts, 10-13 digits | pattern |
| CARD_NUMBER | 13-19 digits **and** Luhn | validated |
| IP_ADDRESS | IPv4, every octet 0-255, no leading zeros | validated |
| GOVERNMENT_ID | PAN shape, grouped 4-4-4 and 3-2-4 ids (never a slice of a longer digit group) | pattern |
| PERSON, LOCATION, ORGANIZATION | GLiNER (`urchade/gliner_multi_pii-v1`) | model score |
| FINANCIAL, DATE_OF_BIRTH | column-name heuristic only | metadata (never "found" in values) |

IPv6, Verhoeff-validated Aadhaar and non-English text are not handled.

## Merge and overlap rules

1. An ML span that overlaps a rule span is dropped (rules are validated and authoritative where they fire; this also removes the "person" and "organisation" the model finds inside an e-mail address).
2. Two overlapping ML spans: same category keeps the longer; different category keeps the higher score.
3. One finding per surviving span, so nothing is counted twice. Rule overlaps resolve by priority CARD > IP = EMAIL > GOVERNMENT_ID > PHONE, then length. Dropped spans are returned by `hybrid.merge` for traceability.

Each finding records its `sources` (`rule`, `ml`, `column_name`).

## Column decision

- **detected**: >= 60% of inspected values contain the category.
- **suspected**: some values match (< 60%), or only the column name suggests it. Flagged for human review, risk capped at Medium.
- **unclassified**: nothing matched. This is not "safe": detectors have limits.
- A name that disagrees with the values is reported as a conflict (uncertain).

Counts are values (cells) containing the category, each cell once per category. Rule counts are exact over every row. ML counts are exact when the column has <= `DETECTION_ML_MAX_VALUES` unique text values, otherwise extrapolated and marked `exact: false` / "(est.)".

## Risk (deterministic)

`points = sensitivity(category) + exposure - 2 if protected`. Sensitivity: CARD_NUMBER / GOVERNMENT_ID 4; FINANCIAL / DATE_OF_BIRTH 3; PERSON / PHONE / EMAIL / LOCATION / IP_ADDRESS 2; ORGANIZATION 1. Exposure: >= 50% of values +1, 5-50% 0, < 5% -1. Levels: >= 5 Critical, 4 High, 2-3 Medium, <= 1 Low. Suspected findings never exceed Medium. The ML score is not an input; every column returns its explanation string. Uploaded files carry no masking policy, so `protected` is false for them.

## ML model

- Checkpoint `urchade/gliner_multi_pii-v1` (GLiNER, Apache-2.0, fine-tuned from `gliner_multi-v2.1` on a synthetic PII set). GLiNER takes entity labels at inference time, so it is trusted only for PERSON / LOCATION / ORGANIZATION; the rules own structured identifiers. The model card publishes no accuracy numbers and its training data is synthetic; see `docs/EVALUATION.md` for what we measured.
- Install: `pip install -r requirements-ml.txt` (pulls PyTorch, about 1 GB on disk) and let the first analysis download the checkpoint (needs network once; roughly 1 GB of cache; set `HF_HOME` to choose where). After that it loads from the local cache, once per process, lazily on the first analysis that needs it (about 15-80 s on this machine's CPU) and is serialised by a lock.
- Failure handling: missing package, failed download, bad model id, out-of-memory and inference errors are caught; the status holds the error *type* only (never input text). With `DETECTION_ML_FALLBACK=rules_only` (default) the analysis completes with rules and reports `mode: rules_only` plus the reason in the API and the UI; `fail` returns HTTP 503 instead. A failed load is not retried on every request.
- Observed: even with the checkpoint cached, loading makes metadata HEAD/GET requests to huggingface.co (and the tokenizer repo `microsoft/mdeberta-v3-base`); set `HF_HUB_OFFLINE=1` to force cache-only. Not claimed: offline operation before the first download, or that the model score is a probability.

## Authorization and masking

Upload analysis needs the `b1_scan` permission (Admin / Security Admin); analysts and support get 403. Results hold only aggregates, so they cannot leak values; per-user storage means another user cannot read them. Values from the connected databases still go only through `/api/b1/query`, which applies the role's masking server-side and audits field names and strategies. The assistant has no tool that returns rows. The audit event for an upload records row/column counts, risk and mode, not file contents or names.

## Assistant

Tool `ask_about_dataset` (summary, count_category, highest_risk, column). The router validates the arguments and the role; Python computes every number from the stored findings and the reply shown is the backend's sentence, not model text, so a model cannot substitute a number. The result states exact vs estimated and the scope (rows x columns, file). With no analysis, or no Groq key, it says so.

## Configuration

`DETECTION_ML_ENABLED`, `DETECTION_ML_MODEL`, `DETECTION_ML_THRESHOLD`, `DETECTION_ML_MAX_VALUES`, `DETECTION_ML_FALLBACK`, `UPLOAD_MAX_BYTES`, `UPLOAD_MAX_ROWS` (see `backend/.env.example`; placeholders only).

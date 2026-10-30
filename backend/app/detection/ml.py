"""Optional pretrained-model detector (GLiNER). Loaded lazily once per process, inference serialised by a lock.

Failure is never silent: `status()` reports the state and every result carries `ml_used`. Error text keeps the exception TYPE only (messages can echo input).
Labels are zero-shot prompts, so the model is only trusted for the contextual categories in ML_CATEGORIES; structured identifiers stay with the rules."""
import logging
import threading
import time

from app.core.config import get_settings
from app.detection.rules import ML_CATEGORIES, Span

log = logging.getLogger("trustlayer.detection.ml")
LABELS = {"person": "PERSON", "address": "LOCATION", "city": "LOCATION", "country": "LOCATION", "organization": "ORGANIZATION", "company": "ORGANIZATION"}
MAX_CHARS = 1000

_lock = threading.Lock()
_model = None
_state = {"state": "not_loaded", "error": None, "load_seconds": None}


class MLUnavailable(RuntimeError):
    """Raised only when DETECTION_ML_FALLBACK=fail; otherwise callers fall back to rules and report it."""


def status() -> dict:
    s = get_settings()
    return {"enabled": s.detection_ml_enabled, "model": s.detection_ml_model, "state": _state["state"], "error": _state["error"],
            "load_seconds": _state["load_seconds"], "categories": list(ML_CATEGORIES), "threshold": s.detection_ml_threshold}


def reset() -> None:  # tests
    global _model
    _model = None
    _state.update(state="not_loaded", error=None, load_seconds=None)


def _load():
    global _model
    s = get_settings()
    if not s.detection_ml_enabled:
        _state.update(state="disabled", error="ML detection is disabled (DETECTION_ML_ENABLED=false)")
        raise MLUnavailable(_state["error"])
    if _model is not None:
        return _model
    if _state["state"] == "failed":
        raise MLUnavailable(_state["error"])  # do not retry a failed load on every request; restart or reset() to retry
    t0 = time.perf_counter()
    try:
        from gliner import GLiNER  # imported lazily: the package is optional
        _model = GLiNER.from_pretrained(s.detection_ml_model)
    except ImportError:
        _state.update(state="failed", error="the 'gliner' package is not installed (pip install -r requirements-ml.txt)")
    except MemoryError:
        _state.update(state="failed", error="not enough memory to load the model")
    except Exception as e:  # noqa: BLE001 - download/config/format errors; type only
        _state.update(state="failed", error=f"model could not be loaded ({type(e).__name__})")
    if _model is None:
        log.warning("ML detector unavailable: %s", _state["error"])
        raise MLUnavailable(_state["error"])
    _state.update(state="ready", error=None, load_seconds=round(time.perf_counter() - t0, 2))
    return _model


def available() -> bool:
    try:
        with _lock:
            _load()
        return True
    except MLUnavailable:
        return False


def detect_ml(text: str) -> list[Span]:
    """Spans for PERSON / LOCATION / ORGANIZATION. Raises MLUnavailable if the model cannot be used."""
    if not text or not isinstance(text, str):
        return []
    s = get_settings()
    with _lock:
        model = _load()
        try:
            ents = model.predict_entities(text[:MAX_CHARS], list(LABELS), threshold=s.detection_ml_threshold)
        except MemoryError:
            _state.update(state="failed", error="not enough memory during inference")
            raise MLUnavailable(_state["error"]) from None
        except Exception as e:  # noqa: BLE001
            log.warning("ML inference failed: %s", type(e).__name__)
            raise MLUnavailable(f"inference failed ({type(e).__name__})") from None
    out = []
    for e in ents:
        cat = LABELS.get(str(e.get("label", "")).lower())
        if cat:
            out.append(Span(int(e["start"]), int(e["end"]), cat, "ml", "model", round(float(e.get("score", 0.0)), 3)))
    return out

"""Merge rule spans and ML spans into one non-overlapping, traceable list.

Documented resolution order (docs/DETECTION.md):
  1. An ML span that overlaps any rule span is dropped: rules (checksum/format validated) are authoritative where they fire.
  2. Two ML spans that overlap: same category -> keep the longer; different category -> keep the higher model score (ties: longer).
  3. Nothing is counted twice: one finding per surviving span; dropped spans are returned in `suppressed` so the decision stays auditable.
Each finding records which detectors produced it (`sources`)."""
from dataclasses import dataclass

from app.detection.rules import Span


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    category: str
    sources: tuple[str, ...]
    evidence: str
    score: float | None = None


def _f(s: Span) -> Finding:
    return Finding(s.start, s.end, s.category, (s.source,), s.evidence, s.score)


def merge(rule_spans: list[Span], ml_spans: list[Span]) -> tuple[list[Finding], list[Span]]:
    suppressed: list[Span] = []
    ml_kept: list[Span] = []
    for m in sorted(ml_spans, key=lambda s: (-(s.score or 0), -(s.end - s.start))):
        if any(m.overlaps(r) for r in rule_spans):
            suppressed.append(m)
            continue
        clash = [k for k in ml_kept if m.overlaps(k)]
        if not clash:
            ml_kept.append(m)
            continue
        # sorted by score, so every earlier span scores >= m; a same-category longer span still replaces it
        longer_same = [k for k in clash if k.category == m.category and (m.end - m.start) > (k.end - k.start)]
        if longer_same and len(longer_same) == len(clash):
            for k in longer_same:
                ml_kept.remove(k)
                suppressed.append(k)
            ml_kept.append(m)
        else:
            suppressed.append(m)
    findings = sorted([_f(s) for s in rule_spans] + [_f(s) for s in ml_kept], key=lambda f: f.start)
    return findings, suppressed

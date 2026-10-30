"""Safe CSV intake: size, encoding, structure. Content is only ever parsed as data; nothing is written to disk."""
import csv
import io
from collections import Counter

from app.core.config import get_settings


class CSVError(ValueError):
    """User-facing, value-free validation message."""


def parse_csv(raw: bytes) -> tuple[list[str], list[list[str | None]], dict]:
    s = get_settings()
    if not raw or not raw.strip():
        raise CSVError("The file is empty.")
    if len(raw) > s.upload_max_bytes:
        raise CSVError(f"The file is larger than the {s.upload_max_bytes // 1_000_000} MB limit.")
    if b"\x00" in raw:
        raise CSVError("The file contains binary data and is not a text CSV.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CSVError("The file is not valid UTF-8. Re-save it as CSV (UTF-8).") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        raise CSVError("The file has no header row.") from None
    header = [h.strip() for h in header]
    if not any(header):
        raise CSVError("The header row is empty.")
    if len(header) > s.upload_max_columns:
        raise CSVError(f"Too many columns (limit {s.upload_max_columns}).")
    if any(not h for h in header):
        raise CSVError("The header row has a blank column name.")
    dup = sorted(n for n, c in Counter(h.lower() for h in header).items() if c > 1)
    if dup:
        raise CSVError("Duplicate column names: " + ", ".join(dup[:5]) + ".")
    rows, malformed, blank = [], 0, 0
    try:
        for r in reader:
            if not r or not any(c.strip() for c in r):
                blank += 1
                continue
            if len(r) != len(header):
                malformed += 1
                r = (r + [None] * len(header))[: len(header)]
            if len(rows) >= s.upload_max_rows:
                raise CSVError(f"Too many rows (limit {s.upload_max_rows:,}).")
            rows.append([c if c is not None and c.strip() != "" else None for c in r])
    except csv.Error:
        raise CSVError("The file is not well-formed CSV (unterminated quote or invalid structure).") from None
    return header, rows, {"rows": len(rows), "columns": len(header), "malformed_rows": malformed, "blank_rows": blank}

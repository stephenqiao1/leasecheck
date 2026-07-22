import re
from pypdf import PdfReader
from pypdf.errors import PdfReadError

class UnreadablePDF(Exception):
    """Raised when a PDF can't be opened or has no extractable text."""

def extract_text(path: str) -> tuple[str, int]:
    """Pull text out of a PDF. Returns (full_text, page_count)."""
    try:
        reader = PdfReader(path)
        # Some PDFs are encrypted with an empty password; try to unlock.
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as e:
        raise UnreadablePDF(f"Could not read PDF: {e}")

    text = "\n\n".join(pages)
    if not text.strip():
        raise UnreadablePDF(
            "No extractable text found. This may be a scanned/image-only PDF "
            "that needs OCR."
        )
    return text, len(reader.pages)

def _split_numbered(text: str) -> list[dict] | None:
    """Split on numbered clause markers like '1. ' at the start of a line.
    Returns None if fewer than 3 markers are found (not a numbered document).
    """
    marker = re.compile(r"(?m)^\s*(\d+)\.\s")
    matches = list(marker.finditer(text))
    if len(matches) < 3:
        return None

    clauses = []
    ordinal = 0
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if len(block) < 15:
            continue
        clauses.append({"ordinal": ordinal, "text": block,
                        "char_start": start, "char_end": end})
        ordinal += 1
    return clauses

def _split_paragraphs(text: str) -> list[dict]:
    """Fallback: one clause per paragraph (block of non-blank lines)."""
    clauses = []
    ordinal = 0
    for m in re.finditer(r"[^\n]+(?:\n[^\n]+)*", text):
        block = m.group().strip()
        if len(block) < 25:
            continue
        clauses.append({"ordinal": ordinal, "text": block,
                        "char_start": m.start(), "char_end": m.end()})
        ordinal += 1
    return clauses

def split_into_clauses(text: str) -> list[dict]:
    """Prefer numbered-clause splitting; fall back to paragraph splitting."""
    return _split_numbered(text) or _split_paragraphs(text)
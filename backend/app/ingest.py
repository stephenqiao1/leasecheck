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

def split_into_clauses(text: str) -> list[dict]:
    """Naive clause splitter: one clause per paragraph (block of non-blank lines).
    Tracks character offsets so the UI can highlight the exact span later.
    """
    clauses = []
    ordinal = 0
    for match in re.finditer(r"[^\n]+(?:\n[^\n]+)*", text):
        block = match.group().strip()
        if len(block) < 25:  # skip page numbers, headers, stray fragments
            continue
        clauses.append({
            "ordinal": ordinal,
            "text": block,
            "char_start": match.start(),
            "char_end": match.end(),
        })
        ordinal += 1
    return clauses
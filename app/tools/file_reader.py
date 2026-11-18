"""File reader for PDF, DOCX, TXT and MD files, locked to ONE folder.

The main danger is PATH TRAVERSAL: a request for "../../.env" or "C:/Windows/..." that
escapes the allowed folder. Defense:
  1. Join the requested path to the documents folder and resolve() it. That turns
     "..", symlinks and absolute paths into the real final location.
  2. Check that the real location is still INSIDE the documents folder.
  3. Allow only known document extensions, and limit the file size.
File contents are untrusted (a PDF can contain hidden instructions), so we wrap them.
"""

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.llm.prompts import wrap_untrusted
from app.tools.base import AgentTool, ToolError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_PDF_PAGES = 50


def resolve_safe_path(base_dir: Path, requested: str) -> Path:
    """Return the real path of `requested` inside `base_dir`, or raise ToolError.

    Error messages never include the absolute path: no need to reveal the folder layout.
    """
    base = base_dir.resolve()
    req_clean = requested.strip().lstrip("/\\")
    # If `requested` is absolute, `base / requested` becomes just `requested`;
    # the is_relative_to() check below then rejects it.
    candidate = (base / req_clean).resolve()
    if not candidate.is_relative_to(base):
        raise ToolError("Access denied: files can only be read from the documents folder.")

    # Smart alias / extension fallback if file does not exist directly
    if not candidate.is_file():
        # 1. Try appending allowed document extensions
        for ext in ALLOWED_EXTENSIONS:
            attempt = (base / f"{req_clean}{ext}").resolve()
            if attempt.is_file() and attempt.is_relative_to(base):
                candidate = attempt
                break

    # 2. Semantic fallback for common agent intent (e.g. resume / fresher jobs)
    if not candidate.is_file():
        lower_req = req_clean.lower()
        if "resume" in lower_req or "cv" in lower_req:
            for resume_name in ("resume.pdf", "resume.txt", "resume.md", "resume.docx"):
                attempt = (base / resume_name).resolve()
                if attempt.is_file():
                    candidate = attempt
                    break
        elif ("job" in lower_req and "fresher" in lower_req) or "ai_python" in lower_req:
            attempt = (base / "ai_python_fresher_jobs.md").resolve()
            if attempt.is_file():
                candidate = attempt

    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ToolError(f"File type not allowed. Allowed types: {allowed}.")
    if not candidate.is_file():
        raise ToolError(f"File not found: '{requested}'. {list_documents_hint(base)}")
    return candidate


def list_documents_hint(base: Path, limit: int = 20) -> str:
    """Tell the LLM which files exist, so it can retry with a correct name."""
    if not base.is_dir():
        return "The documents folder is empty."
    names = sorted(
        str(p.relative_to(base)).replace("\\", "/")
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    )
    if not names:
        return "The documents folder is empty."
    return "Available files: " + ", ".join(names[:limit])


def pdf_page_texts(path: Path, max_pages: int = MAX_PDF_PAGES) -> tuple[list[str], int]:
    """Text of each page (up to max_pages) and the total page count.

    Shared by read_file (this tool) and RAG ingestion (which keeps page numbers for citations).
    """
    try:
        reader = PdfReader(path)
    except PdfReadError as exc:
        raise ToolError(f"Could not read PDF: {exc}") from exc
    if reader.is_encrypted:
        raise ToolError("This PDF is password-protected.")
    return [page.extract_text() or "" for page in reader.pages[:max_pages]], len(reader.pages)


def read_pdf(path: Path) -> tuple[str, str]:
    page_texts, total_pages = pdf_page_texts(path)
    info = f"PDF, {total_pages} pages"
    if total_pages > MAX_PDF_PAGES:
        info += f" (first {MAX_PDF_PAGES} read)"
    if not any(t.strip() for t in page_texts):
        return "[No extractable text: this may be a scanned PDF that needs OCR.]", info
    text = "\n".join(f"--- Page {i} ---\n{t}" for i, t in enumerate(page_texts, start=1))
    return text, info


def read_docx(path: Path) -> tuple[str, str]:
    import docx  # python-docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:  # tables are not part of .paragraphs
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts), f"DOCX, {len(document.paragraphs)} paragraphs, {len(document.tables)} tables"


def read_text(path: Path) -> tuple[str, str]:
    # errors="replace": a wrong byte becomes "?" instead of crashing the tool.
    return path.read_text(encoding="utf-8", errors="replace"), "text file"


READERS = {".pdf": read_pdf, ".docx": read_docx, ".txt": read_text, ".md": read_text}


class FileReaderInput(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=255,
        description="File name relative to the documents folder, e.g. 'resume.pdf' or 'jobs/jd1.docx'.",
    )
    max_chars: int = Field(default=8_000, ge=100, le=50_000, description="Maximum characters to return.")


class FileReaderTool(AgentTool):
    name = "read_file"
    input_model = FileReaderInput

    def __init__(self, documents_dir: Path, *, max_file_size_mb: float = 10.0) -> None:
        self._base = documents_dir
        self._max_bytes = int(max_file_size_mb * 1024 * 1024)

    async def run(self, args: FileReaderInput) -> str:  # type: ignore[override]
        path = resolve_safe_path(self._base, args.path)
        size = path.stat().st_size
        if size > self._max_bytes:
            raise ToolError(f"File is too large ({size / 1_048_576:.1f} MB).")

        # PDF parsing is slow, blocking work: do it in a thread so the server stays responsive.
        text, info = await asyncio.to_thread(READERS[path.suffix.lower()], path)
        if len(text) > args.max_chars:
            text = text[: args.max_chars] + f"\n...[cut at {args.max_chars} characters]"
        return wrap_untrusted(f"File: {path.name} ({info})\n\n{text}", source=f"file/{path.name}")

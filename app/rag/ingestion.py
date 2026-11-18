"""Document ingestion: files -> clean text -> overlapping chunks -> vectors in ChromaDB.

Why chunk? An embedding squeezes a whole text into one vector. A 20-page PDF in one
vector is a blurry average that matches nothing well. ~800-character chunks are
specific enough to match a question and still carry enough context to answer it.

Why overlap? A sentence cut at a chunk border would be half in each chunk. With 150
characters of overlap, the border region appears in both chunks, so it stays findable.

Each chunk's metadata records its source file, page and the file's content hash:
  - source + page -> answers can cite where information came from
  - content hash  -> re-ingesting an unchanged file is skipped (no wasted embedding work);
                     a changed file has its old chunks deleted and is re-chunked
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.memory.vector_store import VectorStore
from app.tools.base import ToolError
from app.tools.file_reader import (
    ALLOWED_EXTENSIONS,
    pdf_page_texts,
    read_docx,
    read_text,
    resolve_safe_path,
)

logger = logging.getLogger(__name__)

NO_PAGE = 0  # ChromaDB metadata can't store None, so 0 means "no page numbers" (txt/docx)
MAX_PAGES_TO_INGEST = 500


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class IngestReport:
    source: str
    status: Literal["ingested", "unchanged", "skipped", "failed"]
    chunks: int = 0
    detail: str = ""


@dataclass
class DocumentInfo:
    source: str
    chunks: int
    pages: list[int] = field(default_factory=list)
    ingested_at: str = ""


def clean_text(text: str) -> str:
    """Normalize whitespace but keep paragraph breaks (the splitter uses them)."""
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)  # runs of spaces/tabs -> one space
    text = re.sub(r"\n[ \t]+", "\n", text)  # spaces at line starts
    text = re.sub(r"\n{3,}", "\n\n", text)  # 3+ newlines -> one blank line
    return text.strip()


def load_pages(path: Path) -> list[tuple[int, str]]:
    """(page_number, text) pairs. PDFs keep real page numbers; other files are one 'page' 0."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        texts, _ = pdf_page_texts(path, max_pages=MAX_PAGES_TO_INGEST)
        return [(number, clean_text(t)) for number, t in enumerate(texts, start=1) if t.strip()]
    text, _ = read_docx(path) if suffix == ".docx" else read_text(path)
    text = clean_text(text)
    return [(NO_PAGE, text)] if text else []


def file_hash(path: Path) -> str:
    """SHA-256 of the file's bytes: changes whenever the content changes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chunk_pages(
    pages: list[tuple[int, str]], *, source: str, doc_hash: str, chunk_size: int, overlap: int
) -> list[Chunk]:
    """Split pages into overlapping chunks with metadata. Chunks never span two pages,
    so every chunk has exactly one page to cite."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        # Try to split at paragraphs first, then lines, sentences, words, and only
        # as a last resort in the middle of a word.
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    chunks: list[Chunk] = []
    for page, text in pages:
        for piece in splitter.split_text(text):
            index = len(chunks)
            chunks.append(
                Chunk(
                    # Deterministic id: same file content -> same ids.
                    id=f"{source}::{doc_hash[:12]}::{index}",
                    text=piece,
                    metadata={
                        "source": source,
                        "page": page,
                        "chunk_index": index,
                        "doc_hash": doc_hash,
                        "ingested_at": ingested_at,
                    },
                )
            )
    return chunks


class DocumentIngestor:
    def __init__(
        self,
        store: VectorStore,
        documents_dir: Path,
        *,
        chunk_size: int = 800,
        overlap: int = 150,
        max_file_size_mb: float = 10.0,
        collection: str = "documents",
    ) -> None:
        self._store = store
        self._dir = documents_dir
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_bytes = int(max_file_size_mb * 1024 * 1024)
        self.collection = collection

    async def ingest_file(self, relative_path: str) -> IngestReport:
        """Ingest one file from the documents folder. Never raises: returns a report."""
        try:
            # Same protection as read_file: no "../" escapes, allowed types only.
            path = resolve_safe_path(self._dir, relative_path)
        except ToolError as exc:
            return IngestReport(source=relative_path, status="failed", detail=str(exc))
        source = path.relative_to(self._dir.resolve()).as_posix()  # "jobs/jd1.pdf"

        if path.stat().st_size > self._max_bytes:
            return IngestReport(source=source, status="skipped", detail="file too large")

        doc_hash = await asyncio.to_thread(file_hash, path)
        existing = await self._store.get(self.collection, where={"source": source})
        if existing and all(meta.get("doc_hash") == doc_hash for _, meta in existing):
            return IngestReport(source=source, status="unchanged", chunks=len(existing))

        try:
            pages = await asyncio.to_thread(load_pages, path)
        except ToolError as exc:  # e.g. encrypted PDF
            return IngestReport(source=source, status="failed", detail=str(exc))
        if not pages:
            return IngestReport(source=source, status="skipped", detail="no extractable text (scanned PDF?)")

        chunks = chunk_pages(
            pages, source=source, doc_hash=doc_hash, chunk_size=self._chunk_size, overlap=self._overlap
        )
        if existing:  # the file changed: remove the old version's chunks first
            await self._store.delete(self.collection, where={"source": source})
        await self._store.upsert(
            self.collection,
            [c.id for c in chunks],
            [c.text for c in chunks],
            [c.metadata for c in chunks],
        )
        logger.info("Ingested %s: %d pages -> %d chunks", source, len(pages), len(chunks))
        return IngestReport(source=source, status="ingested", chunks=len(chunks))

    async def ingest_all(self) -> list[IngestReport]:
        """Ingest every allowed file in the documents folder (subfolders included)."""
        if not self._dir.is_dir():
            return []
        paths = sorted(
            p for p in self._dir.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
        )
        reports = []
        for path in paths:  # one at a time: embedding is CPU/API heavy
            rel = path.relative_to(self._dir).as_posix()
            try:
                reports.append(await self.ingest_file(rel))
            except Exception as exc:  # one bad file must not stop the others
                logger.exception("Ingestion of %s failed", rel)
                reports.append(IngestReport(source=rel, status="failed", detail=type(exc).__name__))
        return reports

    async def list_documents(self) -> list[DocumentInfo]:
        docs: dict[str, DocumentInfo] = {}
        for _, meta in await self._store.get(self.collection):
            source = str(meta.get("source", "?"))
            info = docs.setdefault(source, DocumentInfo(source=source, chunks=0))
            info.chunks += 1
            page = int(meta.get("page", NO_PAGE))
            if page != NO_PAGE and page not in info.pages:
                info.pages.append(page)
            info.ingested_at = str(meta.get("ingested_at", ""))
        for info in docs.values():
            info.pages.sort()
        return sorted(docs.values(), key=lambda d: d.source)

    async def delete_document(self, source: str) -> int:
        """Remove a document's chunks from the knowledge base (the file itself stays)."""
        existing = await self._store.get(self.collection, where={"source": source})
        if existing:
            await self._store.delete(self.collection, where={"source": source})
        return len(existing)

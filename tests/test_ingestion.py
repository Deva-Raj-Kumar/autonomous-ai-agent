"""Ingestion tests: cleaning, chunking, hashing, and the full ingest pipeline
(real in-memory ChromaDB, mocked embedder, temporary documents folder)."""

import uuid
from pathlib import Path

import docx
import pytest

from app.memory.vector_store import VectorStore, make_chroma_client
from app.rag.ingestion import NO_PAGE, DocumentIngestor, chunk_pages, clean_text, load_pages
from tests.helpers import make_embedder_mock, make_pdf_bytes

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------- pure parts
def test_clean_text_normalizes_whitespace_but_keeps_paragraphs() -> None:
    raw = "Title\r\n\r\n\r\n\r\nLine   with    spaces\n   indented\x00"

    assert clean_text(raw) == "Title\n\nLine with spaces\nindented"


def test_chunks_respect_size_overlap_and_pages() -> None:
    page1 = " ".join(f"word{i}" for i in range(200))  # ~1,500 characters
    page2 = "Short second page."

    chunks = chunk_pages([(1, page1), (2, page2)], source="a.pdf", doc_hash="abc123" * 10,
                         chunk_size=300, overlap=60)

    assert all(len(c.text) <= 300 for c in chunks)
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert set(first) & set(second)  # consecutive chunks share words: the overlap
    assert chunks[-1].text == "Short second page." and chunks[-1].metadata["page"] == 2
    assert all(c.metadata["page"] == 1 for c in chunks[:-1])  # no chunk spans two pages
    assert chunks[0].id == "a.pdf::abc123abc123::0"  # deterministic ids
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_load_pages_keeps_pdf_page_numbers(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(make_pdf_bytes("Hello from page one"))
    (tmp_path / "b.txt").write_text("Plain text", encoding="utf-8")
    (tmp_path / "blank.txt").write_text("   \n\n  ", encoding="utf-8")

    assert load_pages(tmp_path / "a.pdf") == [(1, "Hello from page one")]
    assert load_pages(tmp_path / "b.txt") == [(NO_PAGE, "Plain text")]
    assert load_pages(tmp_path / "blank.txt") == []


# ------------------------------------------------------------- full pipeline
@pytest.fixture
def docs(tmp_path: Path) -> Path:
    folder = tmp_path / "documents"
    (folder / "jobs").mkdir(parents=True)
    (folder / "notes.txt").write_text("AI engineers need Python and SQL.", encoding="utf-8")
    (folder / "jobs" / "jd.pdf").write_bytes(make_pdf_bytes("Bengaluru ML intern needs PyTorch"))
    document = docx.Document()
    document.add_paragraph("Resume: fresher with FastAPI projects")
    document.save(folder / "resume.docx")
    (tmp_path / "secret.txt").write_text("API_KEY=123", encoding="utf-8")  # outside the folder
    return folder


@pytest.fixture
def ingestor(docs: Path) -> DocumentIngestor:
    store = VectorStore(make_chroma_client(None), make_embedder_mock())
    return DocumentIngestor(store, docs, chunk_size=200, overlap=40, collection=f"t_{uuid.uuid4().hex[:10]}")


async def test_ingest_all_formats_including_subfolders(ingestor: DocumentIngestor) -> None:
    reports = {r.source: r for r in await ingestor.ingest_all()}

    assert {s: r.status for s, r in reports.items()} == {
        "jobs/jd.pdf": "ingested", "notes.txt": "ingested", "resume.docx": "ingested",
    }
    docs = {d.source: d for d in await ingestor.list_documents()}
    assert docs["jobs/jd.pdf"].pages == [1]
    assert docs["notes.txt"].pages == []  # text files have no page numbers


async def test_unchanged_files_are_not_embedded_again(ingestor: DocumentIngestor) -> None:
    await ingestor.ingest_all()
    calls_after_first = ingestor._store.embedder.embed_documents.await_count

    reports = await ingestor.ingest_all()

    assert {r.status for r in reports} == {"unchanged"}
    assert ingestor._store.embedder.embed_documents.await_count == calls_after_first  # zero new calls


async def test_changed_file_replaces_old_chunks(ingestor: DocumentIngestor, docs: Path) -> None:
    await ingestor.ingest_file("notes.txt")
    (docs / "notes.txt").write_text("Completely new content about Docker. " * 20, encoding="utf-8")

    report = await ingestor.ingest_file("notes.txt")

    assert report.status == "ingested" and report.chunks > 1
    stored = await ingestor._store.get(ingestor.collection, where={"source": "notes.txt"})
    assert len(stored) == report.chunks  # no leftovers from the old version
    assert len({meta["doc_hash"] for _, meta in stored}) == 1


async def test_path_traversal_is_refused(ingestor: DocumentIngestor) -> None:
    report = await ingestor.ingest_file("../secret.txt")

    assert report.status == "failed" and "Access denied" in report.detail
    ingestor._store.embedder.embed_documents.assert_not_awaited()


async def test_blank_and_corrupt_files_do_not_stop_the_batch(ingestor: DocumentIngestor, docs: Path) -> None:
    (docs / "blank.txt").write_text("   ", encoding="utf-8")
    (docs / "broken.pdf").write_bytes(b"this is not really a pdf")

    reports = {r.source: r.status for r in await ingestor.ingest_all()}

    assert reports["blank.txt"] == "skipped"
    assert reports["broken.pdf"] == "failed"
    assert reports["notes.txt"] == "ingested"  # good files still processed


async def test_too_large_file_is_skipped(docs: Path) -> None:
    (docs / "big.txt").write_text("x" * 5_000, encoding="utf-8")
    store = VectorStore(make_chroma_client(None), make_embedder_mock())
    small = DocumentIngestor(store, docs, max_file_size_mb=0.001, collection=f"t_{uuid.uuid4().hex[:10]}")

    assert (await small.ingest_file("big.txt")).status == "skipped"


async def test_delete_document(ingestor: DocumentIngestor) -> None:
    await ingestor.ingest_all()

    assert await ingestor.delete_document("notes.txt") >= 1
    assert "notes.txt" not in {d.source for d in await ingestor.list_documents()}
    assert await ingestor.delete_document("notes.txt") == 0

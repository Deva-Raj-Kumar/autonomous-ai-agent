"""API tests for /knowledge. The KnowledgeBase is a create_autospec mock; uploads write
to a temporary documents folder."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_knowledge_base, get_llm_service
from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.main import app
from app.rag.ingestion import DocumentInfo, DocumentIngestor, IngestReport
from app.rag.retrieval import KnowledgeBase, RAGAnswer, RetrievedChunk


@pytest.fixture
def kb() -> KnowledgeBase:
    mock = create_autospec(KnowledgeBase, instance=True)
    # `ingestor` is set in __init__ (an instance attribute), so autospec can't see it:
    # attach a mock for it explicitly.
    mock.ingestor = create_autospec(DocumentIngestor, instance=True)
    return mock


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    return tmp_path / "documents"


@pytest.fixture
def client(kb, mock_llm, docs_dir: Path) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, google_api_key="k", documents_dir=docs_dir, max_file_size_mb=0.01)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_knowledge_base] = lambda: kb
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def chunk() -> RetrievedChunk:
    return RetrievedChunk(id="1", text="Python needed", source="jd.pdf", page=1, similarity=0.6, score=0.9)


def test_ingest_returns_reports(client: TestClient, kb) -> None:
    kb.ingestor.ingest_all.return_value = [IngestReport(source="a.txt", status="ingested", chunks=3)]

    body = client.post("/knowledge/ingest").json()

    assert body == [{"source": "a.txt", "status": "ingested", "chunks": 3, "detail": ""}]


def test_list_and_delete_documents(client: TestClient, kb) -> None:
    kb.ingestor.list_documents.return_value = [DocumentInfo(source="a.pdf", chunks=4, pages=[1, 2])]
    kb.ingestor.delete_document.side_effect = [4, 0]  # first call deletes, second finds nothing

    assert client.get("/knowledge/documents").json()[0]["pages"] == [1, 2]
    assert client.delete("/knowledge/documents/jobs/a.pdf").status_code == 204
    kb.ingestor.delete_document.assert_awaited_with("jobs/a.pdf")  # {source:path} keeps the folder
    assert client.delete("/knowledge/documents/jobs/a.pdf").status_code == 404


def test_search(client: TestClient, kb) -> None:
    kb.search.return_value = [chunk()]

    body = client.post("/knowledge/search", json={"query": "skills", "k": 3}).json()

    assert body[0]["source"] == "jd.pdf"
    kb.search.assert_awaited_once_with("skills", k=3)


def test_ask_and_llm_failure(client: TestClient, kb, mock_llm) -> None:
    kb.answer.return_value = RAGAnswer(answer="Python [1]", sources=[chunk()], cited=[1], invalid_citations=[])

    assert client.post("/knowledge/ask", json={"question": "skills?"}).json()["cited"] == [1]
    kb.answer.assert_awaited_once_with("skills?", mock_llm, k=None)

    kb.answer.side_effect = LLMError("quota")
    assert client.post("/knowledge/ask", json={"question": "skills?"}).status_code == 502


# ------------------------------------------------------------------- upload
def test_upload_saves_and_ingests(client: TestClient, kb, docs_dir: Path) -> None:
    kb.ingestor.ingest_file.return_value = IngestReport(source="notes.txt", status="ingested", chunks=1)

    response = client.post("/knowledge/upload", files={"file": ("notes.txt", b"hello", "text/plain")})

    assert response.status_code == 201
    assert (docs_dir / "notes.txt").read_bytes() == b"hello"
    kb.ingestor.ingest_file.assert_awaited_once_with("notes.txt")


def test_upload_strips_folders_from_the_name(client: TestClient, kb, docs_dir: Path, tmp_path: Path) -> None:
    kb.ingestor.ingest_file.return_value = IngestReport(source="evil.txt", status="ingested")

    client.post("/knowledge/upload", files={"file": ("../../evil.txt", b"x", "text/plain")})

    assert (docs_dir / "evil.txt").exists()  # saved INSIDE the documents folder
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()


@pytest.mark.parametrize(
    ("filename", "status_code"),
    [("virus.exe", 415), (".env", 400), ("noextension", 415), ("", 422)],
)
def test_upload_rejects_bad_names(client: TestClient, kb, filename: str, status_code: int) -> None:
    response = client.post("/knowledge/upload", files={"file": (filename, b"x", "text/plain")})

    assert response.status_code == status_code
    kb.ingestor.ingest_file.assert_not_awaited()


def test_upload_rejects_large_files(client: TestClient, kb, docs_dir: Path) -> None:
    big = b"x" * 20_000  # the test settings allow 0.01 MB (~10 KB)

    response = client.post("/knowledge/upload", files={"file": ("big.txt", big, "text/plain")})

    assert response.status_code == 413
    assert not (docs_dir / "big.txt").exists()  # nothing was written


def test_knowledge_unavailable_is_503() -> None:
    with TestClient(app) as client:
        client.app.state.knowledge_base = None  # e.g. the vector store failed at startup
        response = client.get("/knowledge/documents")

    assert response.status_code == 503

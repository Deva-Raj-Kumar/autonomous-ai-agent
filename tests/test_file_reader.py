"""File reader tests: each format, plus path-traversal and file-type attacks.

pytest's tmp_path fixture gives every test its own empty temporary folder.
"""

from pathlib import Path

import docx
import pytest

from app.tools.base import ToolError
from app.tools.file_reader import FileReaderInput, FileReaderTool
from tests.helpers import make_pdf_bytes

pytestmark = pytest.mark.anyio


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    folder = tmp_path / "documents"
    folder.mkdir()
    (folder / "notes.txt").write_text("Python, SQL and LLM APIs", encoding="utf-8")
    (folder / "jd.pdf").write_bytes(make_pdf_bytes("AI Engineer needs Python"))
    document = docx.Document()
    document.add_paragraph("Resume of a fresher")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Python"
    document.save(folder / "resume.docx")
    (folder / "script.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("API_KEY=123", encoding="utf-8")  # OUTSIDE documents
    return folder


async def read(folder: Path, path: str, **kwargs) -> str:
    return await FileReaderTool(folder, **kwargs).run(FileReaderInput(path=path))


async def test_reads_txt(docs: Path) -> None:
    output = await read(docs, "notes.txt")

    assert "Python, SQL and LLM APIs" in output
    assert output.startswith('<untrusted_data source="file/notes.txt">')


async def test_reads_pdf(docs: Path) -> None:
    output = await read(docs, "jd.pdf")

    assert "PDF, 1 pages" in output
    assert "AI Engineer needs Python" in output


async def test_reads_docx_including_tables(docs: Path) -> None:
    output = await read(docs, "resume.docx")

    assert "Resume of a fresher" in output
    assert "Skill | Python" in output


@pytest.mark.parametrize("attack", ["../secret.txt", "..\\secret.txt", "sub/../../secret.txt"])
async def test_path_traversal_is_blocked(docs: Path, attack: str) -> None:
    with pytest.raises(ToolError, match="Access denied"):
        await read(docs, attack)


async def test_absolute_path_is_blocked(docs: Path) -> None:
    outside = str(docs.parent / "secret.txt")

    with pytest.raises(ToolError, match="Access denied"):
        await read(docs, outside)


@pytest.mark.parametrize("name", ["script.py", ".env", "data.exe"])
async def test_disallowed_file_types(docs: Path, name: str) -> None:
    with pytest.raises(ToolError, match="File type not allowed"):
        await read(docs, name)


async def test_missing_file_lists_available_files(docs: Path) -> None:
    with pytest.raises(ToolError, match="Available files: jd.pdf, notes.txt, resume.docx"):
        await read(docs, "missing.txt")


async def test_file_size_limit(docs: Path) -> None:
    (docs / "big.txt").write_text("x" * 2_000_000, encoding="utf-8")

    with pytest.raises(ToolError, match="too large"):
        await read(docs, "big.txt", max_file_size_mb=1)


async def test_output_is_cut_to_max_chars(docs: Path) -> None:
    (docs / "long.txt").write_text("y" * 5_000, encoding="utf-8")

    output = await FileReaderTool(docs).run(FileReaderInput(path="long.txt", max_chars=100))

    assert "[cut at 100 characters]" in output

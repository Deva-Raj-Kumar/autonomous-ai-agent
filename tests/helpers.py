"""Small helpers shared by tests. (Mocks themselves come from unittest.mock.)"""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.language_models import BaseChatModel


def make_chat_model_mock() -> MagicMock:
    """A mock LangChain chat model.

    spec=BaseChatModel: the mock only has attributes a real chat model has, so a typo
    like model.ainvok(...) fails instead of silently returning another mock.
    ainvoke is async, so it gets an AsyncMock (awaiting a plain MagicMock fails).
    """
    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock()
    return model


def tool_call(name: str, args: dict, call_id: str = "call-1") -> dict:
    """Build a tool-call dict in the format LangChain models produce."""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def make_pdf_bytes(text: str) -> bytes:
    """Build a minimal valid one-page PDF containing `text` (for file-reader tests).

    A PDF is a list of numbered objects plus an "xref" table giving each object's
    byte offset. We compute the offsets so pypdf can parse the file.
    """
    safe = text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
    stream = f"BT /F1 18 Tf 72 720 Td ({safe}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


FAKE_EMBEDDING_DIM = 256


def bag_of_words_vector(text: str) -> list[float]:
    """Deterministic stand-in for a real embedding: each word adds 1 to a bucket chosen
    by a stable hash. Texts sharing words point in similar directions, so cosine
    similarity behaves sensibly. (It knows nothing about MEANING; live tests cover that.)"""
    import hashlib

    from app.memory.long_term import tokenize

    vector = [0.0] * FAKE_EMBEDDING_DIM
    for word in tokenize(text):
        bucket = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16) % FAKE_EMBEDDING_DIM
        vector[bucket] += 1.0
    if not any(vector):
        vector[0] = 1.0  # avoid an all-zero vector (cosine is undefined for it)
    return vector


def make_embedder_mock(name: str = "fake-bow", floor: float = 0.1, strong: float = 0.8):
    """An autospec'd Embedder whose async methods return bag-of-words vectors.

    The mock records every call (assert_awaited..., await_count), while side_effect
    supplies realistic return values. relevance() runs the REAL Embedder logic.
    """
    from unittest.mock import create_autospec

    from app.rag.embeddings import Embedder

    embedder = create_autospec(Embedder, instance=True)
    embedder.name = name
    embedder.similarity_floor = floor
    embedder.similarity_strong = strong

    async def embed_documents(texts: list[str]) -> list[list[float]]:
        return [bag_of_words_vector(t) for t in texts]

    async def embed_query(text: str) -> list[float]:
        return bag_of_words_vector(text)

    embedder.embed_documents.side_effect = embed_documents
    embedder.embed_query.side_effect = embed_query
    embedder.relevance.side_effect = lambda similarity: Embedder.relevance(embedder, similarity)
    return embedder

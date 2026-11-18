"""Tests for the embedders. The real model and the Gemini API are replaced with mocks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.rag.embeddings import EmbeddingError, GeminiEmbedder, LocalEmbedder, make_embedder

pytestmark = pytest.mark.anyio


def test_relevance_uses_model_specific_thresholds() -> None:
    local = LocalEmbedder()  # floor 0.16, strong 0.60

    assert local.relevance(0.10) == 0.0  # below the floor: unrelated
    assert local.relevance(0.38) == pytest.approx(0.5)  # halfway between floor and strong
    assert local.relevance(0.95) == 1.0  # capped
    # The same raw score means very different things for Gemini (floor 0.50).
    gemini = GeminiEmbedder(SecretStr("k"), "gemini-embedding-001", 768, client=MagicMock())
    assert gemini.relevance(0.40) == 0.0


# --------------------------------------------------------------- local model
async def test_local_embedder_batches_and_returns_plain_floats() -> None:
    model = MagicMock(side_effect=lambda batch: [np.array([0.5, 0.25], dtype=np.float32) for _ in batch])
    embedder = LocalEmbedder()
    embedder.batch_size = 2

    with patch("chromadb.utils.embedding_functions.DefaultEmbeddingFunction", return_value=model) as factory:
        vectors = await embedder.embed_documents(["a", "b", "c"])
        await embedder.embed_query("d")

    assert vectors == [[0.5, 0.25]] * 3 and type(vectors[0][0]) is float  # numpy -> float
    assert model.call_count == 3  # batches ["a","b"], ["c"], then the query ["d"]
    factory.assert_called_once()  # the model is loaded only once


async def test_local_embedder_skips_empty_input_without_loading_model() -> None:
    with patch("chromadb.utils.embedding_functions.DefaultEmbeddingFunction") as factory:
        assert await LocalEmbedder().embed_documents([]) == []
    factory.assert_not_called()


async def test_local_embedder_wraps_failures() -> None:
    with patch("chromadb.utils.embedding_functions.DefaultEmbeddingFunction", side_effect=OSError("download failed")):
        with pytest.raises(EmbeddingError, match="download failed"):
            await LocalEmbedder().embed_query("x")


# --------------------------------------------------------------- Gemini API
def gemini_client_mock(vector=(0.1, 0.2)) -> MagicMock:
    async def embed_content(model, contents, config):
        return SimpleNamespace(embeddings=[SimpleNamespace(values=list(vector)) for _ in contents])

    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(side_effect=embed_content)
    return client


async def test_gemini_uses_task_types_and_dimensions() -> None:
    client = gemini_client_mock()
    embedder = GeminiEmbedder(SecretStr("k"), "gemini-embedding-001", 768, client=client)

    await embedder.embed_documents(["chunk"])
    await embedder.embed_query("question")

    doc_call, query_call = client.aio.models.embed_content.await_args_list
    assert doc_call.kwargs["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert query_call.kwargs["config"].task_type == "RETRIEVAL_QUERY"
    assert doc_call.kwargs["config"].output_dimensionality == 768
    assert embedder.name == "gemini-gemini-embedding-001-768"


async def test_gemini_batches_at_100() -> None:
    client = gemini_client_mock()
    embedder = GeminiEmbedder(SecretStr("k"), "m", 768, client=client)

    vectors = await embedder.embed_documents([f"t{i}" for i in range(250)])

    assert len(vectors) == 250
    assert [len(c.kwargs["contents"]) for c in client.aio.models.embed_content.await_args_list] == [100, 100, 50]


async def test_gemini_count_mismatch_is_an_error() -> None:
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(
        return_value=SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1])])  # 1 vector for 2 texts
    )

    with pytest.raises(EmbeddingError, match="different number"):
        await GeminiEmbedder(SecretStr("k"), "m", 768, client=client).embed_documents(["a", "b"])


async def test_gemini_api_errors_are_wrapped() -> None:
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("429 quota"))

    with pytest.raises(EmbeddingError, match="429 quota"):
        await GeminiEmbedder(SecretStr("k"), "m", 768, client=client).embed_query("q")


# --------------------------------------------------------------- selection
def test_make_embedder_selection() -> None:
    assert isinstance(make_embedder(Settings(_env_file=None)), LocalEmbedder)
    gemini = make_embedder(Settings(_env_file=None, embedding_provider="gemini", google_api_key="k"))
    assert isinstance(gemini, GeminiEmbedder)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        make_embedder(Settings(_env_file=None, embedding_provider="gemini"))

"""Semantic retrieval over the LoRA-practice corpus (US-5.3).

The hourly pipeline embeds repo READMEs and HF model cards into Qdrant
(`github_repos`, `huggingface_models`) with `all-MiniLM-L6-v2`. This module is
the read side: embed a natural-language query with the SAME model and search
those collections.

Heavy deps (`sentence-transformers`, `qdrant-client`) are imported lazily and the
embedder / Qdrant client are injectable, so importing this module and unit-testing
it need neither package nor a running Qdrant.

    from ml.rag.retriever import search_all
    hits = search_all("8-bit adamw for qlora on llama-3")
"""

from __future__ import annotations

import os

# friendly kind -> Qdrant collection (must match the embed_* DAG tasks)
COLLECTIONS = {"repos": "github_repos", "models": "huggingface_models"}
MODEL_NAME = "all-MiniLM-L6-v2"


def get_embedder(model_name: str = MODEL_NAME):
    """Load the sentence-transformer used by the embedding pipeline (lazy import)."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name)


def get_qdrant_client():
    """Connect to Qdrant from QDRANT_HOST / QDRANT_PORT (lazy import)."""
    from qdrant_client import QdrantClient
    return QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", "6333")),
    )


def _to_list(vector):
    return vector.tolist() if hasattr(vector, "tolist") else list(vector)


def embed_query(query: str, embedder):
    """Embed a single query string into a vector."""
    return _to_list(embedder.encode([query])[0])


def _format_hit(hit, kind: str) -> dict:
    return {
        "kind": "repo" if kind == "repos" else "model",
        "score": round(float(hit.score), 4),
        "object": hit.payload or {},
    }


def _search_vector(vector, kind: str, top_k: int, client) -> list[dict]:
    hits = client.search(
        collection_name=COLLECTIONS[kind], query_vector=vector, limit=top_k,
    )
    return [_format_hit(h, kind) for h in hits]


def search(query: str, kind: str = "repos", top_k: int = 5,
           client=None, embedder=None) -> list[dict]:
    """Semantic search one collection. `kind` is 'repos' or 'models'."""
    if kind not in COLLECTIONS:
        raise ValueError(f"unknown kind {kind!r}; options: {sorted(COLLECTIONS)}")
    client = client or get_qdrant_client()
    embedder = embedder or get_embedder()
    vector = embed_query(query, embedder)
    return _search_vector(vector, kind, top_k, client)


def search_all(query: str, top_k: int = 5,
               client=None, embedder=None) -> list[dict]:
    """Search both collections (query embedded once) and merge by score desc."""
    client = client or get_qdrant_client()
    embedder = embedder or get_embedder()
    vector = embed_query(query, embedder)
    hits: list[dict] = []
    for kind in COLLECTIONS:
        hits.extend(_search_vector(vector, kind, top_k, client))
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits

"""Retrieval-augmented answering over the LoRA-practice corpus (US-5.3).

`answer()` retrieves the most relevant repos/models (see retriever) and asks
Claude to answer the question grounded in them, citing the repo_name / model_id
it drew from. The Anthropic client is injectable (mocked in tests); the heavy
`anthropic` import is lazy.

    from ml.rag import answer
    result = answer("which optimizer do top llama-3 LoRAs use?")
    print(result["answer"]); print(result["sources"])
"""

from __future__ import annotations

import os

from .retriever import search_all

# Q&A quality matters here, so default to Opus (override with RAG_MODEL).
DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "You answer questions about LoRA / PEFT fine-tuning practices using ONLY the "
    "retrieved repositories and models provided as context. Cite the specific "
    "repo_name or model_id you draw from. If the context does not contain enough "
    "information to answer, say so plainly instead of guessing."
)


def _format_context(hits: list[dict]) -> str:
    if not hits:
        return "(no matching repositories or models were found)"
    lines = []
    for h in hits:
        o = h.get("object", {})
        if h.get("kind") == "repo":
            lines.append(
                f"- [repo] {o.get('repo_name')} "
                f"(language={o.get('primary_language')}, topics={o.get('topics')})"
            )
        else:
            lines.append(
                f"- [model] {o.get('model_id')} "
                f"(base_model={o.get('base_model')}, task={o.get('pipeline_tag')}, "
                f"downloads={o.get('downloads')}, likes={o.get('likes')})"
            )
    return "\n".join(lines)


def build_prompt(question: str, hits: list[dict]) -> list[dict]:
    """Build the user message: retrieved context followed by the question."""
    content = (
        "Context — top matching LoRA repositories and models from the corpus:\n"
        f"{_format_context(hits)}\n\n"
        f"Question: {question}"
    )
    return [{"role": "user", "content": content}]


def answer(question: str, top_k: int = 5, *,
           client=None, embedder=None, anthropic_client=None,
           model: str | None = None) -> dict:
    """Answer `question` grounded in retrieved corpus context.

    Returns {"answer": str, "sources": [...retrieved hits]}. `client`/`embedder`
    drive retrieval; `anthropic_client` is created lazily when omitted (needs
    ANTHROPIC_API_KEY).
    """
    hits = search_all(question, top_k=top_k, client=client, embedder=embedder)

    if anthropic_client is None:
        import anthropic
        anthropic_client = anthropic.Anthropic()
    model = model or os.getenv("RAG_MODEL", DEFAULT_MODEL)

    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=build_prompt(question, hits),
    )
    text = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    )
    return {"answer": text, "sources": hits}

"""
Lightweight JSON-backed retrieval helper used by the default toolkit.
"""

from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Sequence

_TOOLS_DIR = pathlib.Path(__file__).resolve().parent
_DATA_DIR = _TOOLS_DIR.parent / "data"
_RAG_CORPUS_PATH = _DATA_DIR / "sample_rag_corpus.json"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def _tokenize(text: str) -> list[str]:
    """
    Basic tokenizer used by the JSON RAG tool.

    Splits on any non-alphanumeric character, lowercases results, and removes
    simple stopwords.
    """
    if not text:
        return []
    return [
        token
        for token in re.findall(r"[0-9a-zA-Z]+", text.lower())
        if token not in _STOPWORDS
    ]


@lru_cache(maxsize=1)
def _load_rag_corpus() -> list[dict]:
    """
    Loads the sample RAG corpus from disk and augments entries with token sets.
    """
    if not _RAG_CORPUS_PATH.is_file():
        raise FileNotFoundError(
            f"Knowledge base not found at '{_RAG_CORPUS_PATH}'."
        )

    with _RAG_CORPUS_PATH.open(encoding="utf-8") as f:
        raw_docs = json.load(f)

    prepared: list[dict] = []
    for doc in raw_docs:
        combined = (
            f"{doc.get('title', '')} "
            f"{doc.get('summary', '')} "
            f"{doc.get('content', '')}"
        )
        tokens = _tokenize(combined)
        doc_copy = dict(doc)
        doc_copy["_token_set"] = set(tokens)
        prepared.append(doc_copy)

    return prepared


def _rank_documents(
    query_tokens: set[str], docs: Sequence[dict]
) -> list[tuple[float, dict]]:
    """
    Ranks documents by normalized token overlap with the query.
    """
    scored: list[tuple[float, dict]] = []
    if not query_tokens:
        return scored

    for doc in docs:
        token_set: set[str] = doc.get("_token_set", set())
        if not token_set:
            continue
        overlap = len(query_tokens & token_set)
        if overlap == 0 or (len(query_tokens) > 2 and overlap < 2):
            continue
        score = overlap / len(query_tokens)
        scored.append((score, doc))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def json_rag_answer(query: str, top_k: int = 2) -> str:
    """
    Answer a question by retrieving passages from a sample JSON knowledge base.

    Parameters
    ----------
    query : str
        Natural language query describing the user's information need.
    top_k : int, optional
        Maximum number of supporting documents to return. Defaults to 2.

    Returns
    -------
    str
        A synthesized answer that cites the top supporting documents.
    """
    question = query.strip()
    if not question:
        raise ValueError("Query must not be empty.")

    query_tokens = set(_tokenize(question))
    if not query_tokens:
        raise ValueError("Query must contain alphanumeric characters.")

    docs = _load_rag_corpus()
    ranked = _rank_documents(query_tokens, docs)
    if not ranked:
        return "No relevant documents were found in the knowledge base."

    top_k = max(1, min(int(top_k), len(ranked)))
    top_docs = ranked[:top_k]
    primary = top_docs[0][1]

    answer_lines = [
        primary.get("summary") or primary.get("content", ""),
    ]

    support_lines = ["", "Supporting references:"]
    for index, (score, doc) in enumerate(top_docs, start=1):
        title = doc.get("title", "Untitled document")
        source = doc.get("source", "unknown")
        support_lines.append(
            f"{index}. {title} (score={score:.2f}) — source: {source}"
        )

    return "\n".join(answer_lines + support_lines)


__all__ = ["json_rag_answer"]

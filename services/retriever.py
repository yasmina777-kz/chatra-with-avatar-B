import logging
import os
from typing import Optional

import httpx

from services.chunker import count_tokens
from services.embedder import embed_query_sync

logger = logging.getLogger(__name__)

CHAT_MODEL         = os.getenv("CHAT_MODEL", "gpt-4o-mini")
TOP_K              = int(os.getenv("TOP_K", "5"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "3000"))

_SYSTEM_PROMPT = (
    "You are a knowledgeable assistant. Answer the user's question "
    "using ONLY the context passages provided below. If the answer cannot be "
    "found in the context, say so clearly. Be concise and precise. "
    "Respond in the same language as the question."
)

def retrieve_and_answer(question: str, db, top_k: Optional[int] = None) -> dict:
    from sqlalchemy import text as sa_text

    k = top_k or TOP_K

    query_vec = embed_query_sync(question)
    vec_literal = f"[{','.join(str(v) for v in query_vec)}]"

    sql = sa_text(
        """
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.text,
            c.token_count,
            d.filename,
            c.embedding <-> CAST(:vec AS vector) AS distance
        FROM rag_chunks c
        JOIN rag_documents d ON d.id = c.document_id
        ORDER BY distance
        LIMIT :limit
        """
    )
    rows = db.execute(sql, {"vec": vec_literal, "limit": k * 2}).fetchall()

    if not rows:
        return {
            "answer": "No relevant content found in the knowledge base.",
            "sources": [],
            "context_tokens": 0,
        }

    selected: list[tuple] = []
    total_tokens = 0

    for row in rows:
        if total_tokens + row.token_count > MAX_CONTEXT_TOKENS:
            remaining = MAX_CONTEXT_TOKENS - total_tokens
            if remaining < 50:
                break
            trimmed = _trim_to_tokens(row.text, remaining)
            selected.append((row, trimmed))
            total_tokens += count_tokens(trimmed)
            break

        selected.append((row, row.text))
        total_tokens += row.token_count

        if len(selected) >= k:
            break

    logger.info(
        "RAG: %d chunks, %d tokens sent to LLM (cap %d)",
        len(selected), total_tokens, MAX_CONTEXT_TOKENS,
    )

    context_parts = [
        f"[{i}] (source: {row.filename})\n{chunk_text}"
        for i, (row, chunk_text) in enumerate(selected, 1)
    ]
    context = "\n\n---\n\n".join(context_parts)

    answer = _call_llm(question, context)

    sources = [
        {
            "document_id": row.document_id,
            "filename": row.filename,
            "chunk_index": row.chunk_index,
            "text_preview": chunk_text[:200],
        }
        for row, chunk_text in selected
    ]

    return {"answer": answer, "sources": sources, "context_tokens": total_tokens}

def _call_llm(question: str, context: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context:\n\n{context}\n\nQuestion: {question}",
            },
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if not resp.is_success:
        raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text[:300]}")

    return resp.json()["choices"][0]["message"]["content"].strip()

def _trim_to_tokens(text: str, max_tokens: int) -> str:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    ids = enc.encode(text)
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[:max_tokens])

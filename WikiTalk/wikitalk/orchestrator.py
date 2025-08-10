import re
from typing import Any, Dict, List, Optional, Tuple

from wikitalk.db import Database
from wikitalk.llm import LLMClient
from wikitalk.retrieval import Chunk, retrieve_top_k, split_into_chunks
from wikitalk.wiki import WikipediaClient


class ChatOrchestrator:
    def __init__(self, db: Database, wiki: WikipediaClient, llm: LLMClient):
        self.db = db
        self.wiki = wiki
        self.llm = llm

    # Ensure the article exists in cache (fetch/store if missing); return (title, url, chunks).
    def ensure_article_cached(self, title: str, language: str = 'en') -> Tuple[str, Optional[str], List[Chunk]]:
        cached = self.db.get_article(title, language)
        if cached:
            content = cached["content"]
            url = cached.get("url")
            return title, url, split_into_chunks(content)
        self.wiki.language = language
        data = self.wiki.fetch_page_extract(title)
        if not data:
            raise ValueError("Article not found.")
        content = data.get("extract", "")
        self.db.upsert_article(
            data.get("title", title),
            language,
            data.get("pageid"),
            data.get("revision_id"),
            data.get("url"),
            content,
        )
        return data.get("title", title), data.get("url"), split_into_chunks(content)

    # Build history, retrieve relevant chunks, call LLM (or fallback), and return (answer, citations).
    def answer_question(self, session_id: int, question: str) -> Tuple[str, Dict[str, Any]]:
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError("Invalid session.")
        # tuple: id, name, created_at, language, article_title, article_url
        _, _, _, language, article_title, _article_url = session
        if not article_title:
            raise ValueError("Select an article first.")

        title, url, chunks = self.ensure_article_cached(article_title, language)

        msgs = self.db.list_messages(session_id)
        history_pairs: List[Tuple[str, str]] = []
        pending_user: Optional[str] = None
        for _, _, role, text, _, _ in msgs:
            if role == "user":
                pending_user = text
            elif role == "assistant":
                if pending_user is None:
                    continue
                history_pairs.append((pending_user, text))
                pending_user = None
        if pending_user is not None:
            history_pairs.append((pending_user, ""))

        hist_texts = [u for u, a in history_pairs]
        top_chunks = retrieve_top_k(chunks, question, hist_texts, k=5)

        citations = {
            "article": {"title": title, "url": url},
            "sections": [ch.section for ch in top_chunks],
        }

        if self.llm.available():
            messages = self.llm.build_messages(question, history_pairs, top_chunks, title, url)
            answer = self.llm.chat(messages)
        else:
            snippet_lines = []
            for ch in top_chunks[:5]:
                sentences = re.split(r"(?<=[.!?])\s+", ch.text.strip())
                snippet = " ".join(sentences[:3])
                snippet_lines.append(f"[Section: {ch.section}] {snippet}")
            if snippet_lines:
                answer = (
                    "LLM is unavailable. Based on the article context, here are the most relevant snippets and where to look next:\n\n"
                    + "\n\n".join(snippet_lines)
                    + "\n\nSuggestions: consider reading the cited sections in full for more detail, or refine your question to target a specific part."
                )
            else:
                answer = (
                    "LLM is unavailable and I couldn't find relevant content in the provided article. "
                    "Try rephrasing the question or loading a different section/article."
                )

        return answer, citations

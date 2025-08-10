import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Chunk:
    section: str
    text: str
    start_line: int
    end_line: int


# Split article plain text into section and paragraph-sized chunks.
def split_into_chunks(plain_text: str) -> List[Chunk]:
    lines = plain_text.splitlines()
    chunks: List[Chunk] = []
    current_section = "Introduction"
    buf: List[str] = []
    sec_start = 0

    heading_re = re.compile(r"^\s*=+\s*(.*?)\s*=+\s*$")

    def flush(end_idx: int):
        nonlocal buf, current_section, sec_start
        if buf:
            text = "\n".join(buf).strip()
            if text:
                chunks.append(Chunk(current_section, text, sec_start, end_idx))
        buf = []

    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            flush(i - 1)
            current_section = m.group(1) or "Section"
            sec_start = i + 1
        else:
            buf.append(line)
    flush(len(lines) - 1)

    final_chunks: List[Chunk] = []
    for ch in chunks:
        paras = [p.strip() for p in ch.text.split("\n\n") if p.strip()]
        current = []
        current_len = 0
        for p in paras:
            if current_len + len(p) > 1200 and current:
                final_chunks.append(Chunk(ch.section, "\n\n".join(current), ch.start_line, ch.end_line))
                current = [p]
                current_len = len(p)
            else:
                current.append(p)
                current_len += len(p)
        if current:
            final_chunks.append(Chunk(ch.section, "\n\n".join(current), ch.start_line, ch.end_line))
    return final_chunks or chunks


# Lowercase/strip punctuation and split into tokens.
def simple_tokenize(s: str) -> List[str]:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return [t for t in s.split() if t]


# Score a chunk based on keyword overlap with the query and recent history.
def score_chunk(query: str, history: List[str], chunk: Chunk) -> float:
    q_tokens = simple_tokenize(query)
    hist_tokens = simple_tokenize(" ".join(history[-4:])) if history else []
    tokens = set(q_tokens + hist_tokens)
    if not tokens:
        return 0.0
    ch_tokens = simple_tokenize(chunk.text)
    if not ch_tokens:
        return 0.0
    freq: Dict[str, int] = {}
    for t in ch_tokens:
        freq[t] = freq.get(t, 0) + 1
    score = 0.0
    for t in tokens:
        score += freq.get(t, 0)
    score = score / (1.0 + len(ch_tokens) ** 0.5)
    sec_tokens = simple_tokenize(chunk.section)
    for t in tokens:
        if t in sec_tokens:
            score += 0.5
    return score


# Return the top-k highest-scoring chunks above zero.
def retrieve_top_k(chunks: List[Chunk], query: str, history: List[str], k: int = 5) -> List[Chunk]:
    scored = [(score_chunk(query, history, ch), ch) for ch in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ch for s, ch in scored[:k] if s > 0]

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple
import urllib.parse

from wikitalk import APP_NAME, DEFAULT_LANG


# Return the per-user application data directory and ensure it exists.
def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


# Current UTC time formatted as an ISO-8601 string (Z suffix).
def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# Parse a Wikipedia URL and return (language_code, decoded_title).
def parse_wikipedia_url(url: str) -> Tuple[str, str]:
    """Return (language, title) from a Wikipedia article URL like
    https://en.wikipedia.org/wiki/Alan_Turing or https://en.m.wikipedia.org/wiki/Alan_Turing
    """
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc or "wikipedia.org" not in parsed.netloc:
        raise ValueError(
            "Enter a valid Wikipedia article URL (e.g., https://en.wikipedia.org/wiki/Alan_Turing)."
        )
    parts = parsed.netloc.split(".")
    lang = None
    for part in parts:
        if part not in {"www", "m", "wikipedia", "org"}:
            lang = part
            break
    if not lang:
        lang = DEFAULT_LANG
    if not parsed.path.startswith("/wiki/"):
        raise ValueError("URL must be an article path like /wiki/Alan_Turing.")
    title_enc = parsed.path.split("/wiki/", 1)[1]
    if not title_enc:
        raise ValueError("Article title missing in URL.")
    title = urllib.parse.unquote(title_enc).replace("_", " ").strip()
    return lang, title

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from wikitalk.retrieval import Chunk


class LLMClient:
    # Initialize Gemini API key and model, normalizing model aliases.
    def __init__(self):
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        raw_model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash-latest")
        self.gemini_model = self._normalize_model(raw_model)

    # Quick check whether an API key is configured.
    def available(self) -> bool:
        return bool(self.gemini_api_key)

    # Send a message list to Gemini and return the text response.
    def chat(self, messages: List[Dict[str, str]]) -> str:
        if not self.available():
            raise RuntimeError("Gemini API key not configured.")
        return self._chat_gemini(messages)

    # Normalize common user-entered model names to API ids.
    @staticmethod
    def _normalize_model(name: str) -> str:
        n = (name or "").strip().lower()
        n = n.replace("models/", "")
        n = re.sub(r"\s+", "-", n)
        n = n.replace("_", "-")
        n = n.replace("-v1", "")
        aliases = {
            "gemini-1.5-flash-v1": "gemini-1.5-flash",
            "gemini-1.5-flash-001": "gemini-1.5-flash-001",
            "gemini-1.5-pro-v1": "gemini-1.5-pro",
        }
        return aliases.get(n, n)

    # Low-level REST call to Gemini generateContent with fallback system handling.
    def _chat_gemini(self, messages: List[Dict[str, str]]) -> str:
        system_texts = [m.get("content", "") for m in messages if m.get("role") == "system"]
        contents: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            parts = [{"text": m.get("content", "")}]
            if role == "assistant":
                contents.append({"role": "model", "parts": parts})
            else:
                contents.append({"role": "user", "parts": parts})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }
        if system_texts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_texts)}]}

        endpoint = f"https://generativelanguage.googleapis.com/v1/models/{self.gemini_model}:generateContent?key={urllib.parse.quote(self.gemini_api_key)}"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                fallback_body = {
                    "contents": (
                        ([{"role": "user", "parts": [{"text": "\n\n".join(system_texts)}]}] if system_texts else [])
                        + contents
                    ),
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 1024,
                    },
                }
                req2 = urllib.request.Request(
                    endpoint,
                    data=json.dumps(fallback_body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req2, timeout=60) as resp2:
                    data = json.loads(resp2.read().decode("utf-8"))
            else:
                raise

        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    # Build model-agnostic messages including system and context.
    def build_messages(
        self,
        question: str,
        history_pairs: List[Tuple[str, str]],
        chunks: List[Chunk],
        article_title: str,
        article_url: Optional[str],
    ) -> List[Dict[str, str]]:
        system = (
            "You are a helpful assistant answering strictly from the provided Wikipedia context. "
            "Be clear, well-structured, and as informative as possible without fabricating. "
            "Organize responses with a brief summary first, then key points or steps as bullet points, and a short details section when helpful. "
            "Define important terms and include dates, names, and figures when relevant. "
            "Cite sections using [Section: <name>] and include very short quotes where helpful. "
            "If the answer is not in the context, say so plainly and point to likely relevant sections."
        )
        ctx_parts: List[str] = []
        for i, ch in enumerate(chunks, 1):
            ctx_parts.append(f"[Chunk {i}] Section: {ch.section}\n{ch.text}")
        ctx = "\n\n".join(ctx_parts)
        src_line = f"Article: {article_title} - {article_url or ''}".strip()
        content_instruction = (
            "Use only these sources to answer thoroughly. Prefer concise structure over long prose.\n"
            f"{src_line}\n\n{ctx}"
        )

        msgs: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "system", "content": content_instruction},
        ]
        for u, a in history_pairs[-4:]:
            msgs.append({"role": "user", "content": u})
            if a:
                msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": question})
        return msgs

    # Validate the API key and resolve a working model name; return (ok, message).
    def sanity_check(self) -> Tuple[bool, str]:
        if not self.available():
            return False, "Gemini API key not set."
        key_q = urllib.parse.quote(self.gemini_api_key)
        candidates = [self.gemini_model]
        if self.gemini_model.endswith("-latest"):
            candidates.append(self.gemini_model.replace("-latest", ""))
        if not self.gemini_model.endswith("-001"):
            candidates.append(self.gemini_model + "-001")
        tried_errors: List[str] = []
        for m in candidates:
            url = f"https://generativelanguage.googleapis.com/v1/models/{m}?key={key_q}"
            req = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    name = data.get("name") or data.get("displayName") or m
                    self.gemini_model = m
                    return True, f"Gemini connected ({name})."
            except urllib.error.HTTPError as e:
                err = f"{m}: HTTP {e.code}"
                try:
                    details = e.read().decode("utf-8")
                    if details:
                        err += f" - {details[:120]}"
                except Exception:
                    pass
                tried_errors.append(err)
            except urllib.error.URLError as e:
                return False, f"Gemini check failed: {e.reason}"

        list_url = f"https://generativelanguage.googleapis.com/v1/models?key={key_q}"
        try:
            with urllib.request.urlopen(urllib.request.Request(list_url, method="GET"), timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                preferred = next((m for m in models if "gemini-1.5-flash" in m), None) or \
                            next((m for m in models if "gemini-1.5-pro" in m), None)
                hint = (
                    " e.g., 'gemini-1.5-flash' or 'gemini-1.5-pro'"
                    if not preferred
                    else f" try '{preferred.replace('models/','')}'"
                )
                return False, "Gemini model not found. Set GEMINI_MODEL to a valid id," + hint
        except Exception:
            pass
        return False, "Gemini model check failed: " + "; ".join(tried_errors[:3])

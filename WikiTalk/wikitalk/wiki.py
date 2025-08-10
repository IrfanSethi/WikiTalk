import json
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from wikitalk import APP_NAME


class WikipediaClient:
    # Create a client bound to a specific language wiki and a friendly User-Agent.
    def __init__(self, language: str = 'en', user_agent: Optional[str] = None):
        self.language = language
        self.user_agent = user_agent or f"{APP_NAME}/1.0 (https://www.wikipedia.org) Python/{sys.version_info.major}.{sys.version_info.minor}"

    # Perform a GET request against MediaWiki API and return parsed JSON.
    def _request(self, params: Dict[str, str]) -> Dict[str, Any]:
        base = f"https://{self.language}.wikipedia.org/w/api.php"
        params["format"] = "json"
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))

    # Search for article titles matching a free-text query.
    def search_titles(self, query: str, limit: int = 10) -> List[str]:
        if not query.strip():
            return []
        r = self._request({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(limit),
        })
        return [hit.get("title") for hit in r.get("query", {}).get("search", [])]

    # Fetch article plain-text extract and minimal metadata (pageid, revision, url).
    def fetch_page_extract(self, title: str) -> Optional[Dict[str, Any]]:
        r = self._request({
            "action": "query",
            "prop": "extracts|revisions|info",
            "explaintext": "1",
            "exsectionformat": "plain",
            "rvprop": "ids|timestamp",
            "inprop": "url",
            "titles": title,
        })
        pages = r.get("query", {}).get("pages", {})
        if not pages:
            return None
        page = next(iter(pages.values()))
        if int(page.get("missing", 0)) == 1 or page.get("extract") is None:
            return None
        return {
            "pageid": page.get("pageid"),
            "title": page.get("title", title),
            "revision_id": (page.get("revisions") or [{}])[0].get("revid"),
            "url": page.get("fullurl"),
            "extract": page.get("extract", ""),
        }

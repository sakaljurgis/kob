import re
from urllib.parse import urlparse

import requests

JINA_BASE = "https://r.jina.ai/"


def fetch(url: str, api_key: str | None = None, timeout: int = 60) -> tuple[str, str]:
    """Fetch an article via Jina Reader. Returns (title, markdown_body)."""
    headers = {"Accept": "text/markdown"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(JINA_BASE + url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = resp.text
    title = _extract_title(body) or _hostname_fallback(url)
    return title, body


def _extract_title(body: str) -> str | None:
    m = re.match(r"^Title:\s*(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _hostname_fallback(url: str) -> str:
    return urlparse(url).hostname or "Untitled"

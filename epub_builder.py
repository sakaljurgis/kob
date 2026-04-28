import hashlib
import io
import os
import re
import sys

import lxml.etree
import lxml.html
import markdown as md
import requests
from ebooklib import epub

EPUB_CSS = """
body { font-family: serif; line-height: 1.6; }
h1, h2, h3 { font-family: sans-serif; }
img { max-width: 100%; height: auto; }
pre { white-space: pre-wrap; word-break: break-word; }
"""

IMG_TAG = re.compile(r"<img\b([^>]*?)/?>", re.IGNORECASE)
SRC_ATTR = re.compile(r'\bsrc="([^"]+)"', re.IGNORECASE)
IMAGE_TIMEOUT = 20
IMAGE_UA = "Mozilla/5.0 (compatible; kob/1.0; +https://github.com/)"

EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

SPLIT_THRESHOLD = int(os.environ.get("EPUB_SPLIT_THRESHOLD_BYTES", "50000"))
SPLIT_TARGET = int(os.environ.get("EPUB_SPLIT_TARGET_BYTES", "25000"))

HEADING_RE = re.compile(r"^(##|###)\s+(.+)$")


def build(title: str, source_md: str, identifier: str) -> bytes:
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language("en")

    body_md = _strip_jina_header(source_md)
    chunks = _plan_chunks(body_md, title)

    style = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=EPUB_CSS,
    )
    book.add_item(style)

    embedder = _ImageEmbedder(book)
    chapters: list[epub.EpubHtml] = []
    for i, chunk in enumerate(chunks, 1):
        html = md.markdown(chunk["body"], extensions=["extra", "sane_lists"])
        html = embedder.embed(html)
        if i == 1:
            content = f"<h1>{_escape(title)}</h1>\n{html}"
        else:
            content = html
        content = _to_xhtml(content)
        file_name = "article.xhtml" if len(chunks) == 1 else f"article_{i:02d}.xhtml"
        ch = epub.EpubHtml(title=chunk["title"], file_name=file_name, lang="en")
        ch.content = content
        ch.add_item(style)
        book.add_item(ch)
        chapters.append(ch)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]

    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def _plan_chunks(body_md: str, article_title: str) -> list[dict]:
    """Decide how to split. Returns list of {title, body} chunks.

    - Below SPLIT_THRESHOLD: one chunk titled with the article title.
    - Otherwise prefer cutting at H2/H3 boundaries; each chunk titled with its
      first heading. Used only if every resulting chunk fits under threshold.
    - Fallback: paragraph-boundary "Part N" splits.
    """
    if len(body_md) <= SPLIT_THRESHOLD:
        return [{"title": article_title, "body": body_md}]

    blocks = _tokenize_md_blocks(body_md)
    heading_chunks = _split_at_headings(blocks, SPLIT_TARGET, article_title)
    if heading_chunks and all(
        len(c["body"]) <= SPLIT_THRESHOLD for c in heading_chunks
    ):
        return heading_chunks
    return _split_into_parts(blocks, SPLIT_TARGET)


def _tokenize_md_blocks(body: str) -> list[str]:
    """Split markdown into top-level blocks (blank-line separated, fence-aware)."""
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence = True
            fence_marker = stripped[:3]
            cur.append(line)
            continue
        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            cur.append(line)
            continue
        if stripped == "":
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _block_heading(block: str) -> str | None:
    """If the block starts with an H2/H3 heading, return its plain text."""
    if not block.strip():
        return None
    first_line = block.lstrip().splitlines()[0]
    m = HEADING_RE.match(first_line)
    if m:
        return _strip_inline_md(m.group(2))
    return None


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    return text.strip()


def _split_at_headings(
    blocks: list[str], target: int, article_title: str
) -> list[dict]:
    """Walk blocks, cutting before an H2/H3 once accumulated size exceeds target.

    Returns [] if there are no H2/H3 headings at all.
    """
    if not any(_block_heading(b) for b in blocks):
        return []

    chunks: list[dict] = []
    cur_blocks: list[str] = []
    cur_size = 0
    cur_title: str | None = None

    for b in blocks:
        h = _block_heading(b)
        if cur_size >= target and h and cur_blocks:
            chunks.append({
                "title": cur_title or article_title,
                "body": "\n\n".join(cur_blocks),
            })
            cur_blocks = []
            cur_size = 0
            cur_title = None
        if cur_title is None and h:
            cur_title = h
        cur_blocks.append(b)
        cur_size += len(b) + 2

    if cur_blocks:
        chunks.append({
            "title": cur_title or article_title,
            "body": "\n\n".join(cur_blocks),
        })
    return chunks


def _split_into_parts(blocks: list[str], target: int) -> list[dict]:
    parts: list[list[str]] = []
    cur: list[str] = []
    cur_size = 0
    for b in blocks:
        cur.append(b)
        cur_size += len(b) + 2
        if cur_size >= target:
            parts.append(cur)
            cur = []
            cur_size = 0
    if cur:
        parts.append(cur)
    if not parts:
        parts = [[""]]
    return [
        {"title": f"Part {i}", "body": "\n\n".join(p)}
        for i, p in enumerate(parts, 1)
    ]


class _ImageEmbedder:
    def __init__(self, book: epub.EpubBook):
        self.book = book
        self.cache: dict[str, str | None] = {}

    def embed(self, html: str) -> str:
        def replace(match: re.Match[str]) -> str:
            attrs = match.group(1)
            src_match = SRC_ATTR.search(attrs)
            if not src_match:
                return match.group(0)
            url = src_match.group(1)
            if not url.startswith(("http://", "https://")):
                return match.group(0)
            if url not in self.cache:
                self.cache[url] = _download_and_register(url, self.book)
            local = self.cache[url]
            if local is None:
                return match.group(0)
            new_attrs = attrs[: src_match.start(1)] + local + attrs[src_match.end(1):]
            return f"<img{new_attrs}/>"
        return IMG_TAG.sub(replace, html)


def _download_and_register(url: str, book: epub.EpubBook) -> str | None:
    try:
        resp = requests.get(
            url,
            timeout=IMAGE_TIMEOUT,
            headers={"User-Agent": IMAGE_UA},
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[kob] image fetch failed: {url}: {e}", file=sys.stderr)
        return None

    mime = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        print(f"[kob] not an image ({mime}): {url}", file=sys.stderr)
        return None
    ext = EXT_BY_MIME.get(mime, ".bin")

    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    file_name = f"images/img_{h}{ext}"
    item = epub.EpubItem(
        uid=f"img_{h}",
        file_name=file_name,
        media_type=mime,
        content=resp.content,
    )
    book.add_item(item)
    return file_name


def _to_xhtml(html_fragment: str) -> str:
    """Parse an HTML fragment forgivingly and re-serialize as valid XHTML.

    Fixes void-element self-closing, bare ampersands, unclosed tags, and other
    quirks that strict XHTML parsers (libxml2) reject.
    """
    if not html_fragment.strip():
        return html_fragment
    wrapper = lxml.html.fragment_fromstring(html_fragment, create_parent="div")
    serialized = lxml.etree.tostring(
        wrapper,
        method="xml",
        encoding="unicode",
        with_tail=False,
    )
    if serialized in ("<div/>", "<div></div>"):
        return ""
    if serialized.startswith("<div>") and serialized.endswith("</div>"):
        return serialized[len("<div>"):-len("</div>")]
    return serialized


def _strip_jina_header(body: str) -> str:
    marker = "Markdown Content:"
    idx = body.find(marker)
    if idx >= 0:
        return body[idx + len(marker):].lstrip("\n")
    return body


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

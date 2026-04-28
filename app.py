import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

import epub_builder
import fetcher
from storage import Storage

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
ARTICLES_PER_PAGE = int(os.environ.get("ARTICLES_PER_PAGE", "8"))
JINA_API_KEY = os.environ.get("JINA_API_KEY") or None

app = Flask(__name__)
storage = Storage(DATA_DIR)


@app.route("/")
def index():
    page = _parse_page(request.args.get("page"))
    articles = storage.list_articles()
    total_pages = max(1, (len(articles) + ARTICLES_PER_PAGE - 1) // ARTICLES_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * ARTICLES_PER_PAGE
    page_articles = articles[start:start + ARTICLES_PER_PAGE]
    return render_template(
        "index.html",
        articles=page_articles,
        page=page,
        total_pages=total_pages,
    )


@app.route("/add", methods=["POST"])
def add():
    url = (request.form.get("url") or "").strip()
    if not url:
        return render_template("error.html", message="No URL provided."), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        return render_template("error.html", message="URL must start with http:// or https://"), 400
    try:
        title, source_md = fetcher.fetch(url, api_key=JINA_API_KEY)
    except Exception as e:
        return render_template("error.html", message=f"Failed to fetch: {e}"), 502
    article_id = _make_id(title)
    try:
        epub_bytes = epub_builder.build(
            title=title,
            source_md=source_md,
            identifier=article_id,
        )
    except Exception as e:
        return render_template("error.html", message=f"Failed to build EPUB: {e}"), 500
    storage.add_article(article_id, title, url, source_md, epub_bytes)
    return redirect(url_for("index"))


@app.route("/download/<article_id>")
def download(article_id):
    article = storage.get_article(article_id)
    if not article:
        abort(404)
    path = storage.epub_path(article_id)
    if not path.exists():
        abort(404)
    safe_name = _slugify(article["title"]) + ".epub"
    return send_file(
        path,
        as_attachment=True,
        download_name=safe_name,
        mimetype="application/epub+zip",
    )


@app.route("/delete/<article_id>", methods=["GET"])
def delete_confirm(article_id):
    article = storage.get_article(article_id)
    if not article:
        abort(404)
    page = _parse_page(request.args.get("page"))
    return render_template("confirm_delete.html", article=article, page=page)


@app.route("/delete/<article_id>", methods=["POST"])
def delete_do(article_id):
    page = _parse_page(request.form.get("page"))
    storage.delete_article(article_id)
    articles = storage.list_articles()
    total_pages = max(1, (len(articles) + ARTICLES_PER_PAGE - 1) // ARTICLES_PER_PAGE)
    page = min(page, total_pages)
    return redirect(url_for("index", page=page))


def _parse_page(raw: str | None) -> int:
    try:
        return max(1, int(raw or "1"))
    except ValueError:
        return 1


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "article"


def _make_id(title: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{_slugify(title)}"

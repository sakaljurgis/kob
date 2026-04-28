# kob — article-to-EPUB for e-reader

A tiny self-hosted web app: paste an article URL → it's fetched via Jina Reader, packaged as EPUB, and listed for download. Designed to be browsed from an e-reader: HTML-only, no JS, big fonts, full-width, paginated (no scrolling).

## Decisions (locked)

- **Stack**: Python + Flask, `ebooklib` for EPUB, `requests` for HTTP, `markdown` for md→html.
- **Hosting**: home server, Docker. README explains env vars and volumes.
- **Fetcher**: `https://r.jina.ai/<url>`. Optional `JINA_API_KEY` env var, sent as `Authorization: Bearer ...` if set.
- **Articles per page**: configurable via `ARTICLES_PER_PAGE`, default 8.
- **Delete**: button per article → confirmation page (no JS) → POST to actually delete.
- **Storage**: filesystem + `index.json`. Keep source URL and original markdown alongside the EPUB.
- **Title**: taken from Jina response, used as EPUB title and slug for filename.
- **No auth**: single user on home network. Document in README that this should not be exposed publicly without putting a reverse proxy + auth in front.

## Storage layout

Mount one volume at `/data`:

```
/data/
  index.json                 # ordered list, newest first
  articles/
    <id>/                    # id = timestamp + slug, e.g. 20260428-153012-how-to-x
      article.epub
      source.md              # original markdown from Jina
      meta.json              # { id, url, title, fetched_at }
```

`index.json` is the source of truth for ordering and listing. Format:

```json
{
  "articles": [
    { "id": "20260428-153012-how-to-x", "title": "How to X", "url": "https://...", "fetched_at": "2026-04-28T15:30:12Z" }
  ]
}
```

On delete: remove from `index.json` first, then `rm -rf` the article folder. (Order matters: if rm fails, the index is still consistent — orphan folders are harmless and can be GC'd later if ever needed.)

## Routes

| Method | Path                       | Purpose                                            |
|--------|----------------------------|----------------------------------------------------|
| GET    | `/`                        | Main page: URL input + paginated list (`?page=N`). |
| POST   | `/add`                     | Fetch URL → build EPUB → save → redirect to `/`.   |
| GET    | `/download/<id>`           | Stream the `.epub` file.                           |
| GET    | `/delete/<id>?page=N`      | Confirmation page ("Delete '<title>'? Yes / No"). |
| POST   | `/delete/<id>` (form: `page=N`) | Actually delete; redirect to `/?page=N`.      |

Pagination uses big "← Prev" / "Next →" buttons at the bottom. No page-number list (keeps things simple and reader-friendly).

**Page preservation across delete**: each "Delete" link on `/` carries the current `?page=N`. The confirmation page passes it through as a hidden form field; the POST handler redirects back to `/?page=N` so you stay where you were. Edge case: if the page you were on no longer exists after the delete (e.g. you deleted the only article on the last page), clamp `page` to the new max page before redirecting.

## Page layouts (HTML only)

All pages share the same minimal CSS:

- `body { max-width: 100%; font-size: 1.6rem; line-height: 1.5; padding: 1rem; }`
- Buttons / links styled as large blocks (~3rem tall, full-width on small screens).
- No images, no JS, no external assets.
- `<meta name="viewport" content="width=device-width, initial-scale=1">`.

**`/` (main)** — fits one screen, no scrolling:
1. URL input + "Add" button (POST to `/add`).
2. List of up to N=8 article rows. Each row: title + "Download" link + "Delete" link.
3. Prev / Next pagination buttons (disabled state when at edge).

**`/delete/<id>`** — confirmation:
- "Delete '<title>'?"
- Two big buttons: "Yes, delete" (POST) and "Cancel" (link back to `/`).

**`/add` result**: on success, redirect to `/`. On error, render a simple page with the error message and a "Back" link.

## EPUB generation

1. POST `/add` receives URL.
2. GET `https://r.jina.ai/<url>` (with `Authorization` header if `JINA_API_KEY` set). Jina returns markdown with a leading `Title: ...` block — parse it for the title; fall back to URL host if missing.
3. Save markdown to `source.md`.
4. Convert markdown → HTML with the `markdown` library.
5. Build EPUB with `ebooklib`:
   - Single chapter, the converted HTML.
   - Title = parsed title, language = `en`, identifier = id.
   - Minimal embedded CSS for big-font reading (independent of the web UI CSS).
6. Write `article.epub`, `meta.json`. Prepend entry to `index.json`.

If any step fails, clean up partial files; do not modify `index.json`.

## Configuration (env vars)

| Var                  | Default     | Purpose                                  |
|----------------------|-------------|------------------------------------------|
| `DATA_DIR`           | `/data`     | Where articles + index.json live.        |
| `ARTICLES_PER_PAGE`  | `8`         | Pagination size on `/`.                  |
| `JINA_API_KEY`       | *(unset)*   | Optional; sent as bearer token to Jina.  |
| `PORT`               | `8080`      | HTTP port inside the container.          |

## Project layout

```
kob/
  app.py              # Flask app: routes, glue
  storage.py          # index.json + folder ops (add, list, delete)
  fetcher.py          # Jina call + title parsing
  epub_builder.py     # markdown → EPUB
  templates/
    base.html
    index.html
    confirm_delete.html
    error.html
  static/
    style.css
  requirements.txt
  Dockerfile
  README.md
  plan.md             # this file
```

## Dockerfile

- Base: `python:3.12-slim`.
- Install deps from `requirements.txt`.
- Copy app, expose `$PORT`, run with `gunicorn` (single worker — single user, no contention).
- Declare `VOLUME /data`.

## README outline

1. What it does (1 paragraph).
2. Quick start: `docker build`, `docker run` example with `-v ./data:/data -p 8080:8080 -e JINA_API_KEY=... -e ARTICLES_PER_PAGE=8`.
3. Env vars table (same as above).
4. Volumes table: `/data` → article storage (persist this).
5. Security note: no auth — put behind a reverse proxy / Tailscale if not on a trusted LAN.
6. Where to point your e-reader's browser.

## Build order

1. Skeleton: Flask app, `requirements.txt`, render an empty `/` template.
2. Storage module: read/write `index.json`, list/add/delete article folders.
3. Fetcher: Jina call + title extraction; manual test with one URL.
4. EPUB builder: markdown → epub; verify the file opens on the e-reader.
5. Wire `/add` end-to-end.
6. Pagination + listing on `/`.
7. Delete flow with confirmation page.
8. CSS pass for big-font / full-width / no-scroll layout.
9. Dockerfile + README.
10. Smoke test in container with a real volume mount.

## Open / deferred

- Auto-prune of old articles: not in v1; user can delete manually.
- Cover images / multi-chapter EPUBs: not in v1.
- Search: explicitly out of scope.
- Auth: out of scope; documented in README.

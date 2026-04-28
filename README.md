# kob

Self-hosted article-to-EPUB service. Paste a URL, get an EPUB on your e-reader.

Designed to be browsed *from* the e-reader: HTML-only, no JavaScript, big fonts, full-width, paginated (no scrolling).

## How it works

1. You browse to the site from your e-reader.
2. Paste an article URL into the input.
3. The server fetches it via [Jina Reader](https://r.jina.ai/), converts to EPUB, and saves it.
4. The article appears in the list — tap to download.

Images are downloaded and embedded into the EPUB at build time, so the file is fully self-contained — no internet needed when reading. If a particular image fails to fetch, it's skipped and the URL is left in the `src` (so it works online but shows broken offline); a message is written to stderr.

Long articles are split into multiple xhtml files inside the EPUB so weak readers paginate faster (each "chapter" is loaded and laid out independently). Splitting prefers H2/H3 boundaries when present (TOC entries use the heading text) and falls back to "Part 1, Part 2, …" splits at paragraph boundaries when the article has no headings or its sections are larger than the threshold. Tune via `EPUB_SPLIT_THRESHOLD_BYTES` / `EPUB_SPLIT_TARGET_BYTES` (see below).

## Quick start (Docker)

```bash
docker build -t kob .

docker run -d \
  --name kob \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e ARTICLES_PER_PAGE=8 \
  kob
```

Then point your e-reader's browser at `http://<server-ip>:8080`.

## Environment variables

| Var                 | Default   | Purpose                                                |
|---------------------|-----------|--------------------------------------------------------|
| `DATA_DIR`          | `/data`   | Where articles + `index.json` are stored.              |
| `ARTICLES_PER_PAGE` | `8`       | How many articles per page on the listing.            |
| `JINA_API_KEY`      | *(unset)* | Optional. Sent as `Authorization: Bearer ...` to Jina. |
| `PORT`              | `8080`    | HTTP port inside the container.                        |
| `EPUB_SPLIT_THRESHOLD_BYTES` | `50000` | If an article's source markdown is larger than this, it gets split into multiple xhtml files inside the EPUB. Helps weak readers paginate faster. |
| `EPUB_SPLIT_TARGET_BYTES`    | `25000` | Target size for each chunk when splitting. |

## Volumes

| Path     | Purpose                                                       |
|----------|---------------------------------------------------------------|
| `/data`  | Article storage. Persist this — losing it loses your library. |

Layout inside the volume:

```
/data/
  index.json
  articles/
    <id>/
      article.epub
      source.md
      meta.json
```

## Security note

There is **no authentication**. Designed for a trusted home network. If you expose this beyond your LAN, put it behind a reverse proxy with auth (e.g. Caddy + basic auth, or Tailscale).

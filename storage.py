import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.articles_dir = self.data_dir / "articles"
        self.index_file = self.data_dir / "index.json"
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self._write_index({"articles": []})

    def _read_index(self) -> dict:
        with open(self.index_file) as f:
            return json.load(f)

    def _write_index(self, data: dict) -> None:
        tmp = self.index_file.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.index_file)

    def list_articles(self) -> list[dict]:
        return self._read_index()["articles"]

    def get_article(self, article_id: str) -> Optional[dict]:
        for a in self.list_articles():
            if a["id"] == article_id:
                return a
        return None

    def add_article(
        self,
        article_id: str,
        title: str,
        url: str,
        markdown: str,
        epub_bytes: bytes,
    ) -> None:
        folder = self.articles_dir / article_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "source.md").write_text(markdown, encoding="utf-8")
        (folder / "article.epub").write_bytes(epub_bytes)
        meta = {
            "id": article_id,
            "url": url,
            "title": title,
            "fetched_at": _now(),
        }
        (folder / "meta.json").write_text(json.dumps(meta, indent=2))

        index = self._read_index()
        index["articles"].insert(0, meta)
        self._write_index(index)

    def delete_article(self, article_id: str) -> bool:
        index = self._read_index()
        before = len(index["articles"])
        index["articles"] = [a for a in index["articles"] if a["id"] != article_id]
        if len(index["articles"]) == before:
            return False
        self._write_index(index)
        folder = self.articles_dir / article_id
        if folder.exists():
            shutil.rmtree(folder)
        return True

    def epub_path(self, article_id: str) -> Path:
        return self.articles_dir / article_id / "article.epub"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path("data")
PROGRESS_FILE = DATA_DIR / "progress.json"


@dataclass(frozen=True, slots=True)
class DownloadKey:
    code: str
    year: str
    series: str

    def __str__(self) -> str:
        return f"{self.code}_{self.year}_{self.series}"


class Progress:
    """JSONファイルでダウンロード済み銘柄を管理する。"""

    def __init__(self, path: Path = PROGRESS_FILE, *, autosave_every: int = 100) -> None:
        self._path = path
        self._autosave_every = autosave_every
        self._completed: set[str] = self._load()
        self._dirty_count = 0

    def _load(self) -> set[str]:
        if not self._path.exists():
            return set()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return set(raw.get("completed", []))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"completed": sorted(self._completed)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._dirty_count = 0

    def is_downloaded(self, key: DownloadKey) -> bool:
        return str(key) in self._completed

    def mark_downloaded(self, key: DownloadKey) -> None:
        item = str(key)
        if item in self._completed:
            return
        self._completed.add(item)
        self._dirty_count += 1
        if self._dirty_count >= self._autosave_every:
            self._save()

    def flush(self) -> None:
        if self._dirty_count:
            self._save()

    def pending_pages(
        self, page_ids: list[str], year: str, series: str
    ) -> list[str]:
        """未ダウンロードのページID一覧を返す。"""
        return [
            page_id for page_id in page_ids
            if not self.is_downloaded(DownloadKey(page_id, year, series))
        ]

    def pending_codes(
        self, codes: list[str], year: str, series: str
    ) -> list[str]:
        """後方互換用。"""
        return self.pending_pages(codes, year, series)

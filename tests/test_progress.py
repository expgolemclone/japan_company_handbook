from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrape.progress import DownloadKey, Progress


@pytest.fixture
def progress_file(tmp_path: Path) -> Path:
    return tmp_path / "progress.json"


class TestDownloadKey:
    def test_str_representation(self) -> None:
        key = DownloadKey("332A", "2026", "2")
        assert str(key) == "332A_2026_2"

    def test_equality(self) -> None:
        assert DownloadKey("332A", "2026", "2") == DownloadKey("332A", "2026", "2")

    def test_hash_in_set(self) -> None:
        s = {DownloadKey("332A", "2026", "2"), DownloadKey("332A", "2026", "2")}
        assert len(s) == 1


class TestProgress:
    def test_empty_when_no_file(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        key = DownloadKey("332A", "2026", "2")
        assert not progress.is_downloaded(key)

    def test_mark_and_check(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        key = DownloadKey("332A", "2026", "2")
        progress.mark_downloaded(key)
        progress.flush()
        assert progress.is_downloaded(key)

    def test_persists_across_instances(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        progress.mark_downloaded(DownloadKey("332A", "2026", "2"))
        progress.flush()

        progress2 = Progress(progress_file)
        assert progress2.is_downloaded(DownloadKey("332A", "2026", "2"))

    def test_pending_codes_filters_completed(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        progress.mark_downloaded(DownloadKey("332A", "2026", "2"))
        progress.flush()

        codes = ["332A", "7203", "6501"]
        pending = progress.pending_codes(codes, "2026", "2")
        assert pending == ["7203", "6501"]

    def test_pending_codes_all_pending(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        codes = ["332A", "7203"]
        pending = progress.pending_codes(codes, "2026", "2")
        assert pending == codes

    def test_file_format(self, progress_file: Path) -> None:
        progress = Progress(progress_file)
        progress.mark_downloaded(DownloadKey("7203", "2026", "2"))
        progress.mark_downloaded(DownloadKey("332A", "2026", "2"))
        progress.flush()

        raw = json.loads(progress_file.read_text(encoding="utf-8"))
        assert raw == {"completed": ["332A_2026_2", "7203_2026_2"]}

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        progress_file = tmp_path / "nested" / "dir" / "progress.json"
        progress = Progress(progress_file)
        progress.mark_downloaded(DownloadKey("332A", "2026", "2"))
        progress.flush()
        assert progress_file.exists()

    def test_autosaves_when_threshold_is_reached(self, progress_file: Path) -> None:
        progress = Progress(progress_file, autosave_every=2)
        progress.mark_downloaded(DownloadKey("332A", "2026", "2"))
        assert not progress_file.exists()
        progress.mark_downloaded(DownloadKey("7203", "2026", "2"))
        assert progress_file.exists()

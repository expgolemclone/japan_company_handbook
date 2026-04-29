from __future__ import annotations

from pathlib import Path

from scrape.magazine.progress import BatchProgress, IssueProgress
from scrape.magazine.types import MagazineIssueKey


class TestIssueProgress:
    def test_register_mark_and_finalize(self, tmp_path: Path) -> None:
        progress = IssueProgress(tmp_path / "progress.json")

        progress.register_expected_pages(["0000page", "0001page"])
        progress.mark_downloaded("0000page", "0000page.png")

        assert progress.missing_pages() == ["0001page"]
        assert not progress.completed

        progress.mark_downloaded("0001page", "0001page.pdf")
        assert progress.finalize() is True
        assert progress.completed

    def test_persists_failed_state(self, tmp_path: Path) -> None:
        path = tmp_path / "progress.json"
        progress = IssueProgress(path)
        progress.register_expected_pages(["0000page"])
        progress.mark_failed("0000page", "auth")

        loaded = IssueProgress(path)
        assert loaded.page_state("0000page") == {"status": "failed", "reason": "auth"}


class TestBatchProgress:
    def test_tracks_issue_status(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("1936", "1")
        progress = BatchProgress(tmp_path / "batch_progress.json")

        assert progress.status(issue) == "pending"
        progress.mark_running(issue)
        assert progress.status(issue) == "running"
        progress.mark_succeeded(issue)
        assert progress.is_succeeded(issue)

    def test_stores_error(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        progress = BatchProgress(tmp_path / "batch_progress.json")

        progress.mark_failed(issue, "boom")

        loaded = BatchProgress(tmp_path / "batch_progress.json")
        assert loaded.status(issue) == "failed"
        assert loaded.error(issue) == "boom"

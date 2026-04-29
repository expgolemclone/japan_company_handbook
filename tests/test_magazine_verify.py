from __future__ import annotations

import json
from pathlib import Path

import httpx

from scrape.magazine.client import save_expected_issues
from scrape.magazine.downloader import download_issue_artifacts
from scrape.magazine.progress import BatchProgress
from scrape.magazine.types import MagazineIssueKey
from scrape.magazine.verify import verify_all_issues, verify_issue_directory

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _make_page_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return httpx.Response(
                200,
                content=b"%PDF-1.4 page pdf",
                headers={"content-type": "application/pdf"},
            )
        if request.url.path.endswith(".jpg"):
            return httpx.Response(
                200,
                content=b"jpeg",
                headers={"content-type": "image/jpeg"},
            )
        return httpx.Response(
            200,
            content=b"png",
            headers={"content-type": "image/png"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestVerifyIssueDirectory:
    def test_reports_ok_for_complete_issue(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        download_issue_artifacts(
            _make_page_client(),
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )

        report = verify_issue_directory(issue, tmp_path)

        assert report["ok"] is True
        assert report["missing_pages"] == []

    def test_reports_missing_page_file(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        download_issue_artifacts(
            _make_page_client(),
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )
        (tmp_path / "2026_2" / "pages" / "0013page.png").unlink()

        report = verify_issue_directory(issue, tmp_path)

        assert report["ok"] is False
        assert "0013page" in report["missing_pages"]


class TestVerifyAllIssues:
    def test_verifies_all_expected_issues(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        download_issue_artifacts(
            _make_page_client(),
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )
        save_expected_issues([issue], tmp_path / "issues.expected.json")
        batch_progress = BatchProgress(tmp_path / "batch_progress.json")
        batch_progress.mark_succeeded(issue)

        report = verify_all_issues(
            tmp_path,
            expected_issues_path=tmp_path / "issues.expected.json",
            batch_progress_path=tmp_path / "batch_progress.json",
        )

        assert report["verified_complete"] is True
        assert report["expected_issue_count"] == 1

    def test_detects_missing_issue_directory(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("1936", "1")
        save_expected_issues([issue], tmp_path / "issues.expected.json")

        report = verify_all_issues(
            tmp_path,
            expected_issues_path=tmp_path / "issues.expected.json",
            batch_progress_path=tmp_path / "batch_progress.json",
        )

        assert report["verified_complete"] is False
        assert report["missing_issues"] == ["1936_1"]

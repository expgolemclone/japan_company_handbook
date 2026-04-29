from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scrape.magazine.downloader import download_issue_artifacts
from scrape.magazine.progress import IssueProgress
from scrape.magazine.types import MagazineIssueKey

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _make_page_client(*, html_path: str | None = None, calls: list[str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))

        if html_path is not None and request.url.path.endswith(html_path):
            return httpx.Response(
                200,
                content=b"<html>expired</html>",
                headers={"content-type": "text/html"},
            )
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


class TestDownloadIssueArtifacts:
    def test_saves_manifests_and_pages(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        client = _make_page_client()

        manifest = download_issue_artifacts(
            client,
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )

        issue_dir = tmp_path / "2026_2"
        pages_dir = issue_dir / "pages"
        progress = IssueProgress(issue_dir / "progress.json")

        assert manifest["physical_page_count"] == 4
        assert (issue_dir / "manifest.raw.json").exists()
        assert (issue_dir / "manifest.normalized.json").exists()
        assert progress.completed
        assert sorted(path.name for path in pages_dir.iterdir()) == [
            "0000page.png",
            "0013page.png",
            "0100page.pdf",
            "0101page.jpg",
        ]

    def test_marks_failed_page_on_html_response(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        client = _make_page_client(html_path="0013page.png")

        with pytest.raises(ValueError, match="ページ本体ではない"):
            download_issue_artifacts(
                client,
                issue,
                tmp_path,
                raw_issue=_load_json("2026_2.raw.json"),
            )

        progress = IssueProgress(tmp_path / "2026_2" / "progress.json")
        assert progress.page_state("0013page") == {
            "status": "failed",
            "reason": "0013page: ページ本体ではないレスポンスです (text/html)",
        }

    def test_skips_already_downloaded_pages_on_resume(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        calls: list[str] = []
        client = _make_page_client(calls=calls)

        download_issue_artifacts(
            client,
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )
        first_call_count = len(calls)

        download_issue_artifacts(
            client,
            issue,
            tmp_path,
            raw_issue=_load_json("2026_2.raw.json"),
        )

        assert len(calls) == first_call_count

    def test_fetches_pdf_hash_when_manifest_has_no_urls(self, tmp_path: Path) -> None:
        issue = MagazineIssueKey("2026", "2")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url}")
            if request.url.path == "/headers/v1/headers":
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "1000", "message": "ok"},
                        "pdf_hash": "Policy=abc&Resource=https://shikiho.toyokeizai.net/files/shimen/premium/*",
                    },
                )
            if request.url.path.endswith(".pdf"):
                return httpx.Response(
                    200,
                    content=b"%PDF-1.4 page pdf",
                    headers={"content-type": "application/pdf"},
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.example.test")
        raw_issue = {
            "status": {"code": "1000", "message": "ok"},
            "magazine": {
                "calendar": "2026",
                "series": "2",
                "title": "春号",
                "pages": [
                    {"page": "0000page"},
                    {"page": "1433", "stock_code": "1433"},
                ],
            },
        }

        manifest = download_issue_artifacts(
            client,
            issue,
            tmp_path,
            raw_issue=raw_issue,
        )

        assert manifest["physical_page_count"] == 2
        assert (tmp_path / "2026_2" / "pages" / "0000page.pdf").exists()
        assert (tmp_path / "2026_2" / "pages" / "1433.pdf").exists()
        assert any("/headers/v1/headers" in call for call in calls)

from __future__ import annotations

import json
from pathlib import Path

from scrape.magazine.normalize import normalize_magazine
from scrape.magazine.types import MagazineIssueKey, PdfAccessInfo

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class TestNormalizeMagazine:
    def test_deduplicates_pages_and_aggregates_stock_codes(self) -> None:
        raw_issue = _load_json("2026_2.raw.json")

        manifest = normalize_magazine(raw_issue, MagazineIssueKey("2026", "2"))

        assert manifest["page_count"] == 5
        assert manifest["physical_page_count"] == 4
        assert manifest["title"] == "春号"
        assert manifest["sub_title"] == "ベーシック版"
        assert manifest["pages"][0]["source_url"] == "https://shikiho.toyokeizai.net/fixtures/0000page.png"

        duplicate_page = next(page for page in manifest["pages"] if page["page"] == "0100page")
        assert duplicate_page["stock_codes"] == ["1301", "7203"]
        assert duplicate_page["file_ext"] == ".pdf"

    def test_raises_when_pages_are_missing(self) -> None:
        raw_issue = {"status": {"code": "2000"}, "magazine": {"calendar": "2026", "series": "2"}}

        try:
            normalize_magazine(raw_issue, MagazineIssueKey("2026", "2"))
        except ValueError as exc:
            assert "pages" in str(exc)
        else:
            raise AssertionError("ValueError が送出されませんでした")

    def test_builds_pdf_urls_from_live_access_context(self) -> None:
        raw_issue = {
            "status": {"code": "1000"},
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
        access: PdfAccessInfo = {
            "pdf_hash": "Policy=abc&Resource=https://shikiho.toyokeizai.net/files/shimen/premium/*",
            "tier": "premium",
        }

        manifest = normalize_magazine(
            raw_issue,
            MagazineIssueKey("2026", "2"),
            pdf_access=access,
        )

        assert manifest["pages"][0]["source_url"] == (
            "https://shikiho.toyokeizai.net/files/shimen/premium/2026/2/0000page.pdf"
            "?Policy=abc&Resource=https://shikiho.toyokeizai.net/files/shimen/premium/*"
        )
        assert manifest["pages"][0]["file_ext"] == ".pdf"
        assert manifest["pages"][1]["source_url"] == (
            "https://shikiho.toyokeizai.net/files/shimen/premium/2026/2/1433.pdf"
            "?Policy=abc&Resource=https://shikiho.toyokeizai.net/files/shimen/premium/*"
        )

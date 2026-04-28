from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrape.client import PdfAccess, build_pdf_url, extract_page_ids, resolve_pdf_path


class TestBuildPdfUrl:
    def test_constructs_signed_url(self) -> None:
        access = PdfAccess(
            auth_level=6,
            pdf_hash="Policy=test_policy&Signature=test_sig&Key-Pair-Id=test_key",
            pdf_path="/files/shimen/premium",
        )
        url = build_pdf_url("2026", "2", "332A", access)
        assert "files/shimen/premium/2026/2/332A.pdf" in url
        assert "Policy=test_policy" in url
        assert "Signature=test_sig" in url
        assert "Key-Pair-Id=test_key" in url


class TestResolvePdfPath:
    def test_resolves_basic_path(self) -> None:
        assert resolve_pdf_path(3) == "/files/shimen/basic"

    def test_resolves_premium_path(self) -> None:
        assert resolve_pdf_path(6) == "/files/shimen/premium"

    def test_raises_for_unauthorized_level(self) -> None:
        with pytest.raises(PermissionError):
            resolve_pdf_path(1)


class TestExtractPageIds:
    def test_keeps_order_and_deduplicates(self) -> None:
        magazine = {
            "calendar": "1936",
            "series": "3",
            "title": "６月号",
            "subTitle": None,
            "pubDate": None,
            "pages": [
                {"type": "10", "page": "0000page"},
                {"type": "40", "stock_code": "3101", "page": "0016page"},
                {"type": "40", "page": "0017page"},
                {"type": "40", "stock_code": "3101", "page": "0016page"},
            ],
        }
        assert extract_page_ids(magazine) == ["0000page", "0016page", "0017page"]

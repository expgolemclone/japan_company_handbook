from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from scrape.client import PdfAccess
from scrape.downloader import download_pdf
from scrape.progress import DownloadKey, Progress


def _make_pdf_client() -> httpx.Client:
    """PDFレスポンスを返すモッククライアント。"""
    pdf_content = b"%PDF-1.4 fake pdf content"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=pdf_content,
            headers={"content-type": "application/pdf"},
        )

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


FAKE_ACCESS = PdfAccess(
    auth_level=6,
    pdf_hash="Policy=test_policy&Signature=test_sig&Key-Pair-Id=test_key",
    pdf_path="/files/shimen/premium",
)


class TestDownloadPdf:
    def test_saves_pdf_to_correct_path(self, tmp_path: Path) -> None:
        client = _make_pdf_client()
        dest = download_pdf(client, "2026", "2", "332A", FAKE_ACCESS, dest_dir=tmp_path)
        assert dest == tmp_path / "332A.pdf"
        assert dest.exists()
        assert dest.read_bytes() == b"%PDF-1.4 fake pdf content"

    def test_creates_dest_dir(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "nested" / "dir"
        client = _make_pdf_client()
        download_pdf(client, "2026", "2", "332A", FAKE_ACCESS, dest_dir=dest_dir)
        assert (dest_dir / "332A.pdf").exists()

    def test_raises_on_non_pdf_response(self, tmp_path: Path) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200, content=b"<html>error</html>", headers={"content-type": "text/html"}
            )
        )
        client = httpx.Client(transport=transport)

        with pytest.raises(ValueError, match="PDFではない"):
            download_pdf(client, "2026", "2", "332A", FAKE_ACCESS, dest_dir=tmp_path)

    def test_raises_on_http_error(self, tmp_path: Path) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(404, content=b"not found")
        )
        client = httpx.Client(transport=transport)

        with pytest.raises(httpx.HTTPStatusError):
            download_pdf(client, "2026", "2", "9999", FAKE_ACCESS, dest_dir=tmp_path)

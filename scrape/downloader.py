from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from scrape.client import SignedParams, build_pdf_url
from scrape.progress import DownloadKey, Progress

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REQUEST_INTERVAL = 1.0


def _issue_dir(year: str, series: str) -> Path:
    return DATA_DIR / f"{year}_{series}"


def download_pdf(
    client: httpx.Client,
    year: str,
    series: str,
    code: str,
    params: SignedParams,
    dest_dir: Path | None = None,
) -> Path:
    """1銘柄のPDFをダウンロードして保存する。"""
    url = build_pdf_url(year, series, code, params)
    dest_dir = dest_dir or _issue_dir(year, series)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{code}.pdf"

    resp = client.get(url)  # noqa: scrape-interval
    resp.raise_for_status()

    if resp.headers.get("content-type", "") != "application/pdf":
        raise ValueError(
            f"{code}: PDFではないレスポンス (content-type: {resp.headers.get('content-type')})"
        )

    dest.write_bytes(resp.content)
    logger.info("downloaded %s -> %s", code, dest)
    return dest


def download_all_stocks(
    client: httpx.Client,
    year: str,
    series: str,
    codes: list[str],
    params: SignedParams,
    progress: Progress,
    dest_dir: Path | None = None,
) -> None:
    """全銘柄のPDFを順次ダウンロードする（1秒間隔）。"""
    pending = progress.pending_codes(codes, year, series)
    logger.info(
        "[%s_%s] downloading %d / %d stocks",
        year, series, len(pending), len(codes),
    )

    for i, code in enumerate(pending):
        try:
            download_pdf(client, year, series, code, params, dest_dir)
            progress.mark_downloaded(DownloadKey(code, year, series))
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error for %s: %s", code, e)
            raise
        except ValueError as e:
            logger.warning("skipping %s: %s", code, e)

        if i < len(pending) - 1:
            time.sleep(REQUEST_INTERVAL)

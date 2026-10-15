from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from scrape.client import PdfAccess, build_pdf_url
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
    page_id: str,
    access: PdfAccess,
    dest_dir: Path | None = None,
) -> Path:
    """1ページ分のPDFをダウンロードして保存する。"""
    url = build_pdf_url(year, series, page_id, access)
    dest_dir = dest_dir or _issue_dir(year, series)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{page_id}.pdf"

    resp = client.get(url)  # noqa: scrape-interval
    resp.raise_for_status()

    if not resp.headers.get("content-type", "").startswith("application/pdf"):
        raise ValueError(
            f"{page_id}: PDFではないレスポンス (content-type: {resp.headers.get('content-type')})"
        )

    dest.write_bytes(resp.content)
    logger.info("downloaded %s -> %s", page_id, dest)
    return dest


def download_all_pages(
    client: httpx.Client,
    year: str,
    series: str,
    page_ids: list[str],
    access: PdfAccess,
    progress: Progress,
    dest_dir: Path | None = None,
    *,
    workers: int = 1,
) -> None:
    """全ページのPDFをダウンロードする。workers>1で並列実行。"""
    pending = progress.pending_pages(page_ids, year, series)
    logger.info(
        "[%s_%s] downloading %d / %d pages (workers=%d)",
        year, series, len(pending), len(page_ids), workers,
    )

    if workers <= 1:
        _download_sequential(client, year, series, pending, access, progress, dest_dir)
    else:
        _download_parallel(client, year, series, pending, access, progress, dest_dir, workers)
    progress.flush()


def _download_sequential(
    client: httpx.Client,
    year: str,
    series: str,
    pending: list[str],
    access: PdfAccess,
    progress: Progress,
    dest_dir: Path | None,
) -> None:
    for i, page_id in enumerate(pending):
        try:
            download_pdf(client, year, series, page_id, access, dest_dir)
            progress.mark_downloaded(DownloadKey(page_id, year, series))
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error for %s: %s", page_id, e)
            raise
        except ValueError as e:
            logger.warning("skipping %s: %s", page_id, e)

        if i < len(pending) - 1:
            time.sleep(REQUEST_INTERVAL)


def _download_parallel(
    client: httpx.Client,
    year: str,
    series: str,
    pending: list[str],
    access: PdfAccess,
    progress: Progress,
    dest_dir: Path | None,
    workers: int,
) -> None:
    key = DownloadKey  # local reference for closure

    def _download_one(page_id: str) -> str:
        download_pdf(client, year, series, page_id, access, dest_dir)
        progress.mark_downloaded(key(page_id, year, series))
        return page_id

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_one, pid): pid for pid in pending}
        for future in as_completed(futures):
            page_id = futures[future]
            try:
                future.result()
            except httpx.HTTPStatusError as e:
                logger.error("HTTP error for %s: %s", page_id, e)
                raise
            except ValueError as e:
                logger.warning("skipping %s: %s", page_id, e)

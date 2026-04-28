from __future__ import annotations

import logging

from scrape.client import (
    build_api_client,
    build_http_client,
    extract_page_ids,
    fetch_issues,
    fetch_magazine,
    fetch_pdf_access,
)
from scrape.downloader import download_all_pages
from scrape.progress import Progress

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    api_client = build_api_client()
    access = fetch_pdf_access(api_client)
    issues = fetch_issues(api_client, from_year=1936)

    logger.info("取得対象号数: %d", len(issues))
    if issues:
        first = issues[0]
        last = issues[-1]
        logger.info(
            "対象範囲: %s年 %s 〜 %s年 %s",
            first["calendar"], first["title"], last["calendar"], last["title"],
        )

    client = build_http_client()
    progress = Progress()

    for issue in issues:
        year = issue["calendar"]
        series = issue["series"]
        title = issue["title"]
        logger.info("=== %s年 %s (%s) ===", year, title, series)

        magazine = fetch_magazine(api_client, year, series)
        page_ids = extract_page_ids(magazine)
        logger.info("ページ数: %d", len(page_ids))

        download_all_pages(client, year, series, page_ids, access, progress)

    logger.info("完了")


if __name__ == "__main__":
    main()

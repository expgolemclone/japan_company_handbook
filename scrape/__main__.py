from __future__ import annotations

import logging

from scrape.client import ISSUES, build_http_client, load_signed_params, load_stock_codes
from scrape.downloader import download_all_stocks
from scrape.progress import Progress

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("直近4号:")
    for issue in ISSUES:
        logger.info("  %s年 %s (%s)", issue["calendar"], issue["title"], issue["pub_date"])

    params = load_signed_params()
    client = build_http_client()
    progress = Progress()

    for issue in ISSUES:
        year = issue["calendar"]
        series = issue["series"]
        title = issue["title"]
        logger.info("=== %s年 %s (%s) ===", year, title, series)

        codes = load_stock_codes(year, series)
        logger.info("銘柄数: %d", len(codes))

        download_all_stocks(client, year, series, codes, params, progress)

    logger.info("完了")


if __name__ == "__main__":
    main()

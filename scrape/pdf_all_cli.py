from __future__ import annotations

import argparse
import logging

import httpx

from scrape.auth import refresh_cookies_via_chrome
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

DESCRIPTION = "四季報ビューア全号のページPDFを保存する"
logger = logging.getLogger(__name__)


def build_parser(
    *,
    prog: str | None = None,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        add_help=add_help,
    )


def run(_args: argparse.Namespace) -> int:
    _configure_logging()
    api_client = build_api_client()
    client = None

    try:
        try:
            access = fetch_pdf_access(api_client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise

            logger.warning(
                "認証に失敗しました。Chromeで四季報オンラインを開いてCookie更新を試みます。"
            )
            if not refresh_cookies_via_chrome():
                logger.error(
                    "Cookie更新に失敗しました。Chromeで四季報オンラインにログインしてください。"
                )
                raise

            api_client.close()
            api_client = build_api_client()
            access = fetch_pdf_access(api_client)

        issues = fetch_issues(api_client, from_year=1936)

        logger.info("取得対象号数: %d", len(issues))
        if issues:
            first = issues[0]
            last = issues[-1]
            logger.info(
                "対象範囲: %s年 %s 〜 %s年 %s",
                first["calendar"],
                first["title"],
                last["calendar"],
                last["title"],
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
        return 0
    finally:
        api_client.close()
        if client is not None:
            client.close()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

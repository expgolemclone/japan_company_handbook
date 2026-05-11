from __future__ import annotations

import argparse
import logging
from typing import Callable, TypeVar

import httpx

from scrape.auth import is_http_auth_error, refresh_cookie_source
from scrape.client import (
    PdfAccess,
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
T = TypeVar("T")


def build_parser(
    *,
    prog: str | None = None,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        add_help=add_help,
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="並列ダウンロード数 (default: 1 = 直列)",
    )
    return parser


def run(_args: argparse.Namespace) -> int:
    _configure_logging()
    api_client = build_api_client()
    client = None

    try:
        access, api_client = _fetch_pdf_access_with_retry(api_client)
        issues, api_client, access = _call_api_with_refresh(
            api_client,
            access,
            lambda current_client: fetch_issues(current_client, from_year=1936),
            label="号一覧取得",
        )

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

            auth_retry_used = False
            while True:
                try:
                    magazine = fetch_magazine(api_client, year, series)
                    page_ids = extract_page_ids(magazine)
                    logger.info("ページ数: %d", len(page_ids))

                    download_all_pages(
                        client, year, series, page_ids, access, progress,
                        workers=_args.workers,
                    )
                except httpx.HTTPStatusError as exc:
                    if not is_http_auth_error(exc) or auth_retry_used:
                        raise
                    api_client, access = _refresh_pdf_session(api_client)
                    auth_retry_used = True
                    logger.info("認証を再確認したため同じ号を再試行します: %s_%s", year, series)
                    continue
                break

        logger.info("完了")
        return 0
    finally:
        api_client.close()
        if client is not None:
            client.close()


def _fetch_pdf_access_with_retry(api_client: httpx.Client) -> tuple[PdfAccess, httpx.Client]:
    try:
        return fetch_pdf_access(api_client), api_client
    except httpx.HTTPStatusError as exc:
        if not is_http_auth_error(exc):
            raise
        refreshed_client, access = _refresh_pdf_session(api_client)
        return access, refreshed_client


def _call_api_with_refresh(
    api_client: httpx.Client,
    access: PdfAccess,
    operation: Callable[[httpx.Client], T],
    *,
    label: str,
) -> tuple[T, httpx.Client, PdfAccess]:
    auth_retry_used = False

    while True:
        try:
            return operation(api_client), api_client, access
        except httpx.HTTPStatusError as exc:
            if not is_http_auth_error(exc) or auth_retry_used:
                raise
            api_client, access = _refresh_pdf_session(api_client)
            auth_retry_used = True
            logger.info("認証を再確認したため%sを再試行します。", label)


def _refresh_pdf_session(api_client: httpx.Client) -> tuple[httpx.Client, PdfAccess]:
    logger.warning(
        "認証に失敗しました。Chromeで四季報オンラインを開いてCookie更新を試みます。"
    )
    if not refresh_cookie_source():
        logger.error(
            "Cookie更新に失敗しました。Chromeで四季報オンラインにログインしてください。"
        )
        raise RuntimeError("Cookie更新に失敗しました")

    api_client.close()
    refreshed_client = build_api_client()
    access = fetch_pdf_access(refreshed_client)
    return refreshed_client, access


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

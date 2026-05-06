from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scrape.auth import DEFAULT_CHROME_COOKIES
from scrape.magazine.client import MAGAZINES_DIR, build_magazine_http_client
from scrape.magazine.downloader import download_issue_artifacts
from scrape.magazine.types import MagazineIssueKey
from scrape.magazine.verify import verify_issue_directory

logger = logging.getLogger(__name__)
DESCRIPTION = "四季報ビューアの単号を保存する"


def run(args: argparse.Namespace) -> int:
    _configure_logging()

    issue = MagazineIssueKey(calendar=args.calendar, series=args.series)
    with build_magazine_http_client(args.cookie_file) as client:
        download_issue_artifacts(
            client,
            issue,
            args.out_dir,
            request_interval=args.request_interval,
        )

    report = verify_issue_directory(issue, args.out_dir)
    if not report["ok"]:
        logger.error("単号検証に失敗しました: %s", report)
        return 1

    logger.info("完了: %s", issue)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


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
    parser.add_argument("--calendar", required=True, help="西暦")
    parser.add_argument("--series", required=True, help="号番号")
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=DEFAULT_CHROME_COOKIES,
        help="ログイン済みCookie JSON",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=MAGAZINES_DIR,
        help="保存先ディレクトリ",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.0,
        help="ページごとの待機秒数",
    )
    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(main())

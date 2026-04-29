from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scrape.auth import DEFAULT_CHROME_COOKIES
from scrape.magazine.audit import (
    build_auth_diagnostics,
    build_fact_check_report,
    load_local_sample_issues,
    write_auth_diagnostics,
    write_fact_check_report,
)
from scrape.magazine.client import (
    AUTH_DIAGNOSTICS_FILE,
    FACT_CHECK_REPORT_FILE,
    MAGAZINES_DIR,
    build_magazine_http_client,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    fact_report = build_fact_check_report(args.out_dir)
    write_fact_check_report(fact_report, args.out_dir / FACT_CHECK_REPORT_FILE.name)

    sample_issues = load_local_sample_issues(args.out_dir)
    with build_magazine_http_client(args.cookie_file) as client:
        auth_report, _, _ = build_auth_diagnostics(
            client,
            sample_issues=sample_issues,
            start_calendar=args.start_calendar,
        )
    write_auth_diagnostics(auth_report, args.out_dir / AUTH_DIAGNOSTICS_FILE.name)

    if not auth_report["ok"]:
        logger.error("認証診断に失敗しました")
        return 1

    logger.info("監査完了")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="四季報ビューアの欠号監査と認証診断を実行する"
    )
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
        "--start-calendar",
        type=int,
        default=1936,
        help="取得対象の最古年",
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

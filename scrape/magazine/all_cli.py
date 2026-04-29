from __future__ import annotations

import argparse
import logging
from pathlib import Path

import httpx

from scrape.auth import DEFAULT_CHROME_COOKIES, refresh_cookies_via_chrome
from scrape.magazine.audit import build_auth_diagnostics, write_auth_diagnostics
from scrape.magazine.client import (
    AUTH_DIAGNOSTICS_FILE,
    BATCH_PROGRESS_FILE,
    BATCH_SUMMARY_FILE,
    EXPECTED_ISSUES_FILE,
    ISSUES_RAW_FILE,
    MAGAZINES_DIR,
    VERIFY_REPORT_FILE,
    build_magazine_http_client,
    save_expected_issues,
    save_issue_list_cache,
)
from scrape.magazine.downloader import download_issue_artifacts
from scrape.magazine.progress import BatchProgress
from scrape.magazine.summary import build_batch_summary, write_batch_summary
from scrape.magazine.verify import verify_all_issues, write_verify_report

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    batch_progress = BatchProgress(args.out_dir / BATCH_PROGRESS_FILE.name)
    refresh_cookies_via_chrome()
    with build_magazine_http_client(args.cookie_file) as client:
        auth_report, raw_issues, issues = build_auth_diagnostics(
            client,
            start_calendar=args.start_calendar,
        )
        if raw_issues is None or not issues or not auth_report["ok"]:
            write_auth_diagnostics(
                auth_report,
                args.out_dir / AUTH_DIAGNOSTICS_FILE.name,
            )
            logger.error("事前認証診断に失敗しました")
            return 1

        save_issue_list_cache(raw_issues, args.out_dir / ISSUES_RAW_FILE.name)
        save_expected_issues(issues, args.out_dir / EXPECTED_ISSUES_FILE.name)

        for issue in issues:
            if args.resume and batch_progress.is_succeeded(issue):
                logger.info("skip succeeded issue: %s", issue)
                continue

            logger.info("start issue: %s", issue)
            batch_progress.mark_running(issue)
            try:
                download_issue_artifacts(
                    client,
                    issue,
                    args.out_dir,
                    request_interval=args.request_interval,
                )
            except (httpx.HTTPStatusError, httpx.TransportError, ValueError, OSError) as exc:
                logger.exception("issue failed: %s", issue)
                batch_progress.mark_failed(issue, str(exc))
                continue

            batch_progress.mark_succeeded(issue)

    verify_report = None
    if args.verify_after_run:
        verify_report = verify_all_issues(
            args.out_dir,
            expected_issues_path=args.out_dir / EXPECTED_ISSUES_FILE.name,
            batch_progress_path=args.out_dir / BATCH_PROGRESS_FILE.name,
        )
        write_verify_report(verify_report, args.out_dir / VERIFY_REPORT_FILE.name)

    summary = build_batch_summary(batch_progress, verify_report)
    write_batch_summary(summary, args.out_dir / BATCH_SUMMARY_FILE.name)

    if verify_report is not None and not verify_report["verified_complete"]:
        logger.error("全号検証に失敗しました")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="四季報ビューアの全号を保存する")
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
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.0,
        help="ページごとの待機秒数",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="成功済みの号をスキップして再開する",
    )
    parser.add_argument(
        "--verify-after-run",
        action="store_true",
        help="取得後に完全性検証を実行する",
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

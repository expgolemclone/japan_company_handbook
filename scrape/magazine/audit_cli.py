from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from scrape.auth import DEFAULT_CHROME_COOKIES, refresh_cookie_source
from scrape.magazine.audit import (
    build_auth_diagnostics,
    build_fact_check_report,
    load_local_sample_issues,
    should_refresh_for_auth_diagnostics,
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
DESCRIPTION = "四季報ビューアの欠号監査と認証診断を実行する"


def run(args: argparse.Namespace) -> int:
    _configure_logging()

    fact_report = build_fact_check_report(args.out_dir)
    write_fact_check_report(fact_report, args.out_dir / FACT_CHECK_REPORT_FILE.name)

    sample_issues = load_local_sample_issues(args.out_dir)
    auth_report = _run_auth_diagnostics(args, sample_issues)
    write_auth_diagnostics(auth_report, args.out_dir / AUTH_DIAGNOSTICS_FILE.name)

    if not auth_report["ok"]:
        logger.error("認証診断に失敗しました")
        return 1

    logger.info("監査完了")
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


def _run_auth_diagnostics(
    args: argparse.Namespace,
    sample_issues,
) -> dict[str, object]:
    refresh_used = False

    while True:
        try:
            client = build_magazine_http_client(args.cookie_file)
        except (FileNotFoundError, OSError, ValueError) as exc:
            if refresh_used or not refresh_cookie_source(args.cookie_file):
                return _build_client_auth_failure_report(str(exc))
            refresh_used = True
            continue

        with client:
            auth_report, _, _ = build_auth_diagnostics(
                client,
                sample_issues=sample_issues,
                start_calendar=args.start_calendar,
            )

        if auth_report["ok"]:
            return auth_report
        if refresh_used or not should_refresh_for_auth_diagnostics(auth_report):
            return auth_report
        if not refresh_cookie_source(args.cookie_file):
            return auth_report
        refresh_used = True


def _build_client_auth_failure_report(error: str) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_issues": [],
        "live_issue_count": 0,
        "ok": False,
        "checks": [
            {
                "name": "client_build",
                "url": None,
                "issue": None,
                "ok": False,
                "category": "client_build_error",
                "error": error,
            }
        ],
        "category_counts": {"client_build_error": 1},
    }


if __name__ == "__main__":
    raise SystemExit(main())

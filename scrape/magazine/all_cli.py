from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Callable

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
    MagazineApiError,
    MagazineIssueKey,
    VERIFY_REPORT_FILE,
    build_magazine_http_client,
    is_probable_auth_error,
    save_expected_issues,
    save_issue_list_cache,
)
from scrape.magazine.downloader import download_issue_artifacts
from scrape.magazine.progress import BatchProgress
from scrape.magazine.summary import build_batch_summary, write_batch_summary
from scrape.magazine.verify import verify_all_issues, write_verify_report

logger = logging.getLogger(__name__)
DESCRIPTION = "四季報ビューアの全号を保存する"

AUTH_RETRY_TIMEOUT_SECONDS = 20.0
AUTH_RETRY_POLL_SECONDS = 2.0
ISSUE_EXCEPTIONS = (
    httpx.HTTPStatusError,
    httpx.TransportError,
    MagazineApiError,
    ValueError,
    OSError,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


def run(args: argparse.Namespace) -> int:
    _configure_logging()

    batch_progress = BatchProgress(args.out_dir / BATCH_PROGRESS_FILE.name)
    client_builder = partial(build_magazine_http_client, args.cookie_file)
    client, raw_issues, issues = _authenticate_client(
        client_builder,
        cookie_file=args.cookie_file,
        out_dir=args.out_dir,
        start_calendar=args.start_calendar,
    )
    if client is None or raw_issues is None or issues is None:
        logger.error("事前認証診断に失敗しました")
        return 1

    save_issue_list_cache(raw_issues, args.out_dir / ISSUES_RAW_FILE.name)
    save_expected_issues(issues, args.out_dir / EXPECTED_ISSUES_FILE.name)

    try:
        for issue in issues:
            if args.resume and batch_progress.is_succeeded(issue):
                logger.info("skip succeeded issue: %s", issue)
                continue

            logger.info("start issue: %s", issue)
            batch_progress.mark_running(issue)
            auth_retry_used = False

            while True:
                try:
                    download_issue_artifacts(
                        client,
                        issue,
                        args.out_dir,
                        request_interval=args.request_interval,
                    )
                except ISSUE_EXCEPTIONS as exc:
                    logger.exception("issue failed: %s", issue)
                    if not is_probable_auth_error(exc):
                        batch_progress.mark_failed(issue, str(exc))
                        break

                    if auth_retry_used:
                        batch_progress.mark_failed(issue, str(exc))
                        _write_runtime_auth_diagnostics(
                            client,
                            issue=issue,
                            error=exc,
                            out_dir=args.out_dir,
                            start_calendar=args.start_calendar,
                        )
                        logger.error("再認証後も認証異常が解消しませんでした: %s", issue)
                        return 1

                    client.close()
                    refreshed_client, _, _ = _authenticate_client(
                        client_builder,
                        cookie_file=args.cookie_file,
                        out_dir=args.out_dir,
                        start_calendar=args.start_calendar,
                        sample_issues=[issue],
                    )
                    if refreshed_client is None:
                        batch_progress.mark_failed(issue, str(exc))
                        logger.error("認証を回復できなかったため停止します: %s", issue)
                        return 1

                    client = refreshed_client
                    auth_retry_used = True
                    logger.info("認証を再確認したため同じ号を再試行します: %s", issue)
                    continue

                batch_progress.mark_succeeded(issue)
                break
    finally:
        client.close()

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


def _authenticate_client(
    client_builder: Callable[[], httpx.Client],
    *,
    cookie_file: Path,
    out_dir: Path,
    start_calendar: int,
    sample_issues: list[MagazineIssueKey] | None = None,
) -> tuple[httpx.Client | None, dict[str, object] | None, list[MagazineIssueKey] | None]:
    can_wait_for_refresh = _refresh_cookie_source(cookie_file)
    deadline = time.monotonic() + AUTH_RETRY_TIMEOUT_SECONDS if can_wait_for_refresh else None
    last_report: dict[str, object] | None = None
    last_error: Exception | None = None

    while True:
        try:
            client = client_builder()
        except (FileNotFoundError, OSError, ValueError) as exc:
            last_error = exc
        else:
            auth_report, raw_issues, issues = build_auth_diagnostics(
                client,
                sample_issues=sample_issues,
                start_calendar=start_calendar,
            )
            if _auth_preflight_ok(auth_report, raw_issues, issues):
                return client, raw_issues, issues

            last_report = auth_report
            client.close()

        if deadline is None or time.monotonic() >= deadline:
            break
        time.sleep(AUTH_RETRY_POLL_SECONDS)

    failure_report = last_report or _build_client_auth_failure_report(
        error=str(last_error) if last_error is not None else "認証用clientを構築できませんでした",
        sample_issues=sample_issues,
    )
    write_auth_diagnostics(failure_report, out_dir / AUTH_DIAGNOSTICS_FILE.name)
    return None, None, None


def _refresh_cookie_source(cookie_file: Path) -> bool:
    if cookie_file.suffix == ".json":
        logger.warning("JSON Cookie ファイルでは Chrome 自動更新を利用できません: %s", cookie_file)
        return False
    return refresh_cookies_via_chrome(cookies_db=cookie_file)


def _auth_preflight_ok(
    auth_report: dict[str, object],
    raw_issues: dict[str, object] | None,
    issues: list[MagazineIssueKey],
) -> bool:
    return raw_issues is not None and bool(issues) and bool(auth_report.get("ok"))


def _write_runtime_auth_diagnostics(
    client: httpx.Client,
    *,
    issue: MagazineIssueKey,
    error: Exception,
    out_dir: Path,
    start_calendar: int,
) -> None:
    try:
        report, _, _ = build_auth_diagnostics(
            client,
            sample_issues=[issue],
            start_calendar=start_calendar,
        )
    except ISSUE_EXCEPTIONS as exc:
        report = _build_client_auth_failure_report(
            error=str(exc),
            sample_issues=[issue],
            category="diagnostic_error",
        )

    checks = report.get("checks")
    if not isinstance(checks, list):
        checks = []
        report["checks"] = checks

    checks.append(_build_issue_auth_check(issue, error))
    report["sample_issues"] = [str(issue)]
    report["ok"] = False
    report["category_counts"] = dict(
        sorted(Counter(str(check.get("category", "unknown")) for check in checks).items())
    )
    write_auth_diagnostics(report, out_dir / AUTH_DIAGNOSTICS_FILE.name)


def _build_client_auth_failure_report(
    *,
    error: str,
    sample_issues: list[MagazineIssueKey] | None = None,
    category: str = "client_build_error",
) -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_issues": [str(issue) for issue in sample_issues or []],
        "live_issue_count": 0,
        "ok": False,
        "checks": [
            {
                "name": "client_build",
                "url": None,
                "issue": None,
                "ok": False,
                "category": category,
                "error": error,
            }
        ],
        "category_counts": {category: 1},
    }


def _build_issue_auth_check(
    issue: MagazineIssueKey,
    error: Exception,
) -> dict[str, object]:
    category = "auth_error"
    http_status = None
    if isinstance(error, httpx.HTTPStatusError):
        category = "http_status_error"
        if error.response is not None:
            http_status = error.response.status_code
    elif isinstance(error, MagazineApiError):
        if error.__class__.__name__ == "MagazinePermissionError":
            category = "payload_permission_error"
        elif error.__class__.__name__ == "MagazinePayloadShapeError":
            category = "payload_shape_error"

    payload = {
        "name": "issue_runtime_failure",
        "url": None,
        "issue": str(issue),
        "ok": False,
        "category": category,
        "error": str(error),
    }
    if http_status is not None:
        payload["http_status"] = http_status
    return payload


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

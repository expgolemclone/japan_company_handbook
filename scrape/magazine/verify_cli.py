from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scrape.magazine.client import (
    BATCH_PROGRESS_FILE,
    BATCH_SUMMARY_FILE,
    EXPECTED_ISSUES_FILE,
    MAGAZINES_DIR,
    VERIFY_REPORT_FILE,
)
from scrape.magazine.progress import BatchProgress
from scrape.magazine.summary import build_batch_summary, write_batch_summary
from scrape.magazine.verify import verify_all_issues, write_verify_report

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    report = verify_all_issues(
        args.out_dir,
        expected_issues_path=args.out_dir / EXPECTED_ISSUES_FILE.name,
        batch_progress_path=args.out_dir / BATCH_PROGRESS_FILE.name,
    )
    write_verify_report(report, args.out_dir / VERIFY_REPORT_FILE.name)

    batch_progress = BatchProgress(args.out_dir / BATCH_PROGRESS_FILE.name)
    summary = build_batch_summary(batch_progress, report)
    write_batch_summary(summary, args.out_dir / BATCH_SUMMARY_FILE.name)

    if not report["verified_complete"]:
        logger.error("検証に失敗しました")
        return 1

    logger.info("検証完了")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="四季報ビューア全号の完全性を検証する")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=MAGAZINES_DIR,
        help="保存先ディレクトリ",
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

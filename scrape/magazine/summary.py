from __future__ import annotations

import json
from pathlib import Path

from scrape.magazine.progress import BatchProgress
from scrape.magazine.types import BatchSummary, VerifyReport


def build_batch_summary(
    batch_progress: BatchProgress, verify_report: VerifyReport | None = None
) -> BatchSummary:
    records = batch_progress.records()
    succeeded = sorted(
        slug for slug, record in records.items() if record.get("status") == "succeeded"
    )
    failed = {
        slug: dict(record)
        for slug, record in records.items()
        if record.get("status") == "failed"
    }

    summary = BatchSummary(
        issue_count=len(records),
        succeeded_count=len(succeeded),
        failed_count=len(failed),
        succeeded_issues=succeeded,
        failed_issues=failed,
    )
    if verify_report is not None:
        summary["verify"] = {
            "expected_issue_count": verify_report["expected_issue_count"],
            "completed_issue_count": verify_report["completed_issue_count"],
            "verified_complete": verify_report["verified_complete"],
            "missing_issue_count": verify_report["missing_issue_count"],
            "missing_page_count": verify_report["missing_page_count"],
        }
    return summary


def write_batch_summary(summary: BatchSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

from __future__ import annotations

import json
from pathlib import Path

from scrape.magazine.client import (
    BATCH_PROGRESS_FILE,
    EXPECTED_ISSUES_FILE,
    MAGAZINES_DIR,
    load_expected_issues,
    issue_dir,
)
from scrape.magazine.progress import BatchProgress, IssueProgress
from scrape.magazine.types import (
    IssueVerifyReport,
    MagazineIssueKey,
    MissingPageEntry,
    VerifyReport,
)

RAW_MANIFEST_FILE = "manifest.raw.json"
NORMALIZED_MANIFEST_FILE = "manifest.normalized.json"
PROGRESS_FILE = "progress.json"
PAGES_DIR = "pages"


def verify_issue_directory(
    issue: MagazineIssueKey, out_dir: Path = MAGAZINES_DIR
) -> IssueVerifyReport:
    issue_path = issue_dir(out_dir, issue)
    raw_path = issue_path / RAW_MANIFEST_FILE
    normalized_path = issue_path / NORMALIZED_MANIFEST_FILE
    progress_path = issue_path / PROGRESS_FILE
    pages_dir = issue_path / PAGES_DIR

    errors: list[str] = []
    if not raw_path.exists():
        errors.append(f"raw manifest がありません: {raw_path.name}")
    if not normalized_path.exists():
        errors.append(f"normalized manifest がありません: {normalized_path.name}")
    if not progress_path.exists():
        errors.append(f"progress がありません: {progress_path.name}")

    if not normalized_path.exists():
        return _issue_report(
            issue=issue,
            ok=False,
            errors=errors,
            missing_pages=[],
            missing_files=[],
            extra_files=[],
            physical_page_count=0,
            actual_file_count=0,
        )

    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    expected_pages = [page["page"] for page in normalized.get("pages", [])]
    progress = IssueProgress(progress_path)
    actual_files = (
        sorted(path.name for path in pages_dir.iterdir() if path.is_file())
        if pages_dir.exists()
        else []
    )

    missing_pages: list[str] = []
    missing_files: list[str] = []
    referenced_files: set[str] = set()

    for page_id in expected_pages:
        state = progress.page_state(page_id)
        if state is None or state.get("status") != "completed":
            missing_pages.append(page_id)
            continue

        filename = state.get("filename")
        if not isinstance(filename, str) or not filename:
            missing_pages.append(page_id)
            continue

        referenced_files.add(filename)
        if not (pages_dir / filename).exists():
            missing_pages.append(page_id)
            missing_files.append(filename)

    extra_files = sorted(set(actual_files) - referenced_files)
    physical_page_count = int(normalized.get("physical_page_count", len(expected_pages)))
    count_matches = len(referenced_files) == physical_page_count
    if not count_matches:
        errors.append(
            "physical_page_count と completed file 数が一致しません"
        )
    if extra_files:
        errors.append("pages ディレクトリに余分なファイルがあります")
    if not progress.completed:
        errors.append("issue progress が completed ではありません")

    ok = not errors and not missing_pages and not missing_files and not extra_files
    return _issue_report(
        issue=issue,
        ok=ok,
        errors=errors,
        missing_pages=missing_pages,
        missing_files=missing_files,
        extra_files=extra_files,
        physical_page_count=physical_page_count,
        actual_file_count=len(actual_files),
    )


def verify_all_issues(
    out_dir: Path = MAGAZINES_DIR,
    *,
    expected_issues_path: Path = EXPECTED_ISSUES_FILE,
    batch_progress_path: Path = BATCH_PROGRESS_FILE,
) -> VerifyReport:
    expected_issues = load_expected_issues(expected_issues_path)
    batch_progress = BatchProgress(batch_progress_path)

    issue_reports: list[IssueVerifyReport] = []
    missing_issues: list[str] = []
    missing_pages: list[MissingPageEntry] = []
    failed_by_issue: dict[str, dict[str, object]] = {}
    verified_issues: list[str] = []

    for issue in expected_issues:
        slug = str(issue)
        if not issue_dir(out_dir, issue).exists():
            missing_issues.append(slug)
            failed_by_issue[slug] = {
                "issue": slug,
                "status": batch_progress.status(issue),
                "error": batch_progress.error(issue),
            }
            continue

        report = verify_issue_directory(issue, out_dir)
        issue_reports.append(report)
        if report["missing_pages"]:
            missing_pages.append({"issue": slug, "pages": report["missing_pages"]})

        status = batch_progress.status(issue)
        if not report["ok"] or status != "succeeded":
            failed_by_issue[slug] = {
                "issue": slug,
                "status": status,
                "error": batch_progress.error(issue),
                "errors": report["errors"],
            }
            continue

        verified_issues.append(slug)

    earliest_expected = str(expected_issues[0]) if expected_issues else None
    earliest_verified = verified_issues[0] if verified_issues else None
    verified_complete = (
        len(verified_issues) == len(expected_issues)
        and not missing_issues
        and not failed_by_issue
        and not missing_pages
    )

    return VerifyReport(
        expected_issue_count=len(expected_issues),
        completed_issue_count=len(verified_issues),
        failed_issue_count=len(failed_by_issue),
        missing_issue_count=len(missing_issues),
        missing_page_count=sum(len(item["pages"]) for item in missing_pages),
        earliest_expected_issue=earliest_expected,
        earliest_verified_issue=earliest_verified,
        verified_complete=verified_complete,
        missing_issues=missing_issues,
        failed_issues=list(failed_by_issue.values()),
        missing_pages=missing_pages,
        issue_reports=issue_reports,
    )


def write_verify_report(report: VerifyReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _issue_report(
    *,
    issue: MagazineIssueKey,
    ok: bool,
    errors: list[str],
    missing_pages: list[str],
    missing_files: list[str],
    extra_files: list[str],
    physical_page_count: int,
    actual_file_count: int,
) -> IssueVerifyReport:
    return IssueVerifyReport(
        issue=str(issue),
        ok=ok,
        errors=errors,
        missing_pages=missing_pages,
        missing_files=missing_files,
        extra_files=extra_files,
        physical_page_count=physical_page_count,
        actual_file_count=actual_file_count,
    )

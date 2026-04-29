from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True, slots=True)
class MagazineIssueKey:
    calendar: str
    series: str

    def __str__(self) -> str:
        return f"{self.calendar}_{self.series}"

    def to_dict(self) -> dict[str, str]:
        return {"calendar": self.calendar, "series": self.series}


class NormalizedPage(TypedDict):
    page: str
    order: int
    stock_codes: list[str]
    source_url: str | None
    file_ext: str | None


class NormalizedMagazine(TypedDict):
    issue: dict[str, str]
    title: str
    sub_title: str | None
    pub_date: str | None
    page_count: int
    physical_page_count: int
    pages: list[NormalizedPage]


class PdfAccessInfo(TypedDict):
    pdf_hash: str
    tier: str


class PageProgressState(TypedDict, total=False):
    status: str
    filename: str
    reason: str


class IssueProgressState(TypedDict):
    expected_pages: list[str]
    pages: dict[str, PageProgressState]
    completed: bool


class BatchRecord(TypedDict):
    status: str
    error: str | None


class BatchProgressState(TypedDict):
    issues: dict[str, BatchRecord]


class IssueVerifyReport(TypedDict):
    issue: str
    ok: bool
    errors: list[str]
    missing_pages: list[str]
    missing_files: list[str]
    extra_files: list[str]
    physical_page_count: int
    actual_file_count: int


class MissingPageEntry(TypedDict):
    issue: str
    pages: list[str]


class VerifyReport(TypedDict):
    expected_issue_count: int
    completed_issue_count: int
    failed_issue_count: int
    missing_issue_count: int
    missing_page_count: int
    earliest_expected_issue: str | None
    earliest_verified_issue: str | None
    verified_complete: bool
    missing_issues: list[str]
    failed_issues: list[dict[str, object]]
    missing_pages: list[MissingPageEntry]
    issue_reports: list[IssueVerifyReport]


class BatchSummary(TypedDict):
    issue_count: int
    succeeded_count: int
    failed_count: int
    succeeded_issues: list[str]
    failed_issues: dict[str, BatchRecord]


class BatchSummaryWithVerify(BatchSummary):
    verify: VerifySummary


class VerifySummary(TypedDict):
    expected_issue_count: int
    completed_issue_count: int
    verified_complete: bool
    missing_issue_count: int
    missing_page_count: int

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

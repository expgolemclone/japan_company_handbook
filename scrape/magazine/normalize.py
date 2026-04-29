from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

from scrape.magazine.client import SITE_BASE, build_pdf_source_url
from scrape.magazine.types import (
    MagazineIssueKey,
    NormalizedMagazine,
    NormalizedPage,
    PdfAccessInfo,
)

FILE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
FILE_EXTENSION_RE = re.compile(r"\.(pdf|png|jpe?g|webp)(?:$|\?)", re.IGNORECASE)
PAGE_KEYS = ("page", "page_id", "pageId", "pdf_name", "pdfName", "id")
STOCK_KEYS = ("stock_code", "stockCode", "code")
URL_HINTS = (
    "download_url",
    "downloadurl",
    "file_url",
    "fileurl",
    "image_url",
    "imageurl",
    "pdf_url",
    "pdfurl",
    "src",
    "url",
    "image",
    "img",
    "path",
)


def normalize_magazine(
    raw_issue: dict[str, Any],
    issue: MagazineIssueKey | None = None,
    *,
    pdf_access: PdfAccessInfo | None = None,
) -> NormalizedMagazine:
    raw_magazine = raw_issue.get("magazine")
    if not isinstance(raw_magazine, dict):
        raise ValueError("誌面レスポンスに magazine がありません")

    raw_pages = raw_magazine.get("pages")
    if not isinstance(raw_pages, list):
        raise ValueError("誌面レスポンスに pages がありません")

    resolved_issue = issue or MagazineIssueKey(
        calendar=str(raw_magazine["calendar"]),
        series=str(raw_magazine["series"]),
    )
    pages: list[NormalizedPage] = []
    seen_pages: dict[str, NormalizedPage] = {}

    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raise ValueError("pages の要素がオブジェクトではありません")

        page_id = _extract_page_id(raw_page)
        stock_code = _extract_stock_code(raw_page)
        source_url = _resolve_source_url(raw_page, resolved_issue, pdf_access)
        page = seen_pages.get(page_id)
        if page is None:
            page = NormalizedPage(
                page=page_id,
                order=len(pages),
                stock_codes=[],
                source_url=source_url,
                file_ext=_resolve_file_extension(source_url, pdf_access),
            )
            seen_pages[page_id] = page
            pages.append(page)
        elif page["source_url"] is None and source_url is not None:
            page["source_url"] = source_url
            page["file_ext"] = _resolve_file_extension(source_url, pdf_access)

        if stock_code and stock_code not in page["stock_codes"]:
            page["stock_codes"].append(stock_code)

    return NormalizedMagazine(
        issue=resolved_issue.to_dict(),
        title=str(raw_magazine.get("title", "")),
        sub_title=_optional_str(raw_magazine.get("subTitle")),
        pub_date=_optional_str(
            raw_magazine.get("pubDate")
            or raw_magazine.get("publishDate")
            or raw_magazine.get("publishedAt")
        ),
        page_count=len(raw_pages),
        physical_page_count=len(pages),
        pages=pages,
    )


def guess_file_extension_from_url(url: str | None) -> str | None:
    if not url:
        return None

    path = PurePosixPath(urlparse(url).path)
    suffix = path.suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    if suffix in FILE_EXTENSIONS:
        return suffix

    match = FILE_EXTENSION_RE.search(url)
    if not match:
        return None

    ext = f".{match.group(1).lower()}"
    if ext == ".jpeg":
        return ".jpg"
    return ext


def _extract_page_id(raw_page: dict[str, Any]) -> str:
    for key in PAGE_KEYS:
        value = raw_page.get(key)
        if value:
            return str(value)
    raise ValueError(f"page id を解決できません: {raw_page}")


def _extract_stock_code(raw_page: dict[str, Any]) -> str | None:
    for key in STOCK_KEYS:
        value = raw_page.get(key)
        if value:
            return str(value)
    return None


def _extract_source_url(raw_page: dict[str, Any]) -> str | None:
    candidates: list[tuple[int, str]] = []
    _collect_source_candidates(raw_page, candidates)
    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return _normalize_candidate_url(candidates[0][1])


def _resolve_source_url(
    raw_page: dict[str, Any],
    issue: MagazineIssueKey,
    pdf_access: PdfAccessInfo | None,
) -> str | None:
    if pdf_access is not None:
        return build_pdf_source_url(issue, _extract_page_id(raw_page), pdf_access)
    return _extract_source_url(raw_page)


def _resolve_file_extension(
    source_url: str | None,
    pdf_access: PdfAccessInfo | None,
) -> str | None:
    if pdf_access is not None:
        return ".pdf"
    return guess_file_extension_from_url(source_url)


def _collect_source_candidates(
    value: Any, candidates: list[tuple[int, str]], *, current_key: str = ""
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _collect_source_candidates(child, candidates, current_key=str(key))
        return

    if isinstance(value, list):
        for child in value:
            _collect_source_candidates(child, candidates, current_key=current_key)
        return

    if not isinstance(value, str):
        return

    candidate = value.strip()
    if not candidate or candidate.startswith("javascript:"):
        return
    if "/viewer" in candidate and FILE_EXTENSION_RE.search(candidate) is None:
        return
    if not (
        candidate.startswith(("http://", "https://", "/"))
        or FILE_EXTENSION_RE.search(candidate)
    ):
        return

    score = _candidate_score(current_key, candidate)
    if score >= 0:
        candidates.append((score, candidate))


def _candidate_score(key: str, candidate: str) -> int:
    key_lower = key.lower()
    for index, hint in enumerate(URL_HINTS):
        if key_lower == hint:
            return 100 - index
        if key_lower.endswith(hint):
            return 80 - index

    score = 10
    if FILE_EXTENSION_RE.search(candidate):
        score += 20
    if "/files/" in candidate:
        score += 10
    return score


def _normalize_candidate_url(candidate: str) -> str:
    if candidate.startswith(("http://", "https://")):
        return candidate
    return urljoin(SITE_BASE, candidate)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None

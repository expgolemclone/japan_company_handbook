from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from scrape.magazine.client import (
    MAGAZINES_DIR,
    build_pdf_source_url,
    fetch_magazine_issue,
    fetch_pdf_access,
    issue_dir,
    request_with_retries,
    validate_magazine_issue_payload,
)
from scrape.magazine.normalize import guess_file_extension_from_url, normalize_magazine
from scrape.magazine.progress import IssueProgress
from scrape.magazine.types import (
    MagazineIssueKey,
    NormalizedMagazine,
    NormalizedPage,
    PdfAccessInfo,
)

RAW_MANIFEST_FILE = "manifest.raw.json"
NORMALIZED_MANIFEST_FILE = "manifest.normalized.json"
PROGRESS_FILE = "progress.json"
PAGES_DIR = "pages"
REQUEST_INTERVAL = 1.0

CONTENT_TYPE_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def download_issue_artifacts(
    client: httpx.Client,
    issue: MagazineIssueKey,
    out_dir: Path = MAGAZINES_DIR,
    *,
    raw_issue: dict[str, object] | None = None,
    request_interval: float = REQUEST_INTERVAL,
) -> NormalizedMagazine:
    issue_path = issue_dir(out_dir, issue)
    issue_path.mkdir(parents=True, exist_ok=True)

    payload = raw_issue or fetch_magazine_issue(client, issue.calendar, issue.series)
    validate_magazine_issue_payload(payload, endpoint=str(issue))
    _write_json(issue_path / RAW_MANIFEST_FILE, payload)

    normalized = normalize_magazine(payload, issue)
    pdf_access = _resolve_pdf_access(client, normalized)
    if pdf_access is not None:
        normalized = normalize_magazine(payload, issue, pdf_access=pdf_access)

    _write_json(issue_path / NORMALIZED_MANIFEST_FILE, normalized)

    progress = IssueProgress(issue_path / PROGRESS_FILE)
    download_issue_pages(
        client,
        normalized,
        progress,
        issue_path,
        pdf_access=pdf_access,
        request_interval=request_interval,
    )
    progress.finalize()
    return normalized


def download_issue_pages(
    client: httpx.Client,
    manifest: NormalizedMagazine,
    progress: IssueProgress,
    issue_path: Path,
    *,
    pdf_access: PdfAccessInfo | None = None,
    request_interval: float = REQUEST_INTERVAL,
) -> list[Path]:
    pages_dir = issue_path / PAGES_DIR
    pages_dir.mkdir(parents=True, exist_ok=True)

    pages = manifest["pages"]
    issue = _manifest_issue(manifest)
    progress.register_expected_pages([page["page"] for page in pages])
    saved_paths: list[Path] = []

    for index, page in enumerate(pages):
        page_id = page["page"]
        if progress.is_downloaded(page_id):
            filename = progress.completed_filename(page_id)
            if filename is not None and (pages_dir / filename).exists():
                saved_paths.append(pages_dir / filename)
                continue

        try:
            saved = download_page(
                client,
                page,
                pages_dir,
                issue=issue,
                pdf_access=pdf_access,
            )
        except (httpx.HTTPStatusError, httpx.TransportError, ValueError) as exc:
            progress.mark_failed(page_id, str(exc))
            raise

        progress.mark_downloaded(page_id, saved.name)
        saved_paths.append(saved)

        if request_interval > 0 and index < len(pages) - 1:
            time.sleep(request_interval)

    progress.finalize()
    return saved_paths


def download_page(
    client: httpx.Client,
    page: NormalizedPage,
    dest_dir: Path,
    *,
    issue: MagazineIssueKey | None = None,
    pdf_access: PdfAccessInfo | None = None,
) -> Path:
    source_url = page["source_url"]
    page_id = page["page"]
    current_access = pdf_access

    for attempt in range(2):
        if source_url is None and current_access is not None and issue is not None:
            source_url = build_pdf_source_url(issue, page_id, current_access)

        if source_url is None:
            raise ValueError(f"{page_id}: ダウンロードURLを解決できません")

        response = request_with_retries(client, "GET", source_url)  # noqa: scrape-interval
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type in {"text/html", "application/json"}:
            if (
                attempt == 0
                and current_access is not None
                and issue is not None
                and _looks_like_viewer_pdf_url(source_url)
            ):
                current_access = fetch_pdf_access(client)
                source_url = build_pdf_source_url(issue, page_id, current_access)
                page["source_url"] = source_url
                page["file_ext"] = ".pdf"
                continue

            raise ValueError(
                f"{page_id}: ページ本体ではないレスポンスです ({response.headers.get('content-type')})"
            )

        extension = _resolve_extension(source_url, content_type)
        if extension is None:
            raise ValueError(f"{page_id}: 拡張子を判定できません")

        dest = dest_dir / f"{page_id}{extension}"
        dest.write_bytes(response.content)
        return dest

    raise ValueError(f"{page_id}: ページ本体ではないレスポンスです")


def _resolve_extension(source_url: str, content_type: str) -> str | None:
    if content_type in CONTENT_TYPE_TO_EXTENSION:
        return CONTENT_TYPE_TO_EXTENSION[content_type]
    return guess_file_extension_from_url(source_url)


def _resolve_pdf_access(
    client: httpx.Client,
    manifest: NormalizedMagazine,
) -> PdfAccessInfo | None:
    if all(page["source_url"] is not None for page in manifest["pages"]):
        return None
    return fetch_pdf_access(client)


def _manifest_issue(manifest: NormalizedMagazine) -> MagazineIssueKey:
    issue = manifest["issue"]
    return MagazineIssueKey(
        calendar=str(issue["calendar"]),
        series=str(issue["series"]),
    )


def _looks_like_viewer_pdf_url(url: str) -> bool:
    return "/files/shimen/" in url and ".pdf?" in url


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

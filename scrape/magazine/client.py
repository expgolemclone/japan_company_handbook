from __future__ import annotations

import base64
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from scrape.auth import DEFAULT_CHROME_COOKIES, load_toyokeizai_cookies
from scrape.magazine.types import MagazineIssueKey, PdfAccessInfo

SITE_BASE = "https://shikiho.toyokeizai.net"
API_BASE = "https://api-shikiho.toyokeizai.net"
DATA_DIR = Path("data")
MAGAZINES_DIR = DATA_DIR / "magazines"
ISSUES_RAW_FILE = MAGAZINES_DIR / "issues.raw.json"
EXPECTED_ISSUES_FILE = MAGAZINES_DIR / "issues.expected.json"
BATCH_PROGRESS_FILE = MAGAZINES_DIR / "batch_progress.json"
BATCH_SUMMARY_FILE = MAGAZINES_DIR / "batch_summary.json"
VERIFY_REPORT_FILE = MAGAZINES_DIR / "verify_report.json"
FACT_CHECK_REPORT_FILE = MAGAZINES_DIR / "fact_check_report.json"
AUTH_DIAGNOSTICS_FILE = MAGAZINES_DIR / "auth_diagnostics.json"

DEFAULT_HEADERS = {
    "Referer": (
        "https://shikiho.toyokeizai.net/viewer?calendar=2026&series=2&page=0000page"
    ),
    "Origin": SITE_BASE,
    "User-Agent": "Mozilla/5.0",
}
PERMISSION_STATUS_CODES = {"3202", "401", "403"}
SUCCESS_STATUS_CODES = {"1000", "2000"}
PDF_TIER_RE = re.compile(r"/files/shimen/(basic|premium)/", re.IGNORECASE)
REQUEST_RETRIES = 5
RETRY_DELAY_SECONDS = 1.0  # noqa: scrape-interval


class MagazineApiError(RuntimeError):
    pass


class MagazinePermissionError(MagazineApiError):
    pass


class MagazinePayloadShapeError(MagazineApiError):
    pass


def issue_dir(out_dir: Path, issue: MagazineIssueKey) -> Path:
    return out_dir / str(issue)


def build_magazine_http_client(
    cookie_file: Path = DEFAULT_CHROME_COOKIES,
    *,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    cookies = _load_cookie_jar(cookie_file)

    return httpx.Client(
        base_url=API_BASE,
        headers=DEFAULT_HEADERS,
        cookies=cookies,
        follow_redirects=True,
        timeout=30.0,
        transport=transport,
    )


def _load_cookie_jar(cookie_file: Path) -> httpx.Cookies:
    if cookie_file.suffix == ".json":
        raw = json.loads(cookie_file.read_text(encoding="utf-8"))
        jar = httpx.Cookies()
        for cookie in raw:
            domain = str(cookie.get("domain", "")).lstrip(".")
            if domain:
                jar.set(cookie["name"], cookie["value"], domain=domain)
            else:
                jar.set(cookie["name"], cookie["value"])
        return jar

    return load_toyokeizai_cookies(cookie_file)


def fetch_issue_list(client: httpx.Client) -> dict[str, object]:
    payload = _request_json(client, "/files/v1/files/magazines/list")
    validate_payload_status(payload, endpoint="issue list")
    validate_issue_list_payload(payload, endpoint="issue list")
    return payload


def fetch_magazine_issue(
    client: httpx.Client, calendar: str, series: str
) -> dict[str, object]:
    payload = _request_json(client, f"/files/v1/files/magazines/{calendar}/{series}")
    validate_payload_status(payload, endpoint=f"{calendar}_{series}")
    validate_magazine_issue_payload(payload, endpoint=f"{calendar}_{series}")
    return payload


def fetch_stock_page_info(
    client: httpx.Client, page_or_code: str
) -> dict[str, object]:
    payload = _request_json(client, f"/files/v1/files/magazines/{page_or_code}/list")
    validate_payload_status(
        payload,
        endpoint=f"stock page {page_or_code}",
        allowed_status_codes=SUCCESS_STATUS_CODES | {"3001"},
    )
    return payload


def validate_issue_list_payload(
    payload: dict[str, object], *, endpoint: str = "issue list"
) -> None:
    magazines = payload.get("magazines")
    if not isinstance(magazines, list):
        raise MagazinePayloadShapeError(
            f"{endpoint}: magazines 配列がありません"
        )


def validate_magazine_issue_payload(
    payload: dict[str, object], *, endpoint: str
) -> None:
    magazine = payload.get("magazine")
    if not isinstance(magazine, dict) or not magazine:
        raise MagazinePayloadShapeError(
            f"{endpoint}: magazine オブジェクトが空です"
        )

    missing_keys = [
        key
        for key in ("calendar", "series", "pages")
        if key not in magazine
    ]
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise MagazinePayloadShapeError(
            f"{endpoint}: magazine に必須キーがありません ({missing})"
        )

    pages = magazine.get("pages")
    if not isinstance(pages, list):
        raise MagazinePayloadShapeError(
            f"{endpoint}: pages 配列がありません"
        )
    if not pages:
        raise MagazinePayloadShapeError(
            f"{endpoint}: pages 配列が空です"
        )


def fetch_pdf_access(
    client: httpx.Client, *, stock_codes: list[str] | None = None
) -> PdfAccessInfo:
    payload = _request_json(
        client,
        "/headers/v1/headers",
        method="POST",
        json_body={"stock_codes": stock_codes or []},
    )
    validate_payload_status(payload, endpoint="headers")

    pdf_hash_val = payload.get("pdf_hash", "")
    pdf_hash = str(pdf_hash_val).strip() if pdf_hash_val is not None else ""
    if not pdf_hash:
        raise MagazineApiError("headers: pdf_hash がありません")

    return PdfAccessInfo(
        pdf_hash=pdf_hash,
        tier=_infer_pdf_tier(pdf_hash),
    )


def validate_payload_status(
    payload: dict[str, object],
    *,
    endpoint: str,
    allowed_status_codes: set[str] | None = None,
) -> None:
    _raise_for_payload_status(
        payload,
        endpoint=endpoint,
        allowed_status_codes=allowed_status_codes,
    )


def build_pdf_source_url(
    issue: MagazineIssueKey,
    pdf_name: str,
    access: PdfAccessInfo,
) -> str:
    return (
        f"{SITE_BASE}/files/shimen/{access['tier']}/"
        f"{issue.calendar}/{issue.series}/{pdf_name}.pdf?{access['pdf_hash']}"
    )


def extract_issue_refs(
    payload: dict[str, object], *, start_calendar: int = 1936
) -> list[MagazineIssueKey]:
    raw_magazines = payload.get("magazines")
    if not isinstance(raw_magazines, list):
        raise ValueError("号一覧レスポンスに magazines がありません")

    issues: list[MagazineIssueKey] = []
    seen: set[str] = set()
    for raw_issue in raw_magazines:
        if not isinstance(raw_issue, dict):
            continue

        calendar = raw_issue.get("calendar")
        series = raw_issue.get("series")
        if calendar is None or series is None:
            continue

        issue = MagazineIssueKey(str(calendar), str(series))
        if int(issue.calendar) < start_calendar:
            continue
        if str(issue) in seen:
            continue

        seen.add(str(issue))
        issues.append(issue)

    issues.sort(key=lambda issue: (int(issue.calendar), int(issue.series)))
    return issues


def save_issue_list_cache(
    payload: dict[str, object], path: Path = ISSUES_RAW_FILE
) -> None:
    _write_json(path, payload)


def save_expected_issues(
    issues: list[MagazineIssueKey], path: Path = EXPECTED_ISSUES_FILE
) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "issues": [issue.to_dict() for issue in issues],
    }
    _write_json(path, payload)


def load_expected_issues(path: Path = EXPECTED_ISSUES_FILE) -> list[MagazineIssueKey]:
    if not path.exists():
        raise FileNotFoundError(f"期待号一覧が見つかりません: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    issue_dicts = raw.get("issues")
    if not isinstance(issue_dicts, list):
        raise ValueError(f"期待号一覧の形式が不正です: {path}")

    issues: list[MagazineIssueKey] = []
    for issue_dict in issue_dicts:
        if not isinstance(issue_dict, dict):
            raise ValueError(f"期待号一覧の形式が不正です: {path}")
        issues.append(
            MagazineIssueKey(
                calendar=str(issue_dict["calendar"]),
                series=str(issue_dict["series"]),
            )
        )
    return issues


def _request_json(
    client: httpx.Client,
    url: str,
    *,
    method: str = "GET",
    json_body: dict[str, object] | None = None,
) -> dict[str, object]:
    response = request_with_retries(
        client,
        method,
        url,
        json_body=json_body,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise MagazineApiError(
            f"JSONではないレスポンスです: {url} ({response.headers.get('content-type')})"
        )

    payload = response.json()
    if not isinstance(payload, dict):
        raise MagazineApiError(f"JSONオブジェクトではないレスポンスです: {url}")
    return payload


def _raise_for_payload_status(
    payload: dict[str, object],
    *,
    endpoint: str,
    allowed_status_codes: set[str] | None = None,
) -> None:
    status = payload.get("status")
    if not isinstance(status, dict):
        return

    code = str(status.get("code", ""))
    message = str(status.get("message", ""))
    allowed = allowed_status_codes or SUCCESS_STATUS_CODES

    if not code or code in allowed or code.startswith("2"):
        return

    if code in PERMISSION_STATUS_CODES or "permission" in message.lower():
        raise MagazinePermissionError(
            f"{endpoint}: 権限エラーです ({code}: {message})"
        )

    raise MagazineApiError(f"{endpoint}: APIエラーです ({code}: {message})")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _infer_pdf_tier(pdf_hash: str) -> str:
    policy = _extract_cloudfront_policy(pdf_hash)
    if policy is not None:
        decoded_policy = _decode_cloudfront_policy(policy)
        match = PDF_TIER_RE.search(decoded_policy)
        if match:
            return match.group(1).lower()

    match = PDF_TIER_RE.search(pdf_hash)
    if match:
        return match.group(1).lower()
    raise MagazineApiError("headers: pdf_hash から誌面権限を判定できません")


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json_body: dict[str, object] | None = None,
    retries: int = REQUEST_RETRIES,
    retry_delay: float = RETRY_DELAY_SECONDS,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = client.request(method, url, json=json_body)  # noqa: scrape-interval
        except httpx.TransportError as exc:
            last_error = exc
            if attempt + 1 == retries:
                raise
            time.sleep(retry_delay * (attempt + 1))  # noqa: scrape-interval
            continue

        if response.status_code == 429 or response.status_code >= 500:
            last_error = httpx.HTTPStatusError(
                f"retryable status: {response.status_code}",
                request=response.request,
                response=response,
            )
            if attempt + 1 == retries:
                return response
            time.sleep(retry_delay * (attempt + 1))  # noqa: scrape-interval
            continue

        return response

    if last_error is not None:
        raise last_error
    raise RuntimeError("request retry loop が不正終了しました")


def _extract_cloudfront_policy(pdf_hash: str) -> str | None:
    parsed = parse_qs(pdf_hash, keep_blank_values=True)
    values = parsed.get("Policy")
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _decode_cloudfront_policy(policy: str) -> str:
    padding = "=" * (-len(policy) % 4)
    decoded = base64.urlsafe_b64decode(policy + padding)
    return decoded.decode("utf-8", "ignore")

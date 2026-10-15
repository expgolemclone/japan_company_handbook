from __future__ import annotations

import logging
from typing import NotRequired, TypedDict

import httpx

from scrape.auth import load_toyokeizai_cookies

logger = logging.getLogger(__name__)

SITE_BASE = "https://shikiho.toyokeizai.net"
API_BASE = "https://api-shikiho.toyokeizai.net"
AUTH_LEVEL_BASIC = 3
AUTH_LEVEL_PREMIUM = 5


class Issue(TypedDict):
    calendar: str
    series: str
    title: str
    sub_title: str | None
    pub_date: str | None


class MagazinePage(TypedDict):
    type: str
    page: str
    stock_code: NotRequired[str]


class Magazine(TypedDict):
    calendar: str
    series: str
    title: str
    subTitle: str | None
    pubDate: str | None
    pages: list[MagazinePage]


class PdfAccess(TypedDict):
    auth_level: int
    pdf_hash: str
    pdf_path: str


def build_api_client() -> httpx.Client:
    """四季報API用の認証済みhttpx.Clientを構築する。"""
    return httpx.Client(
        base_url=API_BASE,
        cookies=load_toyokeizai_cookies(),
        follow_redirects=True,
        timeout=30.0,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": SITE_BASE,
            "Referer": f"{SITE_BASE}/archive",
        },
    )


def build_http_client() -> httpx.Client:
    """PDFダウンロード用のhttpx.Clientを構築する。"""
    return httpx.Client(
        follow_redirects=True,
        timeout=30.0,
    )


def resolve_pdf_path(auth_level: int) -> str:
    """会員種別からPDF配信パスを決める。"""
    if auth_level >= AUTH_LEVEL_PREMIUM:
        return "/files/shimen/premium"
    if auth_level == AUTH_LEVEL_BASIC:
        return "/files/shimen/basic"
    raise PermissionError(f"誌面PDFを取得できる会員種別ではありません: auth_level={auth_level}")


def fetch_pdf_access(client: httpx.Client) -> PdfAccess:
    """PDFダウンロードに必要な認可情報を取得する。"""
    sso = client.get("/sso/v1/sso/check")
    sso.raise_for_status()
    account = sso.json()

    headers = client.post("/headers/v1/headers/", json={"stock_codes": []})
    headers.raise_for_status()
    header_data = headers.json()

    auth_level = int(account["auth_level"])
    return PdfAccess(
        auth_level=auth_level,
        pdf_hash=header_data["pdf_hash"],
        pdf_path=resolve_pdf_path(auth_level),
    )


def fetch_issues(client: httpx.Client, *, from_year: int = 1936) -> list[Issue]:
    """利用可能な全号一覧を取得する。"""
    resp = client.get("/files/v1/files/magazines/list")
    resp.raise_for_status()
    magazines = resp.json()["magazines"]

    issues = [
        Issue(
            calendar=magazine["calendar"],
            series=magazine["series"],
            title=magazine["title"],
            sub_title=magazine.get("subTitle"),
            pub_date=magazine.get("pubDate"),
        )
        for magazine in magazines
        if int(magazine["calendar"]) >= from_year
    ]
    issues.sort(key=lambda issue: (int(issue["calendar"]), int(issue["series"])))
    return issues


def fetch_magazine(client: httpx.Client, year: str, series: str) -> Magazine:
    """指定号の誌面メタデータを取得する。"""
    resp = client.get(f"/files/v1/files/magazines/{year}/{series}")
    resp.raise_for_status()
    payload = resp.json()
    if "magazine" not in payload:
        status = payload.get("status", {})
        raise ValueError(f"{year}_{series}: 号情報を取得できません ({status.get('message', 'unknown error')})")
    return payload["magazine"]


def extract_page_ids(magazine: Magazine) -> list[str]:
    """誌面ページID一覧を出現順でユニーク化して返す。"""
    seen: set[str] = set()
    pages: list[str] = []
    for page in magazine["pages"]:
        page_id = page["page"]
        if page_id in seen:
            continue
        seen.add(page_id)
        pages.append(page_id)
    return pages


def build_pdf_url(
    year: str,
    series: str,
    page_id: str,
    access: PdfAccess,
) -> str:
    """認証付きPDF URLを構築する。"""
    return f"{SITE_BASE}{access['pdf_path']}/{year}/{series}/{page_id}.pdf?{access['pdf_hash']}"

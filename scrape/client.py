from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypedDict

import httpx

logger = logging.getLogger(__name__)

SITE_BASE = "https://shikiho.toyokeizai.net"
DATA_DIR = Path("data")
SIGNED_PARAMS_FILE = DATA_DIR / "signed_params.json"


class Issue(TypedDict):
    calendar: str
    series: str
    title: str
    pub_date: str


class SignedParams(TypedDict):
    Policy: str
    Signature: str
    Key_Pair_Id: str


# Playwright MCPで取得済みの直近4号
ISSUES: list[Issue] = [
    Issue(calendar="2025", series="3", title="夏号", pub_date="20250618"),
    Issue(calendar="2025", series="4", title="秋号", pub_date="20250918"),
    Issue(calendar="2026", series="1", title="新春号", pub_date="20251217"),
    Issue(calendar="2026", series="2", title="春号", pub_date="20260318"),
]


def load_stock_codes(year: str, series: str, *, data_dir: Path = DATA_DIR) -> list[str]:
    """保存済み銘柄コード一覧を読み込む。"""
    path = data_dir / f"stock_codes_{year}_{series}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"銘柄コードファイルが見つかりません: {path}\n"
            "Playwright MCPで銘柄コードを抽出し、保存してください。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_signed_params(path: Path = SIGNED_PARAMS_FILE) -> SignedParams:
    """保存済みCloudFront署名パラメータを読み込む。"""
    if not path.exists():
        raise FileNotFoundError(
            f"署名パラメータファイルが見つかりません: {path}\n"
            "Playwright MCPで署名パラメータを抽出し、data/signed_params.json に保存してください。"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SignedParams(
        Policy=raw["Policy"],
        Signature=raw["Signature"],
        Key_Pair_Id=raw["Key-Pair-Id"],
    )


def build_pdf_url(
    year: str, series: str, code: str, params: SignedParams
) -> str:
    """署名付きPDF URLを構築する。"""
    return (
        f"{SITE_BASE}/files/shimen/basic/{year}/{series}/{code}.pdf"
        f"?Policy={params['Policy']}"
        f"&Signature={params['Signature']}"
        f"&Key-Pair-Id={params['Key_Pair_Id']}"
    )


def build_http_client() -> httpx.Client:
    """PDFダウンロード用のhttpx.Clientを構築する。"""
    return httpx.Client(
        follow_redirects=True,
        timeout=30.0,
    )

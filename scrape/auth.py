from __future__ import annotations

import json
from pathlib import Path

COOKIES_FILE = Path("data/cookies.json")


def load_cookies(path: Path = COOKIES_FILE) -> list[dict[str, str]]:
    """保存済みCookieファイルを読み込む。"""
    if not path.exists():
        raise FileNotFoundError(
            f"Cookieファイルが見つかりません: {path}\n"
            "Playwright MCPでログイン後、data/cookies.json に保存してください。"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"name": c["name"], "value": c["value"], "domain": c.get("domain", "")}
        for c in raw
    ]

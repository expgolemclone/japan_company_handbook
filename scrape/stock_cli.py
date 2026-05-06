from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DEFAULT_CODES_PATH = DATA_DIR / "stock_codes_2026_2.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION = "四季報の銘柄業績予想を取得してSQLiteへ保存する"


def _find_project_venv_python(project_root: Path = PROJECT_ROOT) -> Path | None:
    candidates = (
        project_root / ".venv/bin/python3",
        project_root / ".venv/bin/python",
        project_root / ".venv/Scripts/python.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _missing_httpx_message() -> str:
    return (
        "httpx が見つかりません。`uv sync` で依存をインストールしてから、"
        "`uv run shikiho stock fetch` を実行してください。"
    )


def _is_running_inside_project_venv(venv_python: Path) -> bool:
    return Path(sys.prefix).resolve() == venv_python.parent.parent.resolve()


def _normalized_shikiho_args(argv: list[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:2] == ["stock", "fetch"]:
        return args
    return ["stock", "fetch", *args]


def _ensure_httpx_runtime() -> object:
    try:
        return importlib.import_module("httpx")
    except ModuleNotFoundError as exc:
        if exc.name != "httpx":
            raise
        venv_python = _find_project_venv_python()
        if venv_python is not None and not _is_running_inside_project_venv(venv_python):
            argv = [str(venv_python), "-m", "scrape.shikiho_cli", *_normalized_shikiho_args()]
            os.execv(
                str(venv_python),
                argv,
            )
        raise SystemExit(_missing_httpx_message()) from exc


httpx = _ensure_httpx_runtime()

from scrape.auth import refresh_cookies_via_chrome
from scrape.client import build_api_client
from scrape.downloader import REQUEST_INTERVAL
from scrape.stock import fetch_stock_latest
from scrape.stock_db import init_db, save_performance


def build_parser(
    *,
    prog: str | None = None,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        add_help=add_help,
    )


def _load_stock_codes(path: Path = DEFAULT_CODES_PATH) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(_args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    codes = _load_stock_codes()
    logger.info("対象銘柄数: %d", len(codes))

    init_db()

    api_client = build_api_client()
    try:
        try:
            access_resp = api_client.get("/sso/v1/sso/check")
            access_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            logger.warning("認証に失敗しました。ChromeでCookie更新を試みます。")
            if not refresh_cookies_via_chrome():
                logger.error("Cookie更新に失敗しました。")
                raise
            api_client.close()
            api_client = build_api_client()

        success = 0
        skipped = 0

        for i, code in enumerate(codes):
            try:
                perf = fetch_stock_latest(api_client, code)
            except httpx.HTTPStatusError as exc:
                logger.warning("%s: HTTP %s — スキップ", code, exc.response.status_code)
                skipped += 1
                if i < len(codes) - 1:
                    time.sleep(REQUEST_INTERVAL)
                continue
            except httpx.TransportError as exc:
                logger.warning("%s: 転送エラー (%s) — スキップ", code, exc)
                skipped += 1
                if i < len(codes) - 1:
                    time.sleep(REQUEST_INTERVAL)
                continue

            if perf is None:
                skipped += 1
                if i < len(codes) - 1:
                    time.sleep(REQUEST_INTERVAL)
                continue

            save_performance(perf)
            success += 1

            if i % 100 == 0:
                logger.info(
                    "進捗: %d / %d (成功: %d, スキップ: %d)",
                    i + 1,
                    len(codes),
                    success,
                    skipped,
                )

            if i < len(codes) - 1:
                time.sleep(REQUEST_INTERVAL)

        logger.info("完了 — 成功: %d, スキップ: %d / %d", success, skipped, len(codes))
        return 0
    finally:
        api_client.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    from scrape.legacy_cli import main_stock_module

    raise SystemExit(main_stock_module())

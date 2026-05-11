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
DEFAULT_RAW_JSON_DIR = DATA_DIR / "stock_latest_json"
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

from scrape.auth import is_http_auth_error, refresh_cookie_source
from scrape.client import build_api_client
from scrape.downloader import REQUEST_INTERVAL
from scrape.stock import fetch_stock_latest_json, parse_stock_latest_payload
from scrape.stock_db import existing_codes, existing_shareholder_codes, init_db, save_performance, save_shareholders


def build_parser(
    *,
    prog: str | None = None,
    add_help: bool = True,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        add_help=add_help,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="取得済み銘柄も再取得する",
    )
    parser.add_argument(
        "--code",
        action="append",
        dest="codes",
        metavar="STOCK_CODE",
        help="指定した銘柄コードだけ取得する。複数指定可",
    )
    parser.add_argument(
        "--raw-json-dir",
        type=Path,
        default=DEFAULT_RAW_JSON_DIR,
        help="銘柄APIの生JSON保存先ディレクトリ",
    )
    return parser


def _load_stock_codes(path: Path = DEFAULT_CODES_PATH) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_requested_codes(codes: list[str] | None) -> list[str] | None:
    if codes is None:
        return None
    normalized = [code.strip() for code in codes if code.strip()]
    if not normalized:
        raise SystemExit("--code には空でない銘柄コードを指定してください。")
    return normalized


def run(_args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    requested_codes = _normalize_requested_codes(getattr(_args, "codes", None))
    codes = requested_codes if requested_codes is not None else _load_stock_codes()
    logger.info("対象銘柄数: %d", len(codes))

    init_db()

    if not _args.force:
        existing_forecasts = existing_codes()
        existing_sh = existing_shareholder_codes()
        existing_raw_json = _existing_raw_json_codes(codes, _args.raw_json_dir)
        existing = existing_forecasts & existing_sh & existing_raw_json
        before = len(codes)
        codes = [c for c in codes if c not in existing]
        if len(codes) < before:
            logger.info(
                "取得済みスキップ: %d, 残り: %d (--force で全件再取得)",
                before - len(codes),
                len(codes),
            )
    else:
        target_label = "指定銘柄" if requested_codes is not None else "全件"
        logger.info("--force: %s再取得します", target_label)

    api_client = build_api_client()
    try:
        try:
            _check_api_auth(api_client)
        except httpx.HTTPStatusError as exc:
            if not is_http_auth_error(exc):
                raise
            refreshed_client = _refresh_api_client(api_client)
            if refreshed_client is None:
                logger.error("Cookie更新に失敗しました。")
                raise
            api_client = refreshed_client
            _check_api_auth(api_client)

        success = 0
        skipped = 0

        for i, code in enumerate(codes):
            auth_retry_used = False
            skip_current_code = False
            perf = None
            try:
                while True:
                    try:
                        latest = fetch_stock_latest_json(api_client, code)
                        _save_stock_latest_json(_args.raw_json_dir, code, latest.content)
                        perf = parse_stock_latest_payload(code, latest.payload)
                    except httpx.HTTPStatusError as exc:
                        if not is_http_auth_error(exc) or auth_retry_used:
                            raise
                        refreshed_client = _refresh_api_client(api_client)
                        if refreshed_client is None:
                            logger.warning("%s: Cookie更新に失敗したためスキップ", code)
                            skip_current_code = True
                            break
                        api_client = refreshed_client
                        auth_retry_used = True
                        logger.info("%s: 認証を再確認したため再試行します", code)
                        continue
                    break
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

            if skip_current_code or perf is None:
                skipped += 1
                if i < len(codes) - 1:
                    time.sleep(REQUEST_INTERVAL)
                continue

            save_performance(perf)
            save_shareholders(perf)
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


def _check_api_auth(api_client) -> None:
    access_resp = api_client.get("/sso/v1/sso/check")
    access_resp.raise_for_status()


def _existing_raw_json_codes(codes: list[str], raw_json_dir: Path) -> set[str]:
    return {code for code in codes if _raw_json_path(raw_json_dir, code).exists()}


def _save_stock_latest_json(raw_json_dir: Path, code: str, content: bytes) -> Path:
    path = _raw_json_path(raw_json_dir, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _raw_json_path(raw_json_dir: Path, code: str) -> Path:
    return raw_json_dir / f"{code}.json"


def _refresh_api_client(api_client):
    logger.warning("認証に失敗しました。ChromeでCookie更新を試みます。")
    if not refresh_cookie_source():
        return None
    api_client.close()
    return build_api_client()


if __name__ == "__main__":
    from scrape.legacy_cli import main_stock_module

    raise SystemExit(main_stock_module())

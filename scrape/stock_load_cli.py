from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from scrape.stock_db import (
    existing_codes,
    existing_shareholder_codes,
    init_db,
    save_performance,
    save_shareholders,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DEFAULT_RAW_JSON_DIR = DATA_DIR / "stock_latest_json"
DESCRIPTION = "ローカルに保存した銘柄JSONからSQLiteへ読み込む"


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
        help="SQLite保存済み銘柄も再処理する",
    )
    parser.add_argument(
        "--code",
        action="append",
        dest="codes",
        metavar="STOCK_CODE",
        help="指定した銘柄コードだけ処理する。複数指定可",
    )
    parser.add_argument(
        "--raw-json-dir",
        type=Path,
        default=DEFAULT_RAW_JSON_DIR,
        help="銘柄APIの生JSON保存先ディレクトリ",
    )
    return parser


def _collect_json_codes(raw_json_dir: Path) -> list[str]:
    if not raw_json_dir.is_dir():
        return []
    return sorted(p.stem for p in raw_json_dir.glob("*.json"))


def _normalize_requested_codes(codes: list[str] | None) -> list[str] | None:
    if codes is None:
        return None
    normalized = [code.strip() for code in codes if code.strip()]
    if not normalized:
        raise SystemExit("--code には空でない銘柄コードを指定してください。")
    return normalized


def run(args: argparse.Namespace) -> int:
    from scrape.stock import parse_stock_latest_payload

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    requested_codes = _normalize_requested_codes(getattr(args, "codes", None))
    if requested_codes is not None:
        codes = requested_codes
    else:
        codes = _collect_json_codes(args.raw_json_dir)

    if not codes:
        logger.info("処理対象の銘柄がありません")
        return 0

    logger.info("対象銘柄数: %d", len(codes))
    init_db()

    if not args.force:
        existing_fc = existing_codes()
        existing_sh = existing_shareholder_codes()
        existing = existing_fc & existing_sh
        before = len(codes)
        codes = [c for c in codes if c not in existing]
        if len(codes) < before:
            logger.info(
                "保存済みスキップ: %d, 残り: %d (--force で全件再処理)",
                before - len(codes),
                len(codes),
            )
    else:
        target_label = "指定銘柄" if requested_codes is not None else "全件"
        logger.info("--force: %sを再処理します", target_label)

    if not codes:
        logger.info("処理すべき銘柄がありません")
        return 0

    success = 0
    skipped = 0

    for i, code in enumerate(codes):
        json_path = args.raw_json_dir / f"{code}.json"
        if not json_path.exists():
            logger.warning("%s: JSONファイルがありません — スキップ", code)
            skipped += 1
            continue

        try:
            payload = json.loads(json_path.read_bytes())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("%s: JSON読み込みエラー (%s) — スキップ", code, exc)
            skipped += 1
            continue

        if not isinstance(payload, dict):
            logger.warning("%s: JSONオブジェクトではありません — スキップ", code)
            skipped += 1
            continue

        perf = parse_stock_latest_payload(code, payload)
        if perf is None:
            skipped += 1
            continue

        save_performance(perf)
        save_shareholders(perf)
        success += 1

        if (i + 1) % 100 == 0:
            logger.info(
                "進捗: %d / %d (成功: %d, スキップ: %d)",
                i + 1,
                len(codes),
                success,
                skipped,
            )

    logger.info("完了 — 成功: %d, スキップ: %d / %d", success, skipped, len(codes))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

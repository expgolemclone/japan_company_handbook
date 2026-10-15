from __future__ import annotations

from pathlib import Path
import argparse
import logging
import time

from pdfops.invert import ensure_required_binaries, invert_pdf, plan_inversion_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDFを反転して別ディレクトリへ出力する")
    parser.add_argument("source_root", type=Path, help="入力PDFの起点ディレクトリ")
    parser.add_argument("output_root", type=Path, help="反転版PDFの出力先ディレクトリ")
    parser.add_argument("--dpi", type=int, default=144, help="ラスタライズ時の解像度")
    parser.add_argument("--overwrite", action="store_true", help="既存の出力PDFを上書きする")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="各PDF変換の間に待つ秒数",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()

    ensure_required_binaries()
    jobs = plan_inversion_jobs(source_root, output_root, overwrite=args.overwrite)

    logger.info("source_root=%s", source_root)
    logger.info("output_root=%s", output_root)
    logger.info("jobs=%d", len(jobs))

    for index, job in enumerate(jobs, start=1):
        logger.info("[%d/%d] %s", index, len(jobs), job.source.relative_to(source_root))
        invert_pdf(job.source, job.destination, dpi=args.dpi)
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    logger.info("完了")


if __name__ == "__main__":
    main()

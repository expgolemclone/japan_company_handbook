from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class InversionJob:
    source: Path
    destination: Path


def collect_pdf_paths(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*.pdf") if path.is_file())


def build_output_path(source_path: Path, source_root: Path, output_root: Path) -> Path:
    relative_path = source_path.relative_to(source_root)
    return output_root / relative_path


def plan_inversion_jobs(
    source_root: Path,
    output_root: Path,
    *,
    overwrite: bool = False,
) -> list[InversionJob]:
    jobs: list[InversionJob] = []
    for source_path in collect_pdf_paths(source_root):
        destination = build_output_path(source_path, source_root, output_root)
        if not overwrite and destination.exists():
            continue
        jobs.append(InversionJob(source=source_path, destination=destination))
    return jobs


def _render_page_images(source_path: Path, render_root: Path, dpi: int) -> None:
    subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-r",
            str(dpi),
            str(source_path),
            str(render_root / "page"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _collect_rendered_pages(render_root: Path) -> list[Path]:
    pages = sorted(render_root.glob("page-*.png"))
    if not pages:
        raise FileNotFoundError(f"Rendered pages were not created in {render_root}")
    return pages


def _write_inverted_pdf(page_paths: list[Path], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "magick",
            *[str(page_path) for page_path in page_paths],
            "-negate",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _invert_pdf_with_ghostscript(source_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gs",
            "-q",
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            "-sColorConversionStrategy=RGB",
            "-dProcessColorModel=/DeviceRGB",
            f"-sOutputFile={destination}",
            "-c",
            "{1 exch sub} settransfer",
            "-f",
            str(source_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def invert_pdf(source_path: Path, destination: Path, *, dpi: int = 144) -> None:
    if shutil.which("gs") is not None:
        _invert_pdf_with_ghostscript(source_path, destination)
        return

    with tempfile.TemporaryDirectory(prefix="invert-pdf-") as temp_dir_name:
        render_root = Path(temp_dir_name)
        _render_page_images(source_path, render_root, dpi)
        page_paths = _collect_rendered_pages(render_root)
        _write_inverted_pdf(page_paths, destination)


def ensure_required_binaries() -> None:
    if shutil.which("gs") is not None:
        return

    for binary_name in ("pdftoppm", "magick"):
        if shutil.which(binary_name) is None:
            raise FileNotFoundError(f"Required binary is not available: {binary_name}")

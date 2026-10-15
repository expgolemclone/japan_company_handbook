from __future__ import annotations

from pathlib import Path

from pdfops.invert import InversionJob, build_output_path, collect_pdf_paths, plan_inversion_jobs


class TestCollectPdfPaths:
    def test_collects_only_pdf_files_in_sorted_order(self, tmp_path: Path) -> None:
        # Arrange
        (tmp_path / "b").mkdir()
        (tmp_path / "a").mkdir()
        (tmp_path / "b" / "2.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "a" / "1.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "a" / "ignore.txt").write_text("x")

        # Act
        actual = collect_pdf_paths(tmp_path)

        # Assert
        assert actual == [tmp_path / "a" / "1.pdf", tmp_path / "b" / "2.pdf"]


class TestBuildOutputPath:
    def test_preserves_relative_structure(self, tmp_path: Path) -> None:
        # Arrange
        source_root = tmp_path / "data"
        output_root = tmp_path / "derived" / "inverted_pdfs"
        source_path = source_root / "2026_1" / "3763.pdf"

        # Act
        actual = build_output_path(source_path, source_root, output_root)

        # Assert
        assert actual == output_root / "2026_1" / "3763.pdf"


class TestPlanInversionJobs:
    def test_skips_existing_outputs_by_default(self, tmp_path: Path) -> None:
        # Arrange
        source_root = tmp_path / "data"
        output_root = tmp_path / "derived" / "inverted_pdfs"
        source_dir = source_root / "2026_1"
        source_dir.mkdir(parents=True)
        existing_output_dir = output_root / "2026_1"
        existing_output_dir.mkdir(parents=True)
        source_a = source_dir / "1111.pdf"
        source_b = source_dir / "2222.pdf"
        source_a.write_bytes(b"%PDF-1.4")
        source_b.write_bytes(b"%PDF-1.4")
        (existing_output_dir / "1111.pdf").write_bytes(b"%PDF-1.4 inverted")

        # Act
        actual = plan_inversion_jobs(source_root, output_root)

        # Assert
        assert actual == [
            InversionJob(
                source=source_b,
                destination=output_root / "2026_1" / "2222.pdf",
            )
        ]

    def test_includes_existing_outputs_when_overwrite_is_enabled(self, tmp_path: Path) -> None:
        # Arrange
        source_root = tmp_path / "data"
        output_root = tmp_path / "derived" / "inverted_pdfs"
        source_dir = source_root / "2026_1"
        source_dir.mkdir(parents=True)
        source_path = source_dir / "1111.pdf"
        source_path.write_bytes(b"%PDF-1.4")
        existing_output_dir = output_root / "2026_1"
        existing_output_dir.mkdir(parents=True)
        (existing_output_dir / "1111.pdf").write_bytes(b"%PDF-1.4 inverted")

        # Act
        actual = plan_inversion_jobs(source_root, output_root, overwrite=True)

        # Assert
        assert actual == [
            InversionJob(
                source=source_path,
                destination=output_root / "2026_1" / "1111.pdf",
            )
        ]

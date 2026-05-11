from __future__ import annotations

import pytest

from scrape import legacy_cli, shikiho_cli


class TestShikihoCli:
    def test_top_level_help_lists_domains(self) -> None:
        help_text = shikiho_cli.build_parser().format_help()

        assert "pdf" in help_text
        assert "magazine" in help_text
        assert "stock" in help_text

    def test_magazine_issue_help_uses_leaf_parser(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            shikiho_cli.main(["magazine", "issue", "--help"])

        assert exc_info.value.code == 0
        help_text = capsys.readouterr().out
        assert "--calendar" in help_text
        assert "--series" in help_text

    def test_dispatches_pdf_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scrape import pdf_all_cli

        def fake_run(args) -> int:
            assert args.domain == "pdf"
            assert args.pdf_command == "all"
            return 7

        monkeypatch.setattr(pdf_all_cli, "run", fake_run)

        assert shikiho_cli.main(["pdf", "all"]) == 7

    def test_dispatches_magazine_verify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args) -> int:
            assert args.domain == "magazine"
            assert args.magazine_command == "verify"
            assert str(args.out_dir) == "data/magazines"
            return 11

        monkeypatch.setattr(shikiho_cli.verify_cli, "run", fake_run)

        assert shikiho_cli.main(["magazine", "verify"]) == 11

    def test_dispatches_stock_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scrape import stock_cli

        def fake_run(args) -> int:
            assert args.domain == "stock"
            assert args.stock_command == "fetch"
            assert str(args.raw_json_dir) == "data/stock_latest_json"
            return 13

        monkeypatch.setattr(stock_cli, "run", fake_run)

        assert shikiho_cli.main(["stock", "fetch"]) == 13


class TestLegacyCli:
    def test_scrape_message_points_to_shikiho(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert legacy_cli.main_scrape() == 2
        assert "uv run shikiho pdf all" in capsys.readouterr().err

    def test_stock_module_message_points_to_shikiho(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert legacy_cli.main_stock_module() == 2
        assert "uv run shikiho stock fetch" in capsys.readouterr().err

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from scrape import stock_load_cli
from scrape.stock import ForecastRow, StockPerformance


def _write_raw_json(raw_dir: Path, code: str, payload: dict[str, object]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{code}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _performance(code: str) -> StockPerformance:
    return StockPerformance(
        code=code,
        company_name="テスト会社",
        shikiho_forecasts=[
            ForecastRow(period="26.3", operating_profit=1000, net_income=800),
        ],
        company_forecast=ForecastRow(
            period="26.3",
            operating_profit=900,
            net_income=700,
        ),
        shareholders=[],
        shareholders_date=None,
    )


SAMPLE_SHIMEN_RESULTS = [
    ["【業績】", "売上高", "営業利益", "税前利益", "純利益", "1株益(円)", "1株配(円)"],
    ["◇26.3予", "50,000,000", "4,000,000", "5,200,000", "3,800,000", "179.5", "60"],
    ["◇27.3予", "52,000,000", "4,200,000", "5,400,000", "3,900,000", "180.0", "65"],
    ["会26.3予", "50,000,000", "3,800,000", "5,020,000", "3,570,000", "-", "(26.2.6)"],
]


class TestCollectJsonCodes:
    def test_lists_json_stems(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "7203.json").write_text("{}", encoding="utf-8")
        (raw_dir / "1301.json").write_text("{}", encoding="utf-8")
        (raw_dir / "readme.txt").write_text("not json", encoding="utf-8")

        codes = stock_load_cli._collect_json_codes(raw_dir)
        assert codes == ["1301", "7203"]

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert stock_load_cli._collect_json_codes(tmp_path / "missing") == []


class TestRun:
    def test_processes_all_json_files_in_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        for code in ("7203", "9999"):
            _write_raw_json(raw_dir, code, {
                "is_exist": "1",
                "company_name_j": "テスト",
                "shimen_results": SAMPLE_SHIMEN_RESULTS,
            })

        saved: list[StockPerformance] = []
        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)

        exit_code = stock_load_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert [p.code for p in saved] == ["7203", "9999"]

    def test_processes_specified_codes_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        for code in ("7203", "9999"):
            _write_raw_json(raw_dir, code, {
                "is_exist": "1",
                "company_name_j": "テスト",
                "shimen_results": SAMPLE_SHIMEN_RESULTS,
            })

        saved: list[StockPerformance] = []
        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)

        exit_code = stock_load_cli.main([
            "--code", "7203",
            "--raw-json-dir", str(raw_dir),
        ])

        assert exit_code == 0
        assert [p.code for p in saved] == ["7203"]

    def test_skips_existing_unless_force(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        _write_raw_json(raw_dir, "7203", {
            "is_exist": "1",
            "company_name_j": "テスト",
            "shimen_results": SAMPLE_SHIMEN_RESULTS,
        })

        saved: list[StockPerformance] = []
        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)

        exit_code = stock_load_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert saved == []

    def test_force_reprocesses_existing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        _write_raw_json(raw_dir, "7203", {
            "is_exist": "1",
            "company_name_j": "テスト",
            "shimen_results": SAMPLE_SHIMEN_RESULTS,
        })

        saved: list[StockPerformance] = []
        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)

        exit_code = stock_load_cli.main(["--force", "--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert [p.code for p in saved] == ["7203"]

    def test_skips_missing_json_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()

        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        caplog.set_level(logging.WARNING)

        exit_code = stock_load_cli.main([
            "--code", "9999",
            "--raw-json-dir", str(raw_dir),
        ])

        assert exit_code == 0
        assert "9999" in caplog.text
        assert "JSONファイルがありません" in caplog.text

    def test_skips_invalid_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "7203.json").write_text("not json{{{", encoding="utf-8")

        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        caplog.set_level(logging.WARNING)

        exit_code = stock_load_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert "7203" in caplog.text
        assert "JSON読み込みエラー" in caplog.text

    def test_skips_non_object_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "7203.json").write_text("[1, 2, 3]", encoding="utf-8")

        monkeypatch.setattr(stock_load_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_load_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        caplog.set_level(logging.WARNING)

        exit_code = stock_load_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert "JSONオブジェクトではありません" in caplog.text

    def test_returns_zero_when_no_codes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        raw_dir = tmp_path / "empty"
        caplog.set_level(logging.INFO)

        exit_code = stock_load_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert "処理対象の銘柄がありません" in caplog.text

    def test_exits_on_empty_code_option(self) -> None:
        with pytest.raises(SystemExit, match="空でない銘柄コード"):
            stock_load_cli.main(["--code", ""])

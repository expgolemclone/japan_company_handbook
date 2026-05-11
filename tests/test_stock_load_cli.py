from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from scrape import stock_load_cli
from scrape.stock import ForecastRow, StockPerformance
from scrape.stock import parse_dividends, parse_metrics, DividendRow


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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)

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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)

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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)

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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: {"7203"})
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)

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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)
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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)
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
        monkeypatch.setattr(stock_load_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_load_cli, "save_performance", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_load_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_load_cli, "save_metrics", lambda met: None)
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


class TestParseDividends:
    def test_parses_dividend_rows(self) -> None:
        raw = [
            ["【配当】", "配当金(円)"],
            ["22.5", "30"],
            ["23.5", "35"],
            ["24.5予", "40"],
        ]
        result = parse_dividends(raw)
        assert len(result) == 3
        assert result[0] == DividendRow(period="22.5", dividend=30.0, is_forecast=False)
        assert result[1] == DividendRow(period="23.5", dividend=35.0, is_forecast=False)
        assert result[2] == DividendRow(period="24.5", dividend=40.0, is_forecast=True)

    def test_returns_empty_for_none(self) -> None:
        assert parse_dividends(None) == []

    def test_skips_dash_values(self) -> None:
        raw = [
            ["【配当】", "配当金(円)"],
            ["22.5", "-"],
        ]
        result = parse_dividends(raw)
        assert len(result) == 1
        assert result[0].dividend is None


class TestParseMetrics:
    def test_parses_scalar_fields(self) -> None:
        payload = {
            "is_exist": "1",
            "company_name_j": "テスト",
            "fyp1_per": 15.5,
            "fyp2_per": 12.3,
            "pbr": 1.5,
            "shimen_per_high": 20.0,
            "shimen_per_low": 10.0,
            "fyp1_dividend_yield": 0.02,
            "fyp2_dividend_yield": 0.03,
            "market_capitalization": 5000.0,
            "shimen_ratio_of_net_worth": 45.0,
            "year_high": 2000.0,
            "year_low": 1500.0,
            "shimen_stats": {
                "roe": ["ROE", "12.5%", "予10.0%"],
                "roa": ["ROA", "8.3%"],
                "eps": ["調整１株益", "150.2円"],
            },
            "shimen_financials": {
                "net_worth": ["自己資本", "50,000"],
                "total_assets": ["総資産", "100,000"],
                "capital_stock": ["資本金", "10,000"],
                "interest_bearing_liabilities": ["有利子負債", "5,000"],
            },
            "shimen_employees": "【従業員】<25.3> 500名(35歳)",
            "shimen_established_date": 20000101,
            "shimen_listed_date": 20100601,
            "shimen_year_end_month": "【決算】3月",
        }
        m = parse_metrics("7203", payload)
        assert m is not None
        assert m.code == "7203"
        assert m.fyp1_per == 15.5
        assert m.pbr == 1.5
        assert m.roe == 12.5
        assert m.roa == 8.3
        assert m.eps == 150.2
        assert m.net_worth == 50000
        assert m.total_assets == 100000
        assert m.capital_stock == 10000
        assert m.interest_bearing_debt == 5000
        assert m.employees == 500
        assert m.established_date == "20000101"
        assert m.listed_date == "20100601"
        assert m.year_end_month == "3"

    def test_returns_none_for_nonexistent(self) -> None:
        assert parse_metrics("9999", {"is_exist": "0"}) is None

    def test_handles_null_fields(self) -> None:
        m = parse_metrics("7203", {"is_exist": "1"})
        assert m is not None
        assert m.fyp1_per is None
        assert m.roe is None

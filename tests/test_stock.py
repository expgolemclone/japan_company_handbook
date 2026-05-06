from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scrape.stock import (
    ForecastRow,
    MajorShareholder,
    StockPerformance,
    _parse_value,
    fetch_stock_latest,
    parse_shimen_results,
)
from scrape.stock_db import existing_shareholder_codes, init_db, save_performance, save_shareholders


class TestParseValue:
    def test_numeric_with_comma(self) -> None:
        assert _parse_value("3,800,000") == 3800000

    def test_plain_numeric(self) -> None:
        assert _parse_value("179.5") is None  # float string → ValueError → None

    def test_integer_string(self) -> None:
        assert _parse_value("3800000") == 3800000

    def test_dash_fullwidth(self) -> None:
        assert _parse_value("ー") is None

    def test_dash_halfwidth(self) -> None:
        assert _parse_value("-") is None

    def test_none(self) -> None:
        assert _parse_value(None) is None

    def test_empty(self) -> None:
        assert _parse_value("") is None


SAMPLE_SHIMEN_RESULTS = [
    ["【業績】", "売上高", "営業利益", "税前利益", "純利益", "1株益(円)", "1株配(円)"],
    ["◇23.3", "37,154,298", "2,725,025", "3,668,733", "2,451,318", "179.5", "60"],
    ["◇24.3", "45,095,325", "5,352,934", "6,965,085", "4,944,933", "365.9", "75"],
    ["◇25.3", "48,036,704", "4,795,586", "6,414,590", "4,765,086", "359.6", "90"],
    ["◇26.3予", "ー", "ー", "ー", "ー", "ー", "ー"],
    ["◇27.3予", "ー", "ー", "ー", "ー", "ー", "ー"],
    ["◇25.4〜9", "24,630,753", "2,005,692", "2,478,127", "1,773,426", "136.1", "45"],
    ["◇26.4〜9予", "ー", "ー", "ー", "ー", "ー", "ー"],
    ["◇24.4〜12", "35,673,545", "3,679,491", "5,430,093", "4,100,389", "308.0"],
    ["◇25.4〜12", "38,087,604", "3,196,722", "4,188,484", "3,030,891", "232.6"],
    ["会26.3予", "50,000,000", "3,800,000", "5,020,000", "3,570,000", "-", "(26.2.6)"],
]

SAMPLE_TANREN_SHIMEN_RESULTS = [
    ["【業績】", "売上高", "営業利益", "経常利益", "純利益", "1株益(円)", "1株配(円)"],
    ["単22.6", "1,397", "52", "51", "38", "15.9", "0"],
    ["連23.6", "1,711", "164", "169", "121", "49.8", "0"],
    ["連24.6", "1,957", "231", "231", "156", "59.3", "10"],
    ["連25.6", "2,006", "123", "125", "32", "10.4", "10"],
    ["連26.6予", "2,100", "-60", "-60", "-100", "-31.3", "10"],
    ["連27.6予", "2,600", "0", "0", "-10", "-3.1", "10"],
    ["連25.7〜12", "1,008", "-31", "-29", "-69", "-22.2", "0"],
    ["連26.7〜12予", "1,100", "-20", "-20", "-30", "-9.4", "0"],
]

SAMPLE_VARIANT_SHIMEN_RESULTS = [
    ["【業績】", "売上高", "営業利益", "税前利益", "純利益", "1株益(円)", "1株配(円)"],
    ["◇25.9", "4,399", "-351", "-370", "-377", "-63.6", "0"],
    ["◇26.4予変", "2,400", "70", "70", "50", "8.2", "0"],
    ["連26.9*予", "1,100", "-700", "-700", "-700", "-6.8", "0"],
    ["◎27.3予", "5,400,000", "‥", "535,000", "353,000", "118.0", "47〜49"],
]


class TestParseShimenResults:
    def test_extracts_shikiho_forecasts(self) -> None:
        shikiho, company = parse_shimen_results(SAMPLE_SHIMEN_RESULTS)
        assert len(shikiho) == 2
        assert shikiho[0] == ForecastRow(period="26.3", operating_profit=None, net_income=None)
        assert shikiho[1] == ForecastRow(period="27.3", operating_profit=None, net_income=None)

    def test_extracts_company_forecast(self) -> None:
        shikiho, company = parse_shimen_results(SAMPLE_SHIMEN_RESULTS)
        assert company is not None
        assert company.period == "26.3"
        assert company.operating_profit == 3800000
        assert company.net_income == 3570000

    def test_ignores_actual_results(self) -> None:
        shikiho, company = parse_shimen_results(SAMPLE_SHIMEN_RESULTS)
        periods = [fc.period for fc in shikiho]
        assert "23.3" not in periods
        assert "24.3" not in periods
        assert "25.3" not in periods

    def test_ignores_half_year_forecasts(self) -> None:
        shikiho, _ = parse_shimen_results(SAMPLE_SHIMEN_RESULTS)
        periods = [fc.period for fc in shikiho]
        assert "26.4〜9" not in periods

    def test_extracts_full_year_forecasts_from_tanren_labels(self) -> None:
        shikiho, company = parse_shimen_results(SAMPLE_TANREN_SHIMEN_RESULTS)
        assert shikiho == [
            ForecastRow(period="26.6", operating_profit=-60, net_income=-100),
            ForecastRow(period="27.6", operating_profit=0, net_income=-10),
        ]
        assert company is None

    def test_ignores_half_year_forecasts_from_tanren_labels(self) -> None:
        shikiho, _ = parse_shimen_results(SAMPLE_TANREN_SHIMEN_RESULTS)
        periods = [fc.period for fc in shikiho]
        assert "26.7〜12" not in periods

    def test_extracts_variant_full_year_forecasts(self) -> None:
        shikiho, company = parse_shimen_results(SAMPLE_VARIANT_SHIMEN_RESULTS)
        assert shikiho == [
            ForecastRow(period="26.4", operating_profit=70, net_income=50),
            ForecastRow(period="26.9", operating_profit=-700, net_income=-700),
        ]
        assert company is None

    def test_extracts_financial_sector_forecasts(self) -> None:
        shikiho, _ = parse_shimen_results(
            [
                SAMPLE_VARIANT_SHIMEN_RESULTS[0],
                SAMPLE_VARIANT_SHIMEN_RESULTS[4],
                ["◎28.3予", "5,500,000", "‥", "540,000", "360,000", "120.0", "48〜50"],
            ]
        )
        assert shikiho == [
            ForecastRow(period="27.3", operating_profit=None, net_income=353000),
            ForecastRow(period="28.3", operating_profit=None, net_income=360000),
        ]

    def test_empty_results(self) -> None:
        shikiho, company = parse_shimen_results([["【業績】", "売上高", "営業利益"]])
        assert shikiho == []
        assert company is None

    def test_with_actual_shikiho_values(self) -> None:
        results = [
            ["【業績】", "売上高", "営業利益", "税前利益", "純利益"],
            ["◇26.3予", "50,000,000", "4,000,000", "5,200,000", "3,800,000"],
            ["◇27.3予", "52,000,000", "4,200,000", "5,400,000", "3,900,000"],
            ["会26.3予", "50,000,000", "3,800,000", "5,020,000", "3,570,000"],
        ]
        shikiho, company = parse_shimen_results(results)
        assert shikiho[0].operating_profit == 4000000
        assert shikiho[0].net_income == 3800000
        assert shikiho[1].operating_profit == 4200000
        assert shikiho[1].net_income == 3900000
        assert company is not None
        assert company.operating_profit == 3800000
        assert company.net_income == 3570000


class TestFetchStockLatest:
    def test_returns_performance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": "トヨタ自動車",
            "shimen_results": SAMPLE_SHIMEN_RESULTS,
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "7203")

        assert result is not None
        assert result.code == "7203"
        assert result.company_name == "トヨタ自動車"
        assert len(result.shikiho_forecasts) == 2
        assert result.company_forecast is not None
        assert result.company_forecast.operating_profit == 3800000

    def test_returns_none_for_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json={"is_exist": "0"}, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "9999")
        assert result is None

    def test_returns_performance_for_tanren_labels_with_missing_company_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": None,
            "shimen_results": SAMPLE_TANREN_SHIMEN_RESULTS,
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "157A")

        assert result is not None
        assert result.company_name == ""
        assert result.shikiho_forecasts == [
            ForecastRow(period="26.6", operating_profit=-60, net_income=-100),
            ForecastRow(period="27.6", operating_profit=0, net_income=-10),
        ]

    def test_returns_none_when_no_supported_forecast_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": None,
            "shimen_results": [
                ["【業績】", "売上高", "営業利益", "経常利益", "純利益"],
                ["連25.7〜12", "1,008", "-31", "-29", "-69"],
                ["連26.7〜12予", "1,100", "-20", "-20", "-30"],
            ],
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "157A")

        assert result is None

    def test_returns_performance_for_variant_full_year_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": None,
            "shimen_results": SAMPLE_VARIANT_SHIMEN_RESULTS,
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "8604")

        assert result is not None
        assert result.company_name == ""
        assert result.shikiho_forecasts == [
            ForecastRow(period="26.4", operating_profit=70, net_income=50),
            ForecastRow(period="26.9", operating_profit=-700, net_income=-700),
        ]


class TestStockDb:
    def test_init_and_save(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        perf = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[
                ForecastRow(period="26.3", operating_profit=None, net_income=None),
                ForecastRow(period="27.3", operating_profit=None, net_income=None),
            ],
            company_forecast=ForecastRow(period="26.3", operating_profit=3800000, net_income=3570000),
            shareholders=[],
            shareholders_date=None,
        )
        save_performance(perf, db_path)

        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT * FROM stock_forecasts ORDER BY forecast_type DESC, period"
        ).fetchall()
        con.close()

        assert len(rows) == 3
        # shikiho 26.3
        assert rows[0] == ("7203", "トヨタ自動車", "shikiho", "26.3", None, None, rows[0][6])
        # shikiho 27.3
        assert rows[1] == ("7203", "トヨタ自動車", "shikiho", "27.3", None, None, rows[1][6])
        # company 26.3
        assert rows[2][:6] == ("7203", "トヨタ自動車", "company", "26.3", 3800000, 3570000)

    def test_upsert_overwrites(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        perf1 = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=ForecastRow(period="26.3", operating_profit=3800000, net_income=3570000),
            shareholders=[],
            shareholders_date=None,
        )
        save_performance(perf1, db_path)

        perf2 = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=ForecastRow(period="26.3", operating_profit=4000000, net_income=3800000),
            shareholders=[],
            shareholders_date=None,
        )
        save_performance(perf2, db_path)

        con = sqlite3.connect(db_path)
        rows = con.execute("SELECT operating_profit, net_income FROM stock_forecasts").fetchall()
        con.close()

        assert len(rows) == 1
        assert rows[0] == (4000000, 3800000)


SAMPLE_SHAREHOLDERS = [
    {"name": "日本マスター信託", "number": "174,020", "ratio": "11.0"},
    {"name": "豊田自動織機", "number": "119,233", "ratio": "7.5"},
    {"name": "日本カストディ銀行", "number": "81,561", "ratio": "5.1"},
]


class TestParseShareholders:
    def test_parses_shareholders_from_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": "トヨタ自動車",
            "shimen_results": SAMPLE_SHIMEN_RESULTS,
            "shimen_shareholders": SAMPLE_SHAREHOLDERS,
            "shareholders_research_date": "20250930",
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "7203")

        assert result is not None
        assert result.shareholders_date == "20250930"
        assert len(result.shareholders) == 3
        assert result.shareholders[0] == MajorShareholder(name="日本マスター信託", shares=174020, ratio_pct=11.0)
        assert result.shareholders[1] == MajorShareholder(name="豊田自動織機", shares=119233, ratio_pct=7.5)
        assert result.shareholders[2] == MajorShareholder(name="日本カストディ銀行", shares=81561, ratio_pct=5.1)

    def test_handles_missing_shareholders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        payload = {
            "is_exist": "1",
            "company_name_j": "テスト",
            "shimen_results": SAMPLE_SHIMEN_RESULTS,
        }
        request = httpx.Request("GET", "https://example.com/test")
        response = httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "get", lambda self, url: response)
        client = httpx.Client()
        result = fetch_stock_latest(client, "9999")

        assert result is not None
        assert result.shareholders == []
        assert result.shareholders_date is None


class TestShareholderDb:
    def test_save_and_query_shareholders(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        perf = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=None,
            shareholders=[
                MajorShareholder(name="日本マスター信託", shares=174020, ratio_pct=11.0),
                MajorShareholder(name="豊田自動織機", shares=119233, ratio_pct=7.5),
            ],
            shareholders_date="20250930",
        )
        save_shareholders(perf, db_path)

        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT rank, shareholder_name, shares, ratio_pct, research_date "
            "FROM major_shareholders ORDER BY rank"
        ).fetchall()
        con.close()

        assert len(rows) == 2
        assert rows[0] == (1, "日本マスター信託", 174020, 11.0, "20250930")
        assert rows[1] == (2, "豊田自動織機", 119233, 7.5, "20250930")

    def test_upsert_overwrites_shareholders(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        perf1 = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=None,
            shareholders=[
                MajorShareholder(name="旧株主A", shares=100, ratio_pct=5.0),
            ],
            shareholders_date="20250630",
        )
        save_shareholders(perf1, db_path)

        perf2 = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=None,
            shareholders=[
                MajorShareholder(name="新株主B", shares=200, ratio_pct=10.0),
            ],
            shareholders_date="20250930",
        )
        save_shareholders(perf2, db_path)

        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT shareholder_name, shares, research_date FROM major_shareholders"
        ).fetchall()
        con.close()

        assert len(rows) == 1
        assert rows[0] == ("新株主B", 200, "20250930")

    def test_existing_shareholder_codes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        assert existing_shareholder_codes(db_path) == set()

        perf = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=None,
            shareholders=[
                MajorShareholder(name="テスト", shares=100, ratio_pct=1.0),
            ],
            shareholders_date="20250930",
        )
        save_shareholders(perf, db_path)

        assert existing_shareholder_codes(db_path) == {"7203"}

    def test_save_does_nothing_for_empty_shareholders(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)

        perf = StockPerformance(
            code="7203",
            company_name="トヨタ自動車",
            shikiho_forecasts=[],
            company_forecast=None,
            shareholders=[],
            shareholders_date=None,
        )
        save_shareholders(perf, db_path)

        con = sqlite3.connect(db_path)
        rows = con.execute("SELECT * FROM major_shareholders").fetchall()
        con.close()
        assert len(rows) == 0

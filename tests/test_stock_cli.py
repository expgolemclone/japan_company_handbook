from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from scrape import stock_cli
from scrape.stock import ForecastRow, StockLatestJson, StockPerformance


class _ExecvCalled(Exception):
    pass


class TestFindProjectVenvPython:
    def test_returns_python3_when_present(self, tmp_path: Path) -> None:
        python3 = tmp_path / ".venv/bin/python3"
        python3.parent.mkdir(parents=True)
        python3.write_text("", encoding="utf-8")

        assert stock_cli._find_project_venv_python(tmp_path) == python3

    def test_returns_none_when_venv_missing(self, tmp_path: Path) -> None:
        assert stock_cli._find_project_venv_python(tmp_path) is None


class TestIsRunningInsideProjectVenv:
    def test_detects_project_venv_from_sys_prefix(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        venv_python = tmp_path / ".venv/bin/python3"
        venv_python.parent.mkdir(parents=True)
        monkeypatch.setattr(stock_cli.sys, "prefix", str(tmp_path / ".venv"))

        assert stock_cli._is_running_inside_project_venv(venv_python) is True


class TestEnsureHttpxRuntime:
    def test_reexecs_into_project_venv_when_httpx_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        venv_python = tmp_path / ".venv/bin/python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")

        def fake_import_module(name: str) -> object:
            raise ModuleNotFoundError("No module named 'httpx'", name=name)

        def fake_execv(path: str, argv: list[str]) -> None:
            raise _ExecvCalled((path, argv))

        monkeypatch.setattr(stock_cli.importlib, "import_module", fake_import_module)
        monkeypatch.setattr(stock_cli, "_find_project_venv_python", lambda: venv_python)
        monkeypatch.setattr(stock_cli.sys, "argv", [str(stock_cli.PROJECT_ROOT / "scrape/stock_cli.py"), "--dry-run"])
        monkeypatch.setattr(stock_cli.sys, "prefix", str(tmp_path / ".global"))
        monkeypatch.setattr(stock_cli.os, "execv", fake_execv)

        with pytest.raises(_ExecvCalled) as exc_info:
            stock_cli._ensure_httpx_runtime()

        assert exc_info.value.args[0] == (
            str(venv_python),
            [str(venv_python), "-m", "scrape.shikiho_cli", "stock", "fetch", "--dry-run"],
        )

    def test_exits_with_helpful_message_when_httpx_missing_and_no_venv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_import_module(name: str) -> object:
            raise ModuleNotFoundError("No module named 'httpx'", name=name)

        monkeypatch.setattr(stock_cli.importlib, "import_module", fake_import_module)
        monkeypatch.setattr(stock_cli, "_find_project_venv_python", lambda: None)

        with pytest.raises(SystemExit, match="shikiho stock fetch"):
            stock_cli._ensure_httpx_runtime()


class _FakeApiClient:
    def __init__(self) -> None:
        self.closed = False
        self.sso_checks = 0

    def get(self, path: str):
        import httpx

        self.sso_checks += 1
        assert path == "/sso/v1/sso/check"
        request = httpx.Request("GET", f"https://api-shikiho.toyokeizai.net{path}")
        return httpx.Response(200, json={"auth_level": 5}, request=request)

    def close(self) -> None:
        self.closed = True


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"https://api-shikiho.toyokeizai.net/status/{status_code}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


def _latest_json(code: str, content: bytes | None = None) -> StockLatestJson:
    body = content or f'{{"code":"{code}"}}'.encode()
    return StockLatestJson(code=code, payload={"code": code}, content=body)


def _performance(code: str) -> StockPerformance:
    return StockPerformance(
        code=code,
        company_name="トヨタ自動車",
        shikiho_forecasts=[
            ForecastRow(period="26.3", operating_profit=4000000, net_income=3800000),
        ],
        company_forecast=ForecastRow(
            period="26.3",
            operating_profit=3800000,
            net_income=3570000,
        ),
        shareholders=[],
        shareholders_date=None,
    )


class TestRun:
    def test_fetches_requested_code_without_loading_default_codes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        client = _FakeApiClient()
        saved: list[StockPerformance] = []
        raw_dir = tmp_path / "raw"

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: pytest.fail("default code list should not be loaded"))
        monkeypatch.setattr(stock_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_cli, "build_api_client", lambda: client)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest_json", lambda client, code: _latest_json(code, b'{"raw":true}'))
        monkeypatch.setattr(stock_cli, "parse_stock_latest_payload", lambda code, payload: _performance(code))
        monkeypatch.setattr(stock_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_cli, "save_metrics", lambda met: None)

        exit_code = stock_cli.main([
            "--code",
            "4231",
            "--force",
            "--raw-json-dir",
            str(raw_dir),
        ])

        assert exit_code == 0
        assert client.closed is True
        assert [perf.code for perf in saved] == ["4231"]
        assert (raw_dir / "4231.json").read_bytes() == b'{"raw":true}'

    def test_fetches_codes_and_saves_successes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        client = _FakeApiClient()
        init_calls = 0
        saved: list[StockPerformance] = []
        sleeps: list[float] = []
        raw_dir = tmp_path / "raw"

        def fake_init_db() -> None:
            nonlocal init_calls
            init_calls += 1

        def fake_parse_stock_latest_payload(
            code: str,
            payload: dict[str, object],
        ) -> StockPerformance | None:
            if code == "7203":
                return _performance(code)
            return None

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: ["7203", "9999"])
        monkeypatch.setattr(stock_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "init_db", fake_init_db)
        monkeypatch.setattr(stock_cli, "build_api_client", lambda: client)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest_json", lambda client, code: _latest_json(code))
        monkeypatch.setattr(stock_cli, "parse_stock_latest_payload", fake_parse_stock_latest_payload)
        monkeypatch.setattr(stock_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_cli, "save_metrics", lambda met: None)
        monkeypatch.setattr(stock_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
        caplog.set_level(logging.INFO)

        exit_code = stock_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert init_calls == 1
        assert client.sso_checks == 1
        assert client.closed is True
        assert [perf.code for perf in saved] == ["7203"]
        assert (raw_dir / "7203.json").read_bytes() == b'{"code":"7203"}'
        assert (raw_dir / "9999.json").read_bytes() == b'{"code":"9999"}'
        assert sleeps == [stock_cli.REQUEST_INTERVAL]
        assert "完了 — 成功: 1, スキップ: 1 / 2" in caplog.text

    def test_skips_only_when_db_and_raw_json_exist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        client = _FakeApiClient()
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "7203.json").write_bytes(b'{"code":"7203"}')
        fetched: list[str] = []

        def fake_fetch_stock_latest_json(
            _client: _FakeApiClient,
            code: str,
        ) -> StockLatestJson:
            fetched.append(code)
            return _latest_json(code)

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: ["7203", "9999"])
        monkeypatch.setattr(stock_cli, "existing_codes", lambda: {"7203", "9999"})
        monkeypatch.setattr(stock_cli, "existing_shareholder_codes", lambda: {"7203", "9999"})
        monkeypatch.setattr(stock_cli, "existing_dividend_codes", lambda: {"7203", "9999"})
        monkeypatch.setattr(stock_cli, "existing_metrics_codes", lambda: {"7203", "9999"})
        monkeypatch.setattr(stock_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_cli, "build_api_client", lambda: client)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest_json", fake_fetch_stock_latest_json)
        monkeypatch.setattr(stock_cli, "parse_stock_latest_payload", lambda code, payload: None)
        monkeypatch.setattr(stock_cli.time, "sleep", lambda seconds: None)

        exit_code = stock_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert fetched == ["9999"]
        assert (raw_dir / "9999.json").read_bytes() == b'{"code":"9999"}'

    def test_retries_same_code_after_auth_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        clients: list[_FakeApiClient] = []
        refresh_calls = 0
        saved: list[StockPerformance] = []
        raw_dir = tmp_path / "raw"

        def fake_build_api_client() -> _FakeApiClient:
            client = _FakeApiClient()
            clients.append(client)
            return client

        def fake_refresh_cookie_source() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        fetch_calls = 0

        def fake_fetch_stock_latest_json(_client: _FakeApiClient, code: str) -> StockLatestJson:
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls == 1:
                raise _http_status_error(401)
            return _latest_json(code, b'{"retry":true}')

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: ["7203"])
        monkeypatch.setattr(stock_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_cli, "build_api_client", fake_build_api_client)
        monkeypatch.setattr(stock_cli, "refresh_cookie_source", fake_refresh_cookie_source)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest_json", fake_fetch_stock_latest_json)
        monkeypatch.setattr(stock_cli, "parse_stock_latest_payload", lambda code, payload: _performance(code))
        monkeypatch.setattr(stock_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_cli, "save_shareholders", lambda perf: None)
        monkeypatch.setattr(stock_cli, "save_dividends", lambda code, divs: None)
        monkeypatch.setattr(stock_cli, "save_metrics", lambda met: None)

        exit_code = stock_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert refresh_calls == 1
        assert fetch_calls == 2
        assert len(clients) == 2
        assert clients[0].closed is True
        assert clients[1].closed is True
        assert [perf.code for perf in saved] == ["7203"]
        assert (raw_dir / "7203.json").read_bytes() == b'{"retry":true}'

    def test_skips_code_after_second_auth_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        clients: list[_FakeApiClient] = []
        refresh_calls = 0
        raw_dir = tmp_path / "raw"

        def fake_build_api_client() -> _FakeApiClient:
            client = _FakeApiClient()
            clients.append(client)
            return client

        def fake_refresh_cookie_source() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: ["7203"])
        monkeypatch.setattr(stock_cli, "existing_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_shareholder_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_dividend_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "existing_metrics_codes", lambda: set())
        monkeypatch.setattr(stock_cli, "init_db", lambda: None)
        monkeypatch.setattr(stock_cli, "build_api_client", fake_build_api_client)
        monkeypatch.setattr(stock_cli, "refresh_cookie_source", fake_refresh_cookie_source)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest_json", lambda client, code: (_ for _ in ()).throw(_http_status_error(403)))

        exit_code = stock_cli.main(["--raw-json-dir", str(raw_dir)])

        assert exit_code == 0
        assert refresh_calls == 1
        assert len(clients) == 2
        assert clients[0].closed is True
        assert clients[1].closed is True

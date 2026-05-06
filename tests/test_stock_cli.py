from __future__ import annotations

from pathlib import Path

import pytest

from scrape import stock_cli
from scrape.stock import ForecastRow, StockPerformance


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


class TestRun:
    def test_fetches_codes_and_saves_successes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _FakeApiClient()
        init_calls = 0
        saved: list[StockPerformance] = []
        sleeps: list[float] = []

        def fake_init_db() -> None:
            nonlocal init_calls
            init_calls += 1

        def fake_fetch_stock_latest(_client: _FakeApiClient, code: str) -> StockPerformance | None:
            if code == "7203":
                return StockPerformance(
                    code="7203",
                    company_name="トヨタ自動車",
                    shikiho_forecasts=[
                        ForecastRow(period="26.3", operating_profit=4000000, net_income=3800000),
                        ForecastRow(period="27.3", operating_profit=4200000, net_income=3900000),
                    ],
                    company_forecast=ForecastRow(
                        period="26.3",
                        operating_profit=3800000,
                        net_income=3570000,
                    ),
                )
            return None

        monkeypatch.setattr(stock_cli, "_load_stock_codes", lambda: ["7203", "9999"])
        monkeypatch.setattr(stock_cli, "init_db", fake_init_db)
        monkeypatch.setattr(stock_cli, "build_api_client", lambda: client)
        monkeypatch.setattr(stock_cli, "fetch_stock_latest", fake_fetch_stock_latest)
        monkeypatch.setattr(stock_cli, "save_performance", lambda perf: saved.append(perf))
        monkeypatch.setattr(stock_cli.time, "sleep", lambda seconds: sleeps.append(seconds))

        exit_code = stock_cli.main([])

        assert exit_code == 0
        assert init_calls == 1
        assert client.sso_checks == 1
        assert client.closed is True
        assert [perf.code for perf in saved] == ["7203"]
        assert sleeps == [stock_cli.REQUEST_INTERVAL]

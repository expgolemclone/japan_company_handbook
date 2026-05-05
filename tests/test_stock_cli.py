from __future__ import annotations

from pathlib import Path

import pytest

from scrape import stock_cli


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
            [str(venv_python), "-m", "scrape.stock_cli", "--dry-run"],
        )

    def test_exits_with_helpful_message_when_httpx_missing_and_no_venv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_import_module(name: str) -> object:
            raise ModuleNotFoundError("No module named 'httpx'", name=name)

        monkeypatch.setattr(stock_cli.importlib, "import_module", fake_import_module)
        monkeypatch.setattr(stock_cli, "_find_project_venv_python", lambda: None)

        with pytest.raises(SystemExit, match="uv sync"):
            stock_cli._ensure_httpx_runtime()

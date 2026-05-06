from __future__ import annotations

import json
from pathlib import Path

import httpx

from scrape.magazine.audit_cli import main
from scrape.magazine.client import save_expected_issues
from scrape.magazine.types import MagazineIssueKey


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _stub_refresh_cookie(
    monkeypatch,
    *,
    return_value: bool = True,
    calls: dict[str, int] | None = None,
) -> None:
    def fake_refresh(*args, **kwargs) -> bool:
        if calls is not None:
            calls["refresh"] = calls.get("refresh", 0) + 1
        return return_value

    monkeypatch.setattr("scrape.magazine.audit_cli.refresh_cookie_source", fake_refresh)


class TestMagazineAuditCli:
    def test_refreshes_cookie_after_permission_error(self, monkeypatch, tmp_path: Path) -> None:
        refresh_calls: dict[str, int] = {}
        api_calls: dict[str, int] = {}
        _stub_refresh_cookie(monkeypatch, calls=refresh_calls)

        _write_json(
            tmp_path / "issues.raw.json",
            {
                "status": {"code": "2000", "message": "ok"},
                "magazines": [
                    {"calendar": "1936", "series": "3", "title": "６月号"},
                ],
            },
        )
        save_expected_issues(
            [MagazineIssueKey("1936", "3")],
            tmp_path / "issues.expected.json",
        )
        _write_json(
            tmp_path / "1936_3" / "manifest.raw.json",
            {
                "magazine": {
                    "title": "６月号",
                    "previousTitle": None,
                    "followingTitle": None,
                }
            },
        )

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/files/v1/files/magazines/list":
                api_calls["list"] = api_calls.get("list", 0) + 1
                if refresh_calls.get("refresh", 0) == 0:
                    return httpx.Response(
                        200,
                        json={
                            "status": {
                                "code": "3202",
                                "message": "you don't have permission to execute.",
                            }
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "2000", "message": "ok"},
                        "magazines": [
                            {"calendar": "1936", "series": "3", "title": "６月号"},
                        ],
                    },
                )
            if path == "/files/v1/files/magazines/1936/3":
                api_calls["detail"] = api_calls.get("detail", 0) + 1
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "1000", "message": "ok"},
                        "magazine": {
                            "calendar": "1936",
                            "series": "3",
                            "title": "６月号",
                            "pages": [{"page": "0000page"}],
                        },
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        monkeypatch.setattr(
            "scrape.magazine.audit_cli.build_magazine_http_client",
            lambda *args, **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api-shikiho.toyokeizai.net",
            ),
        )

        exit_code = main(["--out-dir", str(tmp_path)])

        assert exit_code == 0
        assert refresh_calls["refresh"] == 1
        assert api_calls["list"] == 2
        assert api_calls["detail"] == 2

        report = json.loads((tmp_path / "auth_diagnostics.json").read_text(encoding="utf-8"))
        assert report["ok"] is True

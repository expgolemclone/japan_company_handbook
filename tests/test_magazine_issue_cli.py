from __future__ import annotations

import json
from pathlib import Path

import httpx

from scrape.magazine.issue_cli import main

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


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

    monkeypatch.setattr("scrape.magazine.issue_cli.refresh_cookie_source", fake_refresh)


class TestMagazineIssueCli:
    def test_retries_same_issue_after_auth_error(self, monkeypatch, tmp_path: Path) -> None:
        calls: dict[str, int] = {}
        refresh_calls: dict[str, int] = {}
        _stub_refresh_cookie(monkeypatch, calls=refresh_calls)
        raw_issue = _load_json("2026_2.raw.json")

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/files/v1/files/magazines/2026/2":
                calls["detail"] = calls.get("detail", 0) + 1
                if calls["detail"] == 1 and refresh_calls.get("refresh", 0) == 0:
                    return httpx.Response(401, request=request)
                return httpx.Response(200, json=raw_issue)
            if path.endswith(".pdf"):
                return httpx.Response(
                    200,
                    content=b"%PDF-1.4 page pdf",
                    headers={"content-type": "application/pdf"},
                )
            if path.endswith(".jpg"):
                return httpx.Response(
                    200,
                    content=b"jpeg",
                    headers={"content-type": "image/jpeg"},
                )
            return httpx.Response(
                200,
                content=b"png",
                headers={"content-type": "image/png"},
            )

        monkeypatch.setattr(
            "scrape.magazine.issue_cli.build_magazine_http_client",
            lambda *args, **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api-shikiho.toyokeizai.net",
            ),
        )

        exit_code = main(["--calendar", "2026", "--series", "2", "--out-dir", str(tmp_path)])

        assert exit_code == 0
        assert refresh_calls["refresh"] == 1
        assert calls["detail"] == 2
        assert (tmp_path / "2026_2" / "pages" / "0100page.pdf").exists()

    def test_returns_error_after_second_auth_failure(self, monkeypatch, tmp_path: Path) -> None:
        calls: dict[str, int] = {}
        refresh_calls: dict[str, int] = {}
        _stub_refresh_cookie(monkeypatch, calls=refresh_calls)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/files/v1/files/magazines/2026/2":
                calls["detail"] = calls.get("detail", 0) + 1
                return httpx.Response(401, request=request)
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        monkeypatch.setattr(
            "scrape.magazine.issue_cli.build_magazine_http_client",
            lambda *args, **kwargs: httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api-shikiho.toyokeizai.net",
            ),
        )

        exit_code = main(["--calendar", "2026", "--series", "2", "--out-dir", str(tmp_path)])

        assert exit_code == 1
        assert refresh_calls["refresh"] == 1
        assert calls["detail"] == 2

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from scrape.magazine.client import (
    MagazinePermissionError,
    MagazinePayloadShapeError,
    build_pdf_source_url,
    build_magazine_http_client,
    extract_issue_refs,
    fetch_pdf_access,
    fetch_issue_list,
    fetch_magazine_issue,
    is_probable_auth_error,
    load_expected_issues,
    save_expected_issues,
)
from scrape.magazine.types import MagazineIssueKey

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class TestBuildMagazineHttpClient:
    def test_loads_cookie_file(self, tmp_path: Path) -> None:
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(
            json.dumps(
                [
                    {"name": "session", "value": "token", "domain": "toyokeizai.net"},
                ]
            ),
            encoding="utf-8",
        )

        client = build_magazine_http_client(cookie_file)
        try:
            assert client.cookies.get("session") == "token"
        finally:
            client.close()


class TestFetchMagazineApi:
    def test_fetch_issue_list_accepts_live_success_code(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                    "magazines": [],
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        payload = fetch_issue_list(client)

        assert payload["magazines"] == []

    def test_fetch_issue_list_raises_on_permission_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {
                        "code": "3202",
                        "message": "you don't have permission to execute.",
                    }
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        with pytest.raises(MagazinePermissionError):
            fetch_issue_list(client)

    def test_fetch_issue_list_raises_when_magazines_array_is_missing(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        with pytest.raises(MagazinePayloadShapeError, match="magazines 配列"):
            fetch_issue_list(client)

    def test_fetch_issue_list_retries_transport_error(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("dns failed", request=request)
            return httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                    "magazines": [],
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.example.test")

        payload = fetch_issue_list(client)

        assert payload["magazines"] == []
        assert calls == 2

    def test_fetch_magazine_issue_uses_expected_path(self) -> None:
        calls: list[str] = []
        fixture = _load_json("2026_2.raw.json")

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=fixture)

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.example.test")
        payload = fetch_magazine_issue(client, "2026", "2")

        assert payload["magazine"]["series"] == "2"
        assert calls == ["/files/v1/files/magazines/2026/2"]

    def test_fetch_magazine_issue_raises_when_magazine_is_empty(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                    "magazine": {},
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        with pytest.raises(MagazinePayloadShapeError, match="magazine オブジェクトが空"):
            fetch_magazine_issue(client, "2026", "2")

    def test_fetch_magazine_issue_raises_when_pages_are_empty(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                    "magazine": {
                        "calendar": "2026",
                        "series": "2",
                        "pages": [],
                    },
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        with pytest.raises(MagazinePayloadShapeError, match="pages 配列が空"):
            fetch_magazine_issue(client, "2026", "2")

    def test_fetch_pdf_access_builds_premium_context(self) -> None:
        policy = base64.urlsafe_b64encode(
            b'{"Statement":[{"Resource":"https://shikiho.toyokeizai.net/files/shimen/premium/*"}]}'
        ).decode("ascii")
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": {"code": "1000", "message": "ok"},
                    "pdf_hash": f"Policy={policy}&Signature=abc&Key-Pair-Id=test",
                },
            )
        )
        client = httpx.Client(transport=transport, base_url="https://api.example.test")

        access = fetch_pdf_access(client)
        url = build_pdf_source_url(MagazineIssueKey("2026", "2"), "0000page", access)

        assert access == {
            "pdf_hash": f"Policy={policy}&Signature=abc&Key-Pair-Id=test",
            "tier": "premium",
        }
        assert (
            url
            == f"https://shikiho.toyokeizai.net/files/shimen/premium/2026/2/0000page.pdf?Policy={policy}&Signature=abc&Key-Pair-Id=test"
        )


class TestAuthErrorClassifier:
    def test_returns_true_for_401(self) -> None:
        request = httpx.Request("GET", "https://api.example.test/files/v1/files/magazines/2026/2")
        response = httpx.Response(401, request=request)
        error = httpx.HTTPStatusError("boom", request=request, response=response)

        assert is_probable_auth_error(error) is True

    def test_returns_false_for_503(self) -> None:
        request = httpx.Request("GET", "https://api.example.test/files/v1/files/magazines/2026/2")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("boom", request=request, response=response)

        assert is_probable_auth_error(error) is False

    def test_returns_true_for_auth_like_payload_shape_error(self) -> None:
        error = MagazinePayloadShapeError("2026_2: magazine オブジェクトが空です")

        assert is_probable_auth_error(error) is True

    def test_returns_false_for_non_auth_payload_shape_error(self) -> None:
        error = MagazinePayloadShapeError("issue list: magazines 配列がありません")

        assert is_probable_auth_error(error) is False


class TestExpectedIssues:
    def test_extract_issue_refs_sorts_and_deduplicates(self) -> None:
        fixture = _load_json("issues_list.json")

        issues = extract_issue_refs(fixture, start_calendar=1936)

        assert issues == [
            MagazineIssueKey("1936", "1"),
            MagazineIssueKey("1936", "2"),
            MagazineIssueKey("2026", "2"),
        ]

    def test_save_and_load_expected_issues(self, tmp_path: Path) -> None:
        issues = [MagazineIssueKey("1936", "1"), MagazineIssueKey("2026", "2")]
        path = tmp_path / "issues.expected.json"

        save_expected_issues(issues, path)
        loaded = load_expected_issues(path)

        assert loaded == issues

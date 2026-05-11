from __future__ import annotations

import httpx

from scrape import pdf_all_cli


class _FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

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


class TestPdfAllCli:
    def test_retries_after_401_and_downloads_pages(self, monkeypatch) -> None:
        api_clients: list[_FakeClient] = []
        download_client = _FakeClient("download")
        refresh_calls = 0
        access_calls: list[str] = []
        progress = object()
        downloaded: list[dict[str, object]] = []

        def fake_build_api_client() -> _FakeClient:
            client = _FakeClient(f"api-{len(api_clients) + 1}")
            api_clients.append(client)
            return client

        def fake_refresh_cookies_via_chrome() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        def fake_fetch_pdf_access(client: _FakeClient) -> dict[str, object]:
            access_calls.append(client.name)
            if len(access_calls) == 1:
                raise _http_status_error(401)
            return {
                "auth_level": 5,
                "pdf_hash": "Policy=abc",
                "pdf_path": "/files/shimen/premium",
            }

        monkeypatch.setattr(pdf_all_cli, "build_api_client", fake_build_api_client)
        monkeypatch.setattr(pdf_all_cli, "build_http_client", lambda: download_client)
        monkeypatch.setattr(pdf_all_cli, "refresh_cookie_source", fake_refresh_cookies_via_chrome)
        monkeypatch.setattr(pdf_all_cli, "fetch_pdf_access", fake_fetch_pdf_access)
        monkeypatch.setattr(
            pdf_all_cli,
            "fetch_issues",
            lambda client, from_year=1936: [
                {"calendar": "2026", "series": "2", "title": "春号"}
            ],
        )
        monkeypatch.setattr(
            pdf_all_cli,
            "fetch_magazine",
            lambda client, year, series: {"pages": [{"page": "0001"}, {"page": "0002"}]},
        )
        monkeypatch.setattr(pdf_all_cli, "extract_page_ids", lambda magazine: ["0001", "0002"])
        monkeypatch.setattr(pdf_all_cli, "Progress", lambda: progress)

        def fake_download_all_pages(
            client: _FakeClient,
            year: str,
            series: str,
            page_ids: list[str],
            access: dict[str, object],
            actual_progress: object,
            *,
            workers: int = 1,
        ) -> None:
            downloaded.append(
                {
                    "client": client.name,
                    "year": year,
                    "series": series,
                    "page_ids": page_ids,
                    "access": access,
                    "progress": actual_progress,
                }
            )

        monkeypatch.setattr(pdf_all_cli, "download_all_pages", fake_download_all_pages)

        exit_code = pdf_all_cli.main([])

        assert exit_code == 0
        assert refresh_calls == 1
        assert access_calls == ["api-1", "api-2"]
        assert downloaded == [
            {
                "client": "download",
                "year": "2026",
                "series": "2",
                "page_ids": ["0001", "0002"],
                "access": {
                    "auth_level": 5,
                    "pdf_hash": "Policy=abc",
                    "pdf_path": "/files/shimen/premium",
                },
                "progress": progress,
            }
        ]
        assert [client.closed for client in api_clients] == [True, True]
        assert download_client.closed is True

    def test_retries_same_issue_after_auth_error_during_download(self, monkeypatch) -> None:
        api_clients: list[_FakeClient] = []
        download_client = _FakeClient("download")
        refresh_calls = 0
        access_calls: list[str] = []
        magazine_calls = 0
        progress = object()
        download_attempts = 0

        def fake_build_api_client() -> _FakeClient:
            client = _FakeClient(f"api-{len(api_clients) + 1}")
            api_clients.append(client)
            return client

        def fake_refresh_cookies_via_chrome() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        def fake_fetch_pdf_access(client: _FakeClient) -> dict[str, object]:
            access_calls.append(client.name)
            return {
                "auth_level": 5,
                "pdf_hash": f"Policy={client.name}",
                "pdf_path": "/files/shimen/premium",
            }

        def fake_fetch_magazine(client: _FakeClient, year: str, series: str) -> dict[str, object]:
            nonlocal magazine_calls
            magazine_calls += 1
            return {"pages": [{"page": "0001"}, {"page": "0002"}]}

        def fake_download_all_pages(
            client: _FakeClient,
            year: str,
            series: str,
            page_ids: list[str],
            access: dict[str, object],
            actual_progress: object,
            *,
            workers: int = 1,
        ) -> None:
            nonlocal download_attempts
            download_attempts += 1
            if download_attempts == 1:
                raise _http_status_error(403)
            assert access["pdf_hash"] == "Policy=api-2"
            assert actual_progress is progress

        monkeypatch.setattr(pdf_all_cli, "build_api_client", fake_build_api_client)
        monkeypatch.setattr(pdf_all_cli, "build_http_client", lambda: download_client)
        monkeypatch.setattr(pdf_all_cli, "refresh_cookie_source", fake_refresh_cookies_via_chrome)
        monkeypatch.setattr(pdf_all_cli, "fetch_pdf_access", fake_fetch_pdf_access)
        monkeypatch.setattr(
            pdf_all_cli,
            "fetch_issues",
            lambda client, from_year=1936: [
                {"calendar": "2026", "series": "2", "title": "春号"}
            ],
        )
        monkeypatch.setattr(pdf_all_cli, "fetch_magazine", fake_fetch_magazine)
        monkeypatch.setattr(pdf_all_cli, "extract_page_ids", lambda magazine: ["0001", "0002"])
        monkeypatch.setattr(pdf_all_cli, "Progress", lambda: progress)
        monkeypatch.setattr(pdf_all_cli, "download_all_pages", fake_download_all_pages)

        exit_code = pdf_all_cli.main([])

        assert exit_code == 0
        assert refresh_calls == 1
        assert access_calls == ["api-1", "api-2"]
        assert magazine_calls == 2
        assert download_attempts == 2
        assert [client.closed for client in api_clients] == [True, True]
        assert download_client.closed is True

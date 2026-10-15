from __future__ import annotations

import json
from pathlib import Path

from scrape import auth


class TestRefreshCookieSource:
    def test_rewrites_json_cookie_file_from_chrome_db(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        cookie_file = tmp_path / "cookies.json"
        chrome_db = tmp_path / "Cookies"
        refresh_calls: list[Path] = []
        cookie_entries = [
            {
                "name": "ismuc",
                "value": "token",
                "domain": "toyokeizai.net",
                "path": "/",
            }
        ]

        def fake_refresh(*, cookies_db: Path, **kwargs) -> bool:
            refresh_calls.append(cookies_db)
            return True

        monkeypatch.setattr(auth, "refresh_cookies_via_chrome", fake_refresh)
        monkeypatch.setattr(auth, "load_toyokeizai_cookie_entries", lambda cookies_db=chrome_db: cookie_entries)

        assert auth.refresh_cookie_source(cookie_file, chrome_cookies_db=chrome_db) is True
        assert refresh_calls == [chrome_db]
        assert json.loads(cookie_file.read_text(encoding="utf-8")) == cookie_entries

    def test_keeps_existing_json_when_refresh_fails(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        cookie_file = tmp_path / "cookies.json"
        original = [{"name": "legacy", "value": "old", "domain": "toyokeizai.net", "path": "/"}]
        cookie_file.write_text(json.dumps(original), encoding="utf-8")

        monkeypatch.setattr(auth, "refresh_cookies_via_chrome", lambda **kwargs: False)

        assert auth.refresh_cookie_source(cookie_file) is False
        assert json.loads(cookie_file.read_text(encoding="utf-8")) == original

    def test_delegates_non_json_sources_to_chrome_refresh(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        cookie_db = tmp_path / "Cookies"
        refresh_calls: list[Path] = []

        def fake_refresh(*, cookies_db: Path, **kwargs) -> bool:
            refresh_calls.append(cookies_db)
            return True

        monkeypatch.setattr(auth, "refresh_cookies_via_chrome", fake_refresh)

        assert auth.refresh_cookie_source(cookie_db) is True
        assert refresh_calls == [cookie_db]

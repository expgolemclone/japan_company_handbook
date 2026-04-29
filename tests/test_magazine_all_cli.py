from __future__ import annotations

import json
from pathlib import Path

import httpx

from scrape.magazine.all_cli import main

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magazines"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_batch_client(call_counter: dict[str, int]) -> httpx.Client:
    issues_list = {
        "status": {"code": "2000", "message": "ok"},
        "magazines": [
            {"calendar": "1936", "series": "1", "title": "創刊号"},
            {"calendar": "2026", "series": "2", "title": "春号"},
        ],
    }
    raw_1936 = _load_json("1936_1.raw.json")
    raw_2026 = _load_json("2026_2.raw.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/files/v1/files/magazines/list":
            call_counter["list"] = call_counter.get("list", 0) + 1
            return httpx.Response(200, json=issues_list)
        if path == "/files/v1/files/magazines/1936/1":
            call_counter["1936_1"] = call_counter.get("1936_1", 0) + 1
            return httpx.Response(200, json=raw_1936)
        if path == "/files/v1/files/magazines/2026/2":
            call_counter["2026_2"] = call_counter.get("2026_2", 0) + 1
            return httpx.Response(200, json=raw_2026)
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

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api-shikiho.toyokeizai.net",
    )


class TestMagazineAllCli:
    def test_runs_batch_and_verifies_output(self, monkeypatch, tmp_path: Path) -> None:
        calls: dict[str, int] = {}

        def fake_client_builder(*args, **kwargs) -> httpx.Client:
            return _build_batch_client(calls)

        monkeypatch.setattr(
            "scrape.magazine.all_cli.build_magazine_http_client",
            fake_client_builder,
        )

        exit_code = main(["--out-dir", str(tmp_path), "--verify-after-run"])

        assert exit_code == 0
        verify_report = json.loads((tmp_path / "verify_report.json").read_text(encoding="utf-8"))
        assert verify_report["verified_complete"] is True
        assert verify_report["expected_issue_count"] == 2
        assert calls["list"] == 1
        assert calls["1936_1"] == 2
        assert calls["2026_2"] == 2

    def test_resume_skips_succeeded_issues(self, monkeypatch, tmp_path: Path) -> None:
        calls: dict[str, int] = {}

        def fake_client_builder(*args, **kwargs) -> httpx.Client:
            return _build_batch_client(calls)

        monkeypatch.setattr(
            "scrape.magazine.all_cli.build_magazine_http_client",
            fake_client_builder,
        )

        assert main(["--out-dir", str(tmp_path), "--verify-after-run"]) == 0
        assert main(["--out-dir", str(tmp_path), "--resume", "--verify-after-run"]) == 0

        assert calls["1936_1"] == 3
        assert calls["2026_2"] == 3
        assert calls["list"] == 2

    def test_writes_auth_diagnostics_and_exits_on_preflight_failure(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        calls: dict[str, int] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/files/v1/files/magazines/list":
                calls["list"] = calls.get("list", 0) + 1
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "2000", "message": "ok"},
                        "magazines": [
                            {"calendar": "1936", "series": "1", "title": "創刊号"},
                            {"calendar": "2026", "series": "2", "title": "春号"},
                        ],
                    },
                )
            if path == "/files/v1/files/magazines/1936/1":
                calls["1936_1"] = calls.get("1936_1", 0) + 1
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "1000", "message": "ok"},
                        "magazine": {},
                    },
                )
            if path == "/files/v1/files/magazines/2026/2":
                calls["2026_2"] = calls.get("2026_2", 0) + 1
                return httpx.Response(
                    200,
                    json={
                        "status": {"code": "1000", "message": "ok"},
                        "magazine": {},
                    },
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        def fake_client_builder(*args, **kwargs) -> httpx.Client:
            return httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api-shikiho.toyokeizai.net",
            )

        monkeypatch.setattr(
            "scrape.magazine.all_cli.build_magazine_http_client",
            fake_client_builder,
        )

        exit_code = main(["--out-dir", str(tmp_path), "--verify-after-run"])

        assert exit_code == 1
        diagnostics = json.loads((tmp_path / "auth_diagnostics.json").read_text(encoding="utf-8"))
        assert diagnostics["ok"] is False
        assert diagnostics["category_counts"]["payload_shape_error"] == 2
        assert not (tmp_path / "batch_progress.json").exists()

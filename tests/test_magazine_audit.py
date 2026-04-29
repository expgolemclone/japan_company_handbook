from __future__ import annotations

import json
from pathlib import Path

import httpx

from scrape.magazine.audit import build_auth_diagnostics, build_fact_check_report
from scrape.magazine.client import save_expected_issues
from scrape.magazine.types import MagazineIssueKey


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class TestBuildFactCheckReport:
    def test_reports_leading_gap_as_external_confirmed(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "issues.raw.json",
            {
                "status": {"code": "2000", "message": "ok"},
                "magazines": [
                    {"calendar": "1936", "series": "3", "title": "６月号"},
                    {"calendar": "1936", "series": "4", "title": "９月号"},
                ],
            },
        )
        save_expected_issues(
            [MagazineIssueKey("1936", "3"), MagazineIssueKey("1936", "4")],
            tmp_path / "issues.expected.json",
        )
        _write_json(
            tmp_path / "1936_3" / "manifest.raw.json",
            {
                "magazine": {
                    "title": "６月号",
                    "previousTitle": None,
                    "followingTitle": "９月号",
                }
            },
        )
        _write_json(
            tmp_path / "1936_4" / "manifest.raw.json",
            {
                "magazine": {
                    "title": "９月号",
                    "previousTitle": "６月号",
                    "followingTitle": "新春号",
                }
            },
        )

        report = build_fact_check_report(tmp_path)

        assert report["raw_expected_match"] is True
        assert report["first_issue"] == "1936_3"
        assert report["leading_missing_groups"] == [
            {
                "missing_issues": ["1936_1", "1936_2"],
                "adjacent_issues": {
                    "before_issue": None,
                    "after_issue": "1936_3",
                    "before_title": None,
                    "after_title": "６月号",
                },
                "assessment": "創刊年の先頭2号は公開書誌で存在が確認でき、API一覧の先頭欠落とみなせる。",
                "confidence": "high",
                "evidence_level": "external_confirmed",
                "sources": report["leading_missing_groups"][0]["sources"],
                "continuity_evidence": {
                    "before_following_title": None,
                    "after_previous_title": None,
                },
            }
        ]
        assert report["latest_year_status"]["assessment"] == "最終年は4集まで揃っている。"


class TestBuildAuthDiagnostics:
    def test_captures_permission_and_shape_errors(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/files/v1/files/magazines/list":
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
                    "status": {"code": "1000", "message": "ok"},
                    "magazine": {},
                },
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.example.test",
        )
        report, raw_issues, live_issues = build_auth_diagnostics(
            client,
            sample_issues=[MagazineIssueKey("1936", "3"), MagazineIssueKey("2026", "2")],
        )

        assert raw_issues is None
        assert live_issues == []
        assert report["ok"] is False
        assert report["category_counts"] == {
            "payload_permission_error": 1,
            "payload_shape_error": 2,
        }

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scrape.magazine.client import (
    AUTH_DIAGNOSTICS_FILE,
    AUTH_RELATED_PAYLOAD_SHAPE_MARKERS,
    EXPECTED_ISSUES_FILE,
    FACT_CHECK_REPORT_FILE,
    ISSUES_RAW_FILE,
    MAGAZINES_DIR,
    MagazineApiError,
    MagazineIssueKey,
    MagazinePayloadShapeError,
    MagazinePermissionError,
    extract_issue_refs,
    load_expected_issues,
    request_with_retries,
    validate_issue_list_payload,
    validate_magazine_issue_payload,
    validate_payload_status,
)

SOURCE_NDL_1936_1940 = {
    "title": "NDL: 会社四季報 昭和11年第1輯-昭和15年第4輯",
    "url": "https://ndlsearch.ndl.go.jp/books/R100000002-I000000707518",
    "note": "昭和11年第1輯至第2輯を含むと明記されており、1936_1 と 1936_2 の存在を確認できる。",
}
SOURCE_NDL_PLANGE = {
    "title": "NDL: 会社四季報 [1947年9月, 1948年2集, 1949年1-3集]",
    "url": "https://ndlsearch.ndl.go.jp/books/R100000002-I000007121299",
    "note": "1947年9月、1948年2集、1949年1-3集の断片所蔵を示す。所蔵欠と刊行欠は区別して扱う必要がある。",
}
SOURCE_NDL_DVD = {
    "title": "NDL: 会社四季報 [複製版]",
    "url": "https://ndlsearch.ndl.go.jp/books/R100000002-I000008353814",
    "note": "1936年創刊号から2006年3集までを収録対象として示す。",
}
SOURCE_JSRI = {
    "title": "証券図書館 利用の手引き",
    "url": "https://www.jsri.or.jp/libraries/",
    "note": "東洋経済デジタルコンテンツ・ライブラリーで『会社四季報』創刊号から最新号まで閲覧可能と案内している。",
}


def build_fact_check_report(out_dir: Path = MAGAZINES_DIR) -> dict[str, object]:
    issues_payload = _load_issues_payload(out_dir / ISSUES_RAW_FILE.name)
    observed_issues = extract_issue_refs(issues_payload)
    expected_issues = _load_expected_or_observed_issues(out_dir, issues_payload)
    manifests = _load_manifest_index(out_dir)

    if not observed_issues:
        raise ValueError("issues.raw.json に号一覧がありません")

    first_issue = observed_issues[0]
    last_issue = observed_issues[-1]
    expected_sequence = _build_expected_sequence(first_issue, last_issue)
    observed_slugs = {str(issue) for issue in observed_issues}
    missing_groups = _collect_missing_groups(expected_sequence, observed_slugs)
    raw_expected_match = [str(issue) for issue in observed_issues] == [
        str(issue) for issue in expected_issues
    ]

    leading_groups: list[dict[str, object]] = []
    interior_groups: list[dict[str, object]] = []
    for group in missing_groups:
        annotated = _annotate_missing_group(group, manifests)
        if group["before_issue"] is None:
            leading_groups.append(annotated)
        else:
            interior_groups.append(annotated)

    latest_year_status = _build_latest_year_status(issues_payload, last_issue)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_issue_file": str(out_dir / ISSUES_RAW_FILE.name),
        "expected_issue_file": str(out_dir / EXPECTED_ISSUES_FILE.name),
        "issue_count": len(observed_issues),
        "expected_issue_count": len(expected_issues),
        "raw_expected_match": raw_expected_match,
        "first_issue": str(first_issue),
        "last_issue": str(last_issue),
        "leading_missing_groups": leading_groups,
        "interior_missing_groups": interior_groups,
        "latest_year_status": latest_year_status,
        "notes": [
            "NDL の所蔵欠・所蔵範囲は刊行欠とは別に扱う。",
            "manifest.raw.json の previousTitle / followingTitle は内部連続性の補助証拠であり、単独では刊行有無を断定しない。",
        ],
    }


def build_auth_diagnostics(
    client: httpx.Client,
    *,
    sample_issues: list[MagazineIssueKey] | None = None,
    start_calendar: int = 1936,
) -> tuple[dict[str, object], dict[str, object] | None, list[MagazineIssueKey]]:
    checks: list[dict[str, object]] = []

    issue_list_entry, issues_payload = _probe_issue_list(client)
    checks.append(issue_list_entry)
    if not issue_list_entry["ok"]:
        issues_payload = None

    live_issues: list[MagazineIssueKey] = []
    selected_issues = list(sample_issues or [])
    if issues_payload is not None:
        live_issues = extract_issue_refs(issues_payload, start_calendar=start_calendar)
        if not selected_issues:
            selected_issues = _pick_sample_issues(live_issues)

    for issue in _dedupe_issue_keys(selected_issues):
        detail_entry, _ = _probe_issue_detail(client, issue)
        checks.append(detail_entry)

    counts = Counter(check["category"] for check in checks)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_issues": [str(issue) for issue in _dedupe_issue_keys(selected_issues)],
        "live_issue_count": len(live_issues),
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "category_counts": dict(sorted(counts.items())),
    }
    return report, issues_payload, live_issues


def write_fact_check_report(
    report: dict[str, object], path: Path = FACT_CHECK_REPORT_FILE
) -> None:
    _write_json(path, report)


def write_auth_diagnostics(
    report: dict[str, object], path: Path = AUTH_DIAGNOSTICS_FILE
) -> None:
    _write_json(path, report)


def should_refresh_for_auth_diagnostics(report: dict[str, object]) -> bool:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return False

    for check in checks:
        if not isinstance(check, dict) or bool(check.get("ok")):
            continue

        category = str(check.get("category", ""))
        if category == "payload_permission_error":
            return True
        if category == "payload_shape_error":
            error = str(check.get("error", ""))
            if any(marker in error for marker in AUTH_RELATED_PAYLOAD_SHAPE_MARKERS):
                return True
        if category == "http_status_error":
            http_status = check.get("http_status")
            try:
                if int(http_status) in {401, 403}:
                    return True
            except (TypeError, ValueError):
                continue

    return False


def load_local_sample_issues(out_dir: Path = MAGAZINES_DIR) -> list[MagazineIssueKey]:
    expected_path = out_dir / EXPECTED_ISSUES_FILE.name
    if expected_path.exists():
        return _pick_sample_issues(load_expected_issues(expected_path))

    raw_path = out_dir / ISSUES_RAW_FILE.name
    if raw_path.exists():
        payload = _load_issues_payload(raw_path)
        return _pick_sample_issues(extract_issue_refs(payload))

    return []


def _probe_issue_list(
    client: httpx.Client,
) -> tuple[dict[str, object], dict[str, object] | None]:
    return _probe_json_endpoint(
        client,
        name="issue_list",
        url="/files/v1/files/magazines/list",
        validator=lambda payload: (
            validate_payload_status(payload, endpoint="issue list"),
            validate_issue_list_payload(payload, endpoint="issue list"),
        ),
    )


def _probe_issue_detail(
    client: httpx.Client, issue: MagazineIssueKey
) -> tuple[dict[str, object], dict[str, object] | None]:
    return _probe_json_endpoint(
        client,
        name="issue_detail",
        url=f"/files/v1/files/magazines/{issue.calendar}/{issue.series}",
        issue=str(issue),
        validator=lambda payload: (
            validate_payload_status(payload, endpoint=str(issue)),
            validate_magazine_issue_payload(payload, endpoint=str(issue)),
        ),
    )


def _probe_json_endpoint(
    client: httpx.Client,
    *,
    name: str,
    url: str,
    validator,
    issue: str | None = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    entry: dict[str, object] = {
        "name": name,
        "url": url,
        "issue": issue,
        "ok": False,
        "category": "unknown",
    }

    try:
        response = request_with_retries(client, "GET", url)
    except httpx.TransportError as exc:
        entry["category"] = "transport_error"
        entry["error"] = str(exc)
        return entry, None

    entry["http_status"] = response.status_code
    entry["content_type"] = response.headers.get("content-type")
    body_preview = response.text[:300]
    if body_preview:
        entry["body_preview"] = body_preview

    if response.status_code >= 400:
        entry["category"] = "http_status_error"
        entry["error"] = f"HTTP {response.status_code}"
        return entry, None

    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        entry["category"] = "non_json_response"
        entry["error"] = f"JSONではないレスポンスです ({response.headers.get('content-type')})"
        return entry, None

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        entry["category"] = "invalid_json"
        entry["error"] = str(exc)
        return entry, None

    if not isinstance(payload, dict):
        entry["category"] = "non_object_json"
        entry["error"] = "JSONオブジェクトではありません"
        return entry, None

    entry["observed_keys"] = sorted(payload.keys())
    status = payload.get("status")
    if isinstance(status, dict):
        entry["payload_status"] = {
            "code": str(status.get("code", "")),
            "message": str(status.get("message", "")),
        }

    try:
        validator(payload)
    except MagazinePermissionError as exc:
        entry["category"] = "payload_permission_error"
        entry["error"] = str(exc)
        return entry, payload
    except MagazinePayloadShapeError as exc:
        entry["category"] = "payload_shape_error"
        entry["error"] = str(exc)
        return entry, payload
    except MagazineApiError as exc:
        entry["category"] = "payload_api_error"
        entry["error"] = str(exc)
        return entry, payload

    entry["ok"] = True
    entry["category"] = "ok"
    return entry, payload


def _load_issues_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"号一覧キャッシュが見つかりません: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"号一覧キャッシュの形式が不正です: {path}")
    return payload


def _load_expected_or_observed_issues(
    out_dir: Path, issues_payload: dict[str, object]
) -> list[MagazineIssueKey]:
    expected_path = out_dir / EXPECTED_ISSUES_FILE.name
    if expected_path.exists():
        return load_expected_issues(expected_path)
    return extract_issue_refs(issues_payload)


def _load_manifest_index(out_dir: Path) -> dict[str, dict[str, object]]:
    manifests: dict[str, dict[str, object]] = {}
    for path in sorted(out_dir.glob("*_*/manifest.raw.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        magazine = payload.get("magazine")
        if not isinstance(magazine, dict):
            continue
        manifests[path.parent.name] = {
            "title": magazine.get("title"),
            "previous_title": magazine.get("previousTitle"),
            "following_title": magazine.get("followingTitle"),
        }
    return manifests


def _build_expected_sequence(
    first_issue: MagazineIssueKey, last_issue: MagazineIssueKey
) -> list[str]:
    sequence: list[str] = []
    first_year = int(first_issue.calendar)
    last_year = int(last_issue.calendar)
    first_series = int(first_issue.series)
    last_series = int(last_issue.series)

    for year in range(first_year, last_year + 1):
        start = 1 if year != first_year else 1
        end = 4 if year != last_year else last_series
        for series in range(start, end + 1):
            sequence.append(f"{year}_{series}")
    return sequence


def _collect_missing_groups(
    expected_sequence: list[str], observed_slugs: set[str]
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    last_observed: str | None = None

    for slug in expected_sequence:
        if slug in observed_slugs:
            if current is not None:
                current["after_issue"] = slug
                groups.append(current)
                current = None
            last_observed = slug
            continue

        if current is None:
            current = {
                "missing_issues": [],
                "before_issue": last_observed,
                "after_issue": None,
            }
        current["missing_issues"].append(slug)

    if current is not None:
        groups.append(current)

    return groups


def _annotate_missing_group(
    group: dict[str, object], manifests: dict[str, dict[str, object]]
) -> dict[str, object]:
    missing_issues = list(group["missing_issues"])
    before_issue = group.get("before_issue")
    after_issue = group.get("after_issue")
    adjacent = {
        "before_issue": before_issue,
        "after_issue": after_issue,
        "before_title": _manifest_title(manifests, before_issue),
        "after_title": _manifest_title(manifests, after_issue),
    }

    if before_issue is None and missing_issues == ["1936_1", "1936_2"]:
        return {
            "missing_issues": missing_issues,
            "adjacent_issues": adjacent,
            "assessment": "創刊年の先頭2号は公開書誌で存在が確認でき、API一覧の先頭欠落とみなせる。",
            "confidence": "high",
            "evidence_level": "external_confirmed",
            "sources": [SOURCE_NDL_1936_1940, SOURCE_NDL_DVD, SOURCE_JSRI],
            "continuity_evidence": _build_continuity_evidence(
                manifests, before_issue, after_issue
            ),
        }

    wartime_or_postwar = any(
        1944 <= int(slug.split("_", 1)[0]) <= 1949 for slug in missing_issues
    )
    if wartime_or_postwar:
        return {
            "missing_issues": missing_issues,
            "adjacent_issues": adjacent,
            "assessment": "戦中戦後の欠落で、API未掲載・所蔵欠・刊行間引きのどれかは公開情報だけでは断定できない。",
            "confidence": "medium",
            "evidence_level": "mixed",
            "sources": [SOURCE_NDL_PLANGE, SOURCE_NDL_DVD, SOURCE_JSRI],
            "continuity_evidence": _build_continuity_evidence(
                manifests, before_issue, after_issue
            ),
        }

    return {
        "missing_issues": missing_issues,
        "adjacent_issues": adjacent,
        "assessment": "API一覧の内部欠落だが、公開書誌で刊行有無を未確認。",
        "confidence": "medium",
        "evidence_level": "internal_inferred",
        "sources": [SOURCE_NDL_DVD, SOURCE_JSRI],
        "continuity_evidence": _build_continuity_evidence(
            manifests, before_issue, after_issue
        ),
    }


def _build_latest_year_status(
    issues_payload: dict[str, object], last_issue: MagazineIssueKey
) -> dict[str, object]:
    magazines = issues_payload.get("magazines")
    latest_pub_date = None
    if isinstance(magazines, list):
        for item in magazines:
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("calendar")) == last_issue.calendar
                and str(item.get("series")) == last_issue.series
            ):
                latest_pub_date = item.get("pubDate")
                break

    last_year = int(last_issue.calendar)
    last_series = int(last_issue.series)
    remaining = [f"{last_year}_{series}" for series in range(last_series + 1, 5)]
    current_year = datetime.now(UTC).year
    if not remaining:
        assessment = "最終年は4集まで揃っている。"
        confidence = "high"
    elif last_year == current_year:
        assessment = "最終年は進行中の年なので、後続号は欠号扱いしない。"
        confidence = "high"
    else:
        assessment = "最終年が途中で止まっており、後続号の有無は別途確認が必要。"
        confidence = "medium"

    return {
        "observed_last_issue": str(last_issue),
        "latest_pub_date": latest_pub_date,
        "remaining_series_in_year": remaining,
        "assessment": assessment,
        "confidence": confidence,
    }


def _build_continuity_evidence(
    manifests: dict[str, dict[str, object]],
    before_issue: object,
    after_issue: object,
) -> dict[str, object]:
    before = manifests.get(str(before_issue)) if before_issue else None
    after = manifests.get(str(after_issue)) if after_issue else None
    return {
        "before_following_title": before.get("following_title") if before else None,
        "after_previous_title": after.get("previous_title") if after else None,
    }


def _manifest_title(
    manifests: dict[str, dict[str, object]], issue: object
) -> str | None:
    if issue is None:
        return None
    manifest = manifests.get(str(issue))
    if manifest is None:
        return None
    title = manifest.get("title")
    return str(title) if title else None


def _pick_sample_issues(issues: list[MagazineIssueKey]) -> list[MagazineIssueKey]:
    if not issues:
        return []
    if len(issues) == 1:
        return [issues[0]]
    return [issues[0], issues[-1]]


def _dedupe_issue_keys(issues: list[MagazineIssueKey]) -> list[MagazineIssueKey]:
    deduped: list[MagazineIssueKey] = []
    seen: set[str] = set()
    for issue in issues:
        slug = str(issue)
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(issue)
    return deduped


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrape.client import (
    ISSUES,
    Issue,
    SignedParams,
    build_pdf_url,
    load_signed_params,
    load_stock_codes,
)


class TestIssues:
    def test_has_four_issues(self) -> None:
        assert len(ISSUES) == 4

    def test_latest_issue(self) -> None:
        latest = ISSUES[-1]
        assert latest["calendar"] == "2026"
        assert latest["series"] == "2"
        assert latest["title"] == "春号"
        assert latest["pub_date"] == "20260318"


class TestBuildPdfUrl:
    def test_constructs_signed_url(self) -> None:
        params = SignedParams(
            Policy="test_policy",
            Signature="test_sig",
            Key_Pair_Id="test_key",
        )
        url = build_pdf_url("2026", "2", "332A", params)
        assert "files/shimen/basic/2026/2/332A.pdf" in url
        assert "Policy=test_policy" in url
        assert "Signature=test_sig" in url
        assert "Key-Pair-Id=test_key" in url


class TestLoadSignedParams:
    def test_loads_params_from_json(self, tmp_path: Path) -> None:
        params_file = tmp_path / "signed_params.json"
        params_file.write_text(
            json.dumps({
                "Policy": "test_policy",
                "Signature": "test_sig",
                "Key-Pair-Id": "test_key",
            }),
            encoding="utf-8",
        )
        params = load_signed_params(params_file)
        assert params["Policy"] == "test_policy"
        assert params["Signature"] == "test_sig"
        assert params["Key_Pair_Id"] == "test_key"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="署名パラメータ"):
            load_signed_params(tmp_path / "nonexistent.json")


class TestLoadStockCodes:
    def test_loads_codes_from_json(self, tmp_path: Path) -> None:
        (tmp_path / "stock_codes_2026_2.json").write_text(
            json.dumps(["1301", "332A", "7203"]),
            encoding="utf-8",
        )
        codes = load_stock_codes("2026", "2", data_dir=tmp_path)
        assert codes == ["1301", "332A", "7203"]

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="銘柄コード"):
            load_stock_codes("2099", "9", data_dir=tmp_path)

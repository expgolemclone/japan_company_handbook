from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scrape.magazine.types import MagazineIssueKey


class IssueProgress:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._state = self._load()

    @property
    def completed(self) -> bool:
        return bool(self._state["completed"])

    @property
    def expected_pages(self) -> list[str]:
        return list(self._state["expected_pages"])

    def page_state(self, page_id: str) -> dict[str, Any] | None:
        raw = self._state["pages"].get(page_id)
        return dict(raw) if isinstance(raw, dict) else None

    def is_downloaded(self, page_id: str) -> bool:
        state = self.page_state(page_id)
        return state is not None and state.get("status") == "completed"

    def completed_filename(self, page_id: str) -> str | None:
        state = self.page_state(page_id)
        if state is None:
            return None
        filename = state.get("filename")
        return str(filename) if filename else None

    def register_expected_pages(self, page_ids: list[str]) -> None:
        self._state["expected_pages"] = list(page_ids)
        self._sync_completed()
        self._save()

    def mark_downloaded(self, page_id: str, filename: str) -> None:
        self._state["pages"][page_id] = {
            "status": "completed",
            "filename": filename,
        }
        self._sync_completed()
        self._save()

    def mark_failed(self, page_id: str, reason: str) -> None:
        self._state["pages"][page_id] = {
            "status": "failed",
            "reason": reason,
        }
        self._sync_completed()
        self._save()

    def missing_pages(self) -> list[str]:
        return [
            page_id
            for page_id in self._state["expected_pages"]
            if not self.is_downloaded(page_id)
        ]

    def finalize(self) -> bool:
        self._sync_completed()
        self._save()
        return self.completed

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {
                "expected_pages": [],
                "pages": {},
                "completed": False,
            }

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {
            "expected_pages": list(raw.get("expected_pages", [])),
            "pages": dict(raw.get("pages", {})),
            "completed": bool(raw.get("completed", False)),
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _sync_completed(self) -> None:
        expected = self._state["expected_pages"]
        self._state["completed"] = bool(expected) and not self.missing_pages()


class BatchProgress:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._state = self._load()

    def status(self, issue: MagazineIssueKey) -> str:
        record = self._state["issues"].get(str(issue))
        if not isinstance(record, dict):
            return "pending"
        return str(record.get("status", "pending"))

    def error(self, issue: MagazineIssueKey) -> str | None:
        record = self._state["issues"].get(str(issue))
        if not isinstance(record, dict):
            return None
        error = record.get("error")
        return str(error) if error else None

    def is_succeeded(self, issue: MagazineIssueKey) -> bool:
        return self.status(issue) == "succeeded"

    def records(self) -> dict[str, dict[str, Any]]:
        return dict(self._state["issues"])

    def mark_running(self, issue: MagazineIssueKey) -> None:
        self._state["issues"][str(issue)] = {"status": "running", "error": None}
        self._save()

    def mark_succeeded(self, issue: MagazineIssueKey) -> None:
        self._state["issues"][str(issue)] = {"status": "succeeded", "error": None}
        self._save()

    def mark_failed(self, issue: MagazineIssueKey, error: str) -> None:
        self._state["issues"][str(issue)] = {"status": "failed", "error": error}
        self._save()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"issues": {}}

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return {"issues": dict(raw.get("issues", {}))}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

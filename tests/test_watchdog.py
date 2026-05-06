from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scrape.watchdog import WatchdogProfile, main, replace_existing_processes


def _profile(name: str, code: str, *, idle_seconds: float = 60.0) -> WatchdogProfile:
    return WatchdogProfile(
        name=name,
        command=(sys.executable, "-c", textwrap.dedent(code)),
        default_idle_seconds=idle_seconds,
        heartbeat_globs=("heartbeat.txt",),
    )


def _state_path(repo_root: Path, profile_name: str) -> Path:
    return repo_root / "data" / "watchdogs" / f"{profile_name}.json"


def _log_path(repo_root: Path, profile_name: str) -> Path:
    return repo_root / "data" / "watchdogs" / f"{profile_name}.log"


class TestWatchdog:
    def test_returns_zero_after_clean_exit(self, tmp_path: Path) -> None:
        profile = _profile(
            "clean",
            """
            from pathlib import Path
            Path("done.txt").write_text("ok", encoding="utf-8")
            """,
        )

        exit_code = main(
            ["clean", "--poll-seconds", "0.05", "--term-grace-seconds", "0.2"],
            repo_root=tmp_path,
            install_signal_handlers=False,
            profiles={"clean": profile},
        )

        assert exit_code == 0
        assert (tmp_path / "done.txt").read_text(encoding="utf-8") == "ok"

        state = json.loads(_state_path(tmp_path, "clean").read_text(encoding="utf-8"))
        assert state["restart_count"] == 0
        assert state["last_exit_code"] == 0
        assert state["pid"] is None

    def test_restarts_after_nonzero_exit_and_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("scrape.watchdog.BACKOFF_SCHEDULE", (0.01,))

        profile = _profile(
            "retry-on-exit",
            """
            from pathlib import Path
            attempts_path = Path("attempts.txt")
            attempts = int(attempts_path.read_text(encoding="utf-8")) if attempts_path.exists() else 0
            attempts += 1
            attempts_path.write_text(str(attempts), encoding="utf-8")
            raise SystemExit(1 if attempts == 1 else 0)
            """,
        )

        exit_code = main(
            ["retry-on-exit", "--poll-seconds", "0.05", "--term-grace-seconds", "0.2"],
            repo_root=tmp_path,
            install_signal_handlers=False,
            profiles={"retry-on-exit": profile},
        )

        assert exit_code == 0
        assert (tmp_path / "attempts.txt").read_text(encoding="utf-8") == "2"

        state = json.loads(_state_path(tmp_path, "retry-on-exit").read_text(encoding="utf-8"))
        assert state["restart_count"] == 1
        assert state["last_exit_code"] == 0
        assert state["last_restart_reason"] is None

        log_text = _log_path(tmp_path, "retry-on-exit").read_text(encoding="utf-8")
        assert "start:" in log_text

    def test_restarts_when_heartbeat_stalls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("scrape.watchdog.BACKOFF_SCHEDULE", (0.01,))

        profile = _profile(
            "retry-on-stall",
            """
            from pathlib import Path
            import time

            attempts_path = Path("attempts.txt")
            attempts = int(attempts_path.read_text(encoding="utf-8")) if attempts_path.exists() else 0
            attempts += 1
            attempts_path.write_text(str(attempts), encoding="utf-8")

            heartbeat = Path("heartbeat.txt")
            heartbeat.write_text(str(attempts), encoding="utf-8")

            if attempts == 1:
                time.sleep(60)
            """,
            idle_seconds=0.2,
        )

        exit_code = main(
            [
                "retry-on-stall",
                "--idle-seconds",
                "0.2",
                "--poll-seconds",
                "0.05",
                "--term-grace-seconds",
                "0.2",
            ],
            repo_root=tmp_path,
            install_signal_handlers=False,
            profiles={"retry-on-stall": profile},
        )

        assert exit_code == 0
        assert (tmp_path / "attempts.txt").read_text(encoding="utf-8") == "2"

        state = json.loads(_state_path(tmp_path, "retry-on-stall").read_text(encoding="utf-8"))
        assert state["restart_count"] == 1
        assert state["last_exit_code"] == 0

        log_text = _log_path(tmp_path, "retry-on-stall").read_text(encoding="utf-8")
        assert log_text.count("[watchdog]") == 2

    def test_replaces_only_matching_process_in_same_repo(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()

        command = (
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        )
        proc_a = subprocess.Popen(command, cwd=repo_a, start_new_session=True)
        proc_b = subprocess.Popen(command, cwd=repo_b, start_new_session=True)

        try:
            replaced = replace_existing_processes(
                command,
                repo_root=repo_a,
                term_grace_seconds=0.2,
            )

            assert replaced == [proc_a.pid]
            proc_a.wait(timeout=5)
            assert proc_b.poll() is None
        finally:
            if proc_a.poll() is None:
                os.killpg(proc_a.pid, signal.SIGKILL)
                proc_a.wait(timeout=5)
            if proc_b.poll() is None:
                os.killpg(proc_b.pid, signal.SIGKILL)
                proc_b.wait(timeout=5)

    def test_rejects_second_watchdog_instance_when_lock_is_held(self, tmp_path: Path) -> None:
        profile = _profile(
            "locked",
            """
            raise SystemExit(0)
            """,
        )

        lock_dir = tmp_path / "data" / "watchdogs"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "locked.lock"

        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            exit_code = main(
                ["locked"],
                repo_root=tmp_path,
                install_signal_handlers=False,
                profiles={"locked": profile},
            )

        assert exit_code == 1

    def test_wrapper_scripts_delegate_to_watchdog(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        pdf_wrapper = (
            repo_root / "scripts" / "watch-shikiho-pdf-all"
        ).read_text(encoding="utf-8")
        magazine_wrapper = (
            repo_root / "scripts" / "watch-shikiho-magazine-all"
        ).read_text(encoding="utf-8")
        legacy_pdf_wrapper = (repo_root / "scripts" / "watch-scrape").read_text(encoding="utf-8")
        legacy_magazine_wrapper = (
            repo_root / "scripts" / "watch-scrape-magazine-all"
        ).read_text(encoding="utf-8")

        assert "python -m scrape.watchdog shikiho-pdf-all " in pdf_wrapper
        assert "python -m scrape.watchdog shikiho-magazine-all " in magazine_wrapper
        assert "watch-shikiho-pdf-all" in legacy_pdf_wrapper
        assert "watch-shikiho-magazine-all" in legacy_magazine_wrapper
        assert "exit 2" in legacy_pdf_wrapper
        assert "exit 2" in legacy_magazine_wrapper

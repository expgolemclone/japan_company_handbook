from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

BACKOFF_SCHEDULE = (10.0, 20.0, 40.0, 80.0, 160.0, 300.0)
HEALTHY_RUNTIME_RESET_SECONDS = 600.0
DEFAULT_LOG_DIR = Path("data/watchdogs")
DEFAULT_STATE_DIR = Path("data/watchdogs")
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class WatchdogProfile:
    name: str
    command: tuple[str, ...]
    default_idle_seconds: float
    heartbeat_globs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    pgid: int
    uid: int
    cwd: Path
    argv: tuple[str, ...]


@dataclass(slots=True)
class SignalState:
    received_signal: int | None = None


PROFILES: dict[str, WatchdogProfile] = {
    "scrape": WatchdogProfile(
        name="scrape",
        command=("uv", "run", "scrape"),
        default_idle_seconds=900.0,
        heartbeat_globs=("data/progress.json",),
    ),
    "scrape-magazine-all": WatchdogProfile(
        name="scrape-magazine-all",
        command=("uv", "run", "scrape-magazine-all", "--resume", "--verify-after-run"),
        default_idle_seconds=1800.0,
        heartbeat_globs=(
            "data/magazines/issues.raw.json",
            "data/magazines/issues.expected.json",
            "data/magazines/batch_progress.json",
            "data/magazines/batch_summary.json",
            "data/magazines/verify_report.json",
            "data/magazines/*/progress.json",
        ),
    ),
}


def build_parser(profiles: dict[str, WatchdogProfile] | None = None) -> argparse.ArgumentParser:
    available = profiles or PROFILES
    parser = argparse.ArgumentParser(description="scrape 系 CLI を監視して再起動する")
    parser.add_argument("profile", choices=sorted(available))
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=None,
        help="heartbeat 停止と見なす秒数",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=30.0,
        help="heartbeat と child 終了を確認する間隔",
    )
    parser.add_argument(
        "--term-grace-seconds",
        type=float,
        default=30.0,
        help="SIGTERM 後に SIGKILL へ切り替えるまでの待機秒数",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="child log の保存先",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help="lock/state ファイルの保存先",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    repo_root: Path | None = None,
    install_signal_handlers: bool = True,
    signal_state: SignalState | None = None,
    profiles: dict[str, WatchdogProfile] | None = None,
) -> int:
    _configure_logging()
    available = profiles or PROFILES
    parser = build_parser(available)
    args = parser.parse_args(argv)

    active_repo_root = repo_root or REPO_ROOT
    active_signal_state = signal_state or SignalState()
    if install_signal_handlers:
        _install_signal_handlers(active_signal_state)

    profile = available[args.profile]
    idle_seconds = (
        profile.default_idle_seconds
        if args.idle_seconds is None
        else args.idle_seconds
    )
    try:
        return run_watchdog(
            profile,
            repo_root=active_repo_root,
            idle_seconds=idle_seconds,
            poll_seconds=args.poll_seconds,
            term_grace_seconds=args.term_grace_seconds,
            log_dir=_resolve_path(active_repo_root, args.log_dir),
            state_dir=_resolve_path(active_repo_root, args.state_dir),
            signal_state=active_signal_state,
        )
    except LockAcquisitionError as exc:
        logger.error(str(exc))
        return 1


def run_watchdog(
    profile: WatchdogProfile,
    *,
    repo_root: Path,
    idle_seconds: float,
    poll_seconds: float,
    term_grace_seconds: float,
    log_dir: Path,
    state_dir: Path,
    signal_state: SignalState,
) -> int:
    repo_root = repo_root.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / f"{profile.name}.log"
    state_path = state_dir / f"{profile.name}.json"
    lock_path = state_dir / f"{profile.name}.lock"

    restart_count = 0
    restart_streak = 0
    last_exit_code: int | None = None
    last_restart_reason: str | None = None

    with acquire_profile_lock(lock_path):
        replaced = replace_existing_processes(
            profile.command,
            repo_root=repo_root,
            term_grace_seconds=term_grace_seconds,
        )
        if replaced:
            logger.info(
                "replaced existing process groups for %s: %s",
                profile.name,
                ", ".join(str(pid) for pid in replaced),
            )

        while True:
            if signal_state.received_signal is not None:
                _write_state(
                    state_path,
                    profile=profile,
                    pid=None,
                    pgid=None,
                    started_at=None,
                    last_heartbeat_at=_isoformat_timestamp(_latest_heartbeat_timestamp(repo_root, profile, log_path)),
                    restart_count=restart_count,
                    last_exit_code=last_exit_code,
                    last_restart_reason="signal",
                )
                return 128 + signal_state.received_signal

            process, log_handle = _start_child(profile.command, repo_root, log_path)
            started_wall = _time_now()
            started_mono = _monotonic_now()
            logger.info("started %s pid=%s", profile.name, process.pid)

            _write_state(
                state_path,
                profile=profile,
                pid=process.pid,
                pgid=process.pid,
                started_at=_isoformat_timestamp(started_wall),
                last_heartbeat_at=_isoformat_timestamp(_latest_heartbeat_timestamp(repo_root, profile, log_path)),
                restart_count=restart_count,
                last_exit_code=last_exit_code,
                last_restart_reason=last_restart_reason,
            )

            restart_reason: str | None = None
            exit_code: int | None = None

            try:
                while True:
                    if signal_state.received_signal is not None:
                        exit_code = _terminate_child(process, term_grace_seconds)
                        last_exit_code = exit_code
                        _write_state(
                            state_path,
                            profile=profile,
                            pid=None,
                            pgid=None,
                            started_at=_isoformat_timestamp(started_wall),
                            last_heartbeat_at=_isoformat_timestamp(_latest_heartbeat_timestamp(repo_root, profile, log_path)),
                            restart_count=restart_count,
                            last_exit_code=last_exit_code,
                            last_restart_reason="signal",
                        )
                        return 128 + signal_state.received_signal

                    exit_code = process.poll()
                    heartbeat_ts = _latest_heartbeat_timestamp(repo_root, profile, log_path)
                    _write_state(
                        state_path,
                        profile=profile,
                        pid=process.pid if exit_code is None else None,
                        pgid=process.pid if exit_code is None else None,
                        started_at=_isoformat_timestamp(started_wall),
                        last_heartbeat_at=_isoformat_timestamp(heartbeat_ts),
                        restart_count=restart_count,
                        last_exit_code=last_exit_code,
                        last_restart_reason=last_restart_reason,
                    )

                    if exit_code is not None:
                        if exit_code == 0:
                            last_exit_code = 0
                            last_restart_reason = None
                            _write_state(
                                state_path,
                                profile=profile,
                                pid=None,
                                pgid=None,
                                started_at=_isoformat_timestamp(started_wall),
                                last_heartbeat_at=_isoformat_timestamp(heartbeat_ts),
                                restart_count=restart_count,
                                last_exit_code=0,
                                last_restart_reason=None,
                            )
                            logger.info("%s exited cleanly", profile.name)
                            return 0

                        last_exit_code = exit_code
                        restart_reason = f"exit_code:{exit_code}"
                        logger.warning("%s exited with code %s", profile.name, exit_code)
                        break

                    reference_ts = heartbeat_ts or started_wall
                    heartbeat_age = _time_now() - reference_ts
                    if heartbeat_age > idle_seconds:
                        logger.warning(
                            "%s heartbeat stalled for %.1f seconds; restarting",
                            profile.name,
                            heartbeat_age,
                        )
                        exit_code = _terminate_child(process, term_grace_seconds)
                        last_exit_code = exit_code
                        restart_reason = "heartbeat_stalled"
                        break

                    _sleep_interruptible(poll_seconds, signal_state)
            finally:
                log_handle.close()

            runtime = _monotonic_now() - started_mono
            if runtime >= HEALTHY_RUNTIME_RESET_SECONDS:
                restart_streak = 0

            delay_seconds = _restart_delay(restart_streak)
            restart_streak += 1
            restart_count += 1
            last_restart_reason = restart_reason

            _write_state(
                state_path,
                profile=profile,
                pid=None,
                pgid=None,
                started_at=_isoformat_timestamp(started_wall),
                last_heartbeat_at=_isoformat_timestamp(_latest_heartbeat_timestamp(repo_root, profile, log_path)),
                restart_count=restart_count,
                last_exit_code=last_exit_code,
                last_restart_reason=last_restart_reason,
            )

            if signal_state.received_signal is not None:
                return 128 + signal_state.received_signal

            logger.info(
                "restart %s after %.1f seconds (reason=%s, restart_count=%s)",
                profile.name,
                delay_seconds,
                restart_reason,
                restart_count,
            )
            _sleep_interruptible(delay_seconds, signal_state)


def replace_existing_processes(
    command: tuple[str, ...],
    *,
    repo_root: Path,
    term_grace_seconds: float,
) -> list[int]:
    current_pid = os.getpid()
    groups: dict[int, ProcessInfo] = {}

    for info in iter_matching_processes(command, repo_root=repo_root):
        if info.pid == current_pid:
            continue
        groups.setdefault(info.pgid, info)

    replaced: list[int] = []
    for info in groups.values():
        _terminate_process_group(info.pid, info.pgid, term_grace_seconds)
        replaced.append(info.pid)

    return sorted(replaced)


def iter_matching_processes(
    command: tuple[str, ...],
    *,
    repo_root: Path,
) -> Iterator[ProcessInfo]:
    repo_root = repo_root.resolve()
    current_uid = os.getuid()

    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue

        try:
            info = read_process_info(int(proc_dir.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue

        if info.uid != current_uid:
            continue
        if info.cwd != repo_root:
            continue
        if info.argv != command:
            continue

        yield info


def read_process_info(pid: int) -> ProcessInfo:
    proc_dir = Path("/proc") / str(pid)
    cmdline = (proc_dir / "cmdline").read_bytes()
    argv = tuple(part.decode("utf-8") for part in cmdline.split(b"\0") if part)
    if not argv:
        raise ValueError(f"empty argv: {pid}")

    cwd = Path(os.readlink(proc_dir / "cwd")).resolve()
    status_lines = (proc_dir / "status").read_text(encoding="utf-8").splitlines()
    stat_fields = (proc_dir / "stat").read_text(encoding="utf-8").split()

    uid: int | None = None
    pgid: int | None = None
    for line in status_lines:
        if line.startswith("Uid:"):
            uid = int(line.split()[1])
            continue
        if line.startswith("NSpgid:"):
            pgid = int(line.split()[1])
            continue

    if pgid is None and len(stat_fields) >= 5:
        pgid = int(stat_fields[4])

    if uid is None or pgid is None:
        raise ValueError(f"missing uid/pgid: {pid}")

    return ProcessInfo(pid=pid, pgid=pgid, uid=uid, cwd=cwd, argv=argv)


class LockAcquisitionError(RuntimeError):
    pass


@contextmanager
def acquire_profile_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockAcquisitionError(f"watchdog lock is already held: {path}") from exc
        yield


def _start_child(
    command: tuple[str, ...],
    repo_root: Path,
    log_path: Path,
) -> tuple[subprocess.Popen[str], object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    started_at = datetime.now(UTC).isoformat()
    handle.write(f"[watchdog] {started_at} start: {' '.join(command)}\n")
    handle.flush()

    process = subprocess.Popen(
        list(command),
        cwd=repo_root,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    return process, handle


def _terminate_child(process: subprocess.Popen[str], term_grace_seconds: float) -> int | None:
    return _terminate_process_group(process.pid, process.pid, term_grace_seconds, process=process)


def _terminate_process_group(
    pid: int,
    pgid: int,
    term_grace_seconds: float,
    *,
    process: subprocess.Popen[str] | None = None,
) -> int | None:
    if not _pid_exists(pid):
        return process.poll() if process is not None else None

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return process.poll() if process is not None else None

    deadline = _monotonic_now() + term_grace_seconds
    while _monotonic_now() < deadline:
        if not _pid_exists(pid):
            return process.poll() if process is not None else None
        if process is not None and process.poll() is not None:
            return process.poll()
        time.sleep(0.1)  # noqa: scrape-interval

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return process.poll() if process is not None else None

    kill_deadline = _monotonic_now() + max(term_grace_seconds, 1.0)
    while _monotonic_now() < kill_deadline:
        if not _pid_exists(pid):
            return process.poll() if process is not None else None
        if process is not None and process.poll() is not None:
            return process.poll()
        time.sleep(0.1)  # noqa: scrape-interval

    return process.poll() if process is not None else None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.debug("pid %d は存在しません", pid)
        return False
    except PermissionError:
        logger.debug("pid %d は存在しますが権限がありません", pid)
        return True
    return True


def _latest_heartbeat_timestamp(
    repo_root: Path,
    profile: WatchdogProfile,
    log_path: Path,
) -> float | None:
    latest: float | None = None

    for candidate in _heartbeat_paths(repo_root, profile, log_path):
        try:
            mtime = candidate.stat().st_mtime
        except FileNotFoundError:
            continue
        latest = mtime if latest is None else max(latest, mtime)

    return latest


def _heartbeat_paths(
    repo_root: Path,
    profile: WatchdogProfile,
    log_path: Path,
) -> Iterator[Path]:
    yield log_path
    for pattern in profile.heartbeat_globs:
        yield from repo_root.glob(pattern)


def _restart_delay(restart_streak: int) -> float:
    index = min(restart_streak, len(BACKOFF_SCHEDULE) - 1)
    return BACKOFF_SCHEDULE[index]


def _sleep_interruptible(seconds: float, signal_state: SignalState) -> None:
    deadline = _monotonic_now() + max(seconds, 0.0)
    while _monotonic_now() < deadline:
        if signal_state.received_signal is not None:
            return
        remaining = deadline - _monotonic_now()
        time.sleep(min(0.5, max(remaining, 0.0)))


def _write_state(
    path: Path,
    *,
    profile: WatchdogProfile,
    pid: int | None,
    pgid: int | None,
    started_at: str | None,
    last_heartbeat_at: str | None,
    restart_count: int,
    last_exit_code: int | None,
    last_restart_reason: str | None,
) -> None:
    payload = {
        "profile": profile.name,
        "command": list(profile.command),
        "pid": pid,
        "pgid": pgid,
        "started_at": started_at,
        "last_heartbeat_at": last_heartbeat_at,
        "restart_count": restart_count,
        "last_exit_code": last_exit_code,
        "last_restart_reason": last_restart_reason,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(path, payload)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _install_signal_handlers(signal_state: SignalState) -> None:
    def handler(signum: int, _frame: object) -> None:
        signal_state.received_signal = signum

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _isoformat_timestamp(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def _time_now() -> float:
    return time.time()


def _monotonic_now() -> float:
    return time.monotonic()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(main())

"""
Minimal watchdog for the taiji yin/yang loop.

This process keeps relaunching `python -m taiji.loop` until a stop file
is created. It mirrors the older autoloop supervisor, but targets the
yin/yang runner and its queue paths.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .cycle import dual_loop_paths
from .schema import ROOT

DEFAULT_LOOP_ARGS = (
    "--iterations",
    "-1",
    "--resume-yang-session",
)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def timestamp_for_filename() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def log_line(log_path: Path, message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiji watch process for the yin/yang loop")
    parser.add_argument("--unit-root", "--env-root", dest="env_root", type=Path, required=True, help="Unit root for the yin/yang unit")
    parser.add_argument("--python-executable", default=sys.executable, help="Python executable used for child restarts")
    parser.add_argument("--stop-path", type=Path, default=None, help="Create this file to stop the supervisor")
    parser.add_argument("--child-pid-path", type=Path, default=None, help="Path that tracks the live loop child pid")
    parser.add_argument("--supervisor-pid-path", type=Path, default=None, help="Path that tracks the watch pid")
    parser.add_argument("--supervisor-log-path", type=Path, default=None, help="Append-only watch log path")
    parser.add_argument("--restart-delay-sec", type=float, default=5.0, help="Base delay before restarting a crashed child")
    parser.add_argument("--restart-delay-max-sec", type=float, default=60.0, help="Maximum backoff delay after repeated fast child exits")
    parser.add_argument("--poll-sec", type=float, default=2.0, help="Polling interval for child exit or stop-file detection")
    parser.add_argument("--fast-exit-sec", type=float, default=30.0, help="Treat exits before this runtime as fast failures and back off restarts")
    parser.add_argument(
        "loop_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed to taiji.loop after --. These are appended after the default args.",
    )
    return parser


def normalize_remainder_args(raw_args: list[str]) -> list[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def build_child_command(args: argparse.Namespace) -> list[str]:
    extra_args = normalize_remainder_args(args.loop_args)
    return [
        args.python_executable,
        "-u",
        "-m",
        "taiji.loop",
        "--unit-root",
        str(args.env_root),
        *DEFAULT_LOOP_ARGS,
        *extra_args,
    ]


def default_queue_path(queue_root: Path, primary_name: str, legacy_name: str) -> Path:
    primary_path = queue_root / primary_name
    legacy_path = queue_root / legacy_name
    if legacy_path.exists() and not primary_path.exists():
        return legacy_path
    return primary_path


def create_child_logs(queue_root: Path) -> tuple[Path, Path]:
    stamp = timestamp_for_filename()
    stdout_path = queue_root / f"loop-{stamp}.log"
    stderr_path = queue_root / f"loop-{stamp}.err.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    return stdout_path, stderr_path


def sleep_with_stop(stop_path: Path, delay_sec: float, poll_sec: float) -> bool:
    deadline = time.monotonic() + max(0.0, delay_sec)
    while time.monotonic() < deadline:
        if stop_path.exists():
            return True
        time.sleep(min(poll_sec, max(0.0, deadline - time.monotonic())))
    return stop_path.exists()


def terminate_child(proc: subprocess.Popen[str], stop_path: Path, child_pid_path: Path, log_path: Path) -> None:
    if proc.poll() is not None:
        if child_pid_path.exists():
            child_pid_path.unlink()
        return

    log_line(log_path, f"Stopping child pid={proc.pid}.")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        log_line(log_path, f"Child pid={proc.pid} did not exit after terminate(); killing it.")
        proc.kill()
        proc.wait(timeout=15)

    if child_pid_path.exists():
        child_pid_path.unlink()
    if stop_path.exists():
        stop_path.unlink()


def main() -> None:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    paths = dual_loop_paths(args.env_root)
    queue_root = paths.queue_root
    queue_root.mkdir(parents=True, exist_ok=True)

    if args.stop_path is None:
        args.stop_path = default_queue_path(queue_root, "loop.stop", "dual_autoloop.stop")
    if args.child_pid_path is None:
        args.child_pid_path = default_queue_path(queue_root, "loop.pid", "dual_autoloop.pid")
    if args.supervisor_pid_path is None:
        args.supervisor_pid_path = default_queue_path(queue_root, "watch.pid", "dual-autoloop-supervisor.pid")
    if args.supervisor_log_path is None:
        args.supervisor_log_path = default_queue_path(queue_root, "watch.log", "dual-autoloop-supervisor.log")
    current_run_path = queue_root / "current-run.json"

    args.stop_path.parent.mkdir(parents=True, exist_ok=True)
    args.supervisor_pid_path.parent.mkdir(parents=True, exist_ok=True)
    args.child_pid_path.parent.mkdir(parents=True, exist_ok=True)
    args.supervisor_pid_path.write_text(str(os.getpid()), encoding="utf-8")
    if args.stop_path.exists():
        args.stop_path.unlink()

    child_command = build_child_command(args)
    log_line(args.supervisor_log_path, f"Supervisor started with child command: {' '.join(child_command)}")

    restart_delay = max(0.0, args.restart_delay_sec)
    active_child: subprocess.Popen[str] | None = None
    try:
        while True:
            if args.stop_path.exists():
                log_line(args.supervisor_log_path, "Stop file detected before launch. Exiting supervisor.")
                break

            stdout_path, stderr_path = create_child_logs(queue_root)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with stdout_path.open("w", encoding="utf-8", errors="backslashreplace") as stdout_handle, stderr_path.open(
                "w",
                encoding="utf-8",
                errors="backslashreplace",
            ) as stderr_handle:
                started_at = time.monotonic()
                child = subprocess.Popen(
                    child_command,
                    cwd=ROOT,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    creationflags=creationflags,
                )
                active_child = child
                args.child_pid_path.write_text(str(child.pid), encoding="utf-8")
                write_payload = {
                    "supervisor_pid": os.getpid(),
                    "pid": child.pid,
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                    "state": str(queue_root / "loop_state.json"),
                    "pid_file": str(args.child_pid_path),
                    "supervisor_pid_file": str(args.supervisor_pid_path),
                    "supervisor_log": str(args.supervisor_log_path),
                }
                current_run_path.write_text(
                    json.dumps(write_payload, indent=2) + "\n",
                    encoding="utf-8",
                )
                log_line(
                    args.supervisor_log_path,
                    f"Launched child pid={child.pid} stdout={stdout_path.name} stderr={stderr_path.name}",
                )

                while True:
                    if args.stop_path.exists():
                        terminate_child(child, args.stop_path, args.child_pid_path, args.supervisor_log_path)
                        log_line(args.supervisor_log_path, "Supervisor stopped by stop file.")
                        return

                    exit_code = child.poll()
                    if exit_code is not None:
                        runtime_sec = time.monotonic() - started_at
                        if args.child_pid_path.exists():
                            args.child_pid_path.unlink()
                        active_child = None
                        log_line(
                            args.supervisor_log_path,
                            f"Child pid={child.pid} exited with code {exit_code} after {runtime_sec:.1f}s.",
                        )
                        if runtime_sec < args.fast_exit_sec:
                            restart_delay = min(
                                args.restart_delay_max_sec,
                                max(args.restart_delay_sec, restart_delay * 2 or args.restart_delay_sec),
                            )
                        else:
                            restart_delay = max(0.0, args.restart_delay_sec)
                        break

                    time.sleep(max(0.1, args.poll_sec))

            if sleep_with_stop(args.stop_path, restart_delay, args.poll_sec):
                log_line(args.supervisor_log_path, "Stop file detected during restart delay. Exiting supervisor.")
                if args.stop_path.exists():
                    args.stop_path.unlink()
                break

            log_line(args.supervisor_log_path, f"Restarting child after {restart_delay:.1f}s delay.")
    except KeyboardInterrupt:
        log_line(args.supervisor_log_path, "Supervisor interrupted. Terminating active child.")
        if active_child is not None:
            terminate_child(active_child, args.stop_path, args.child_pid_path, args.supervisor_log_path)
    finally:
        if active_child is not None and active_child.poll() is None:
            terminate_child(active_child, args.stop_path, args.child_pid_path, args.supervisor_log_path)
        if args.child_pid_path.exists():
            args.child_pid_path.unlink()
        if args.supervisor_pid_path.exists():
            args.supervisor_pid_path.unlink()


if __name__ == "__main__":
    main()

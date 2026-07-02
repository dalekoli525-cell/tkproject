# -*- coding: utf-8 -*-

"""Worker entrypoint.

The first production-safe step is an observable local worker loop. It reads the
local task state that the current desktop client writes, reports queue counts,
and exits cleanly on Ctrl+C or container SIGTERM. The actual distributed queue
consumer can replace LocalTaskObserver without changing the process contract.
"""

from __future__ import annotations

import argparse
import json
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Iterable

from loguru import logger

from APP.SHARED.settings import ROOT_DIR
from APP.SHARED.settings import settings


TASK_STATE_FILE = ROOT_DIR / "runtime" / "client_state" / "collect_tasks.json"
STOP_EVENT = Event()


@dataclass(frozen=True)
class TaskSnapshot:
    total: int
    pending: int
    running: int
    finished: int
    failed: int


def _status_of(task: dict) -> str:
    return str(
        task.get("status")
        or task.get("task_status")
        or task.get("state")
        or "PENDING"
    ).upper()


def _read_tasks(path: Path) -> list[dict]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("无法读取任务状态文件 {}：{}", path, exc)
        return []

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("tasks", [])
    else:
        rows = []

    return [row for row in rows if isinstance(row, dict)]


def _count(statuses: Iterable[str], names: set[str]) -> int:
    return sum(1 for status in statuses if status in names)


class LocalTaskObserver:
    """Read-only observer for the current local task JSON file."""

    def __init__(self, task_state_file: Path = TASK_STATE_FILE):
        self.task_state_file = task_state_file

    def poll_once(self) -> TaskSnapshot:
        tasks = _read_tasks(self.task_state_file)
        statuses = [_status_of(task) for task in tasks]
        snapshot = TaskSnapshot(
            total=len(tasks),
            pending=_count(statuses, {"NEW", "PENDING", "QUEUED"}),
            running=_count(statuses, {"RUNNING", "STARTED", "IN_PROGRESS"}),
            finished=_count(statuses, {"DONE", "FINISHED", "SUCCESS", "COMPLETED"}),
            failed=_count(statuses, {"FAILED", "ERROR"}),
        )
        logger.info(
            "任务快照：总数={} 待处理={} 运行中={} 已完成={} 失败={}",
            snapshot.total,
            snapshot.pending,
            snapshot.running,
            snapshot.finished,
            snapshot.failed,
        )
        return snapshot


def _handle_stop(signum, _frame) -> None:
    logger.info("Worker 收到停止信号 {}", signum)
    STOP_EVENT.set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TK AI CRM Worker")
    parser.add_argument("--once", action="store_true", help="只轮询一次后退出")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="本地任务轮询间隔秒数",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interval = max(5, int(args.poll_seconds))

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "Worker 已启动；并发数={} 模式=本地观察器 任务文件={}",
        settings.worker_concurrency,
        TASK_STATE_FILE,
    )
    observer = LocalTaskObserver()

    while not STOP_EVENT.is_set():
        observer.poll_once()
        if args.once:
            break
        STOP_EVENT.wait(interval)

    logger.info("Worker 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""所有顶层任务共用的总运行时间保护。"""

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import tempfile
import time
from typing import BinaryIO

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.tasker import Tasker, TaskerEventSink

from utils.logger import logger


@dataclass
class _TaskState:
    entry: str
    started_at: float
    max_seconds: int
    timer: threading.Timer
    lease: BinaryIO
    timed_out: bool = False
    stopping: bool = False


class _TaskExecutionGuardCore:
    """在 Tasker 与 Context 两类事件接收器之间共享超时状态。"""

    DEFAULT_MAX_SECONDS = 2 * 60 * 60
    ENTRY_TIMEOUTS = {
        "sanjieqiyuan": 20 * 60,
        "kejuxiangshi": 20 * 60,
        "zhuogui_hundui": 8 * 60 * 60,
        "my_task": 8 * 60 * 60,
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[int, _TaskState] = {}

    @staticmethod
    def _acquire_lease(task_id: int) -> BinaryIO | None:
        """跨 Agent 进程只允许一个 TaskGuard 保护同一顶层任务。

        MXU 同时保留多个实例时，MaaFramework 会把同一个 Tasker 事件广播给
        多个 AgentServer。若每个进程都创建计时器，超时后会并发请求停止并
        放大 AgentServer 反向请求竞态。文件锁随进程退出自动释放，不依赖
        清理回调。
        """
        lock_path = Path(tempfile.gettempdir()) / (
            f"maa_mhxy_task_guard_{os.getppid()}_{task_id}.lock"
        )
        lease = open(lock_path, "a+b")
        try:
            lease.seek(0, os.SEEK_END)
            if lease.tell() == 0:
                lease.write(b"0")
                lease.flush()
            lease.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lease
        except (OSError, BlockingIOError):
            lease.close()
            return None

    @staticmethod
    def _release_lease(lease: BinaryIO) -> None:
        try:
            lease.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            lease.close()

    @classmethod
    def _timeout_for(cls, entry: str) -> int:
        return cls.ENTRY_TIMEOUTS.get(entry, cls.DEFAULT_MAX_SECONDS)

    def _request_stop(self, tasker: Tasker, task_id: int, reason: str) -> None:
        logger.error(f"[TaskGuard] task_id={task_id} {reason}，主动停止全部流程")
        try:
            tasker.post_stop()
        except Exception:
            logger.exception(f"[TaskGuard] task_id={task_id} 请求停止失败")

    def _on_timeout(self, task_id: int) -> None:
        """只记录超时，不在 Timer 线程中调用 MaaFramework 原生接口。"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.stopping:
                return
            state.timed_out = True
            elapsed = int(time.monotonic() - state.started_at)
            entry = state.entry
            max_seconds = state.max_seconds

        logger.error(
            f"[TaskGuard] task_id={task_id} 任务 {entry} 超过总超时 "
            f"{max_seconds} 秒（已运行 {elapsed} 秒），"
            "等待下一个框架事件安全停止"
        )

    def _stop_if_timed_out(self, tasker: Tasker, task_id: int) -> None:
        """在 MaaFramework 的事件回调线程中执行停止，避免跨线程使用借用句柄。"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.stopping:
                return

            elapsed = int(time.monotonic() - state.started_at)
            if not state.timed_out and elapsed < state.max_seconds:
                return

            state.timed_out = True
            state.stopping = True
            reason = (
                f"任务 {state.entry} 超过总超时 {state.max_seconds} 秒"
                f"（已运行 {elapsed} 秒）"
            )

        self._request_stop(tasker, task_id, reason)

    def _is_timed_out(self, task_id: int) -> bool:
        """纯 Python 判断任务是否到期，不触发任何 AgentServer 反向请求。"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.stopping:
                return False
            return state.timed_out or (
                time.monotonic() - state.started_at >= state.max_seconds
            )

    def _start_task(self, details: dict) -> None:
        task_id = int(details["task_id"])
        entry = str(details.get("entry", ""))
        if entry == "MaaTaskerPostStop":
            return

        with self._lock:
            if task_id in self._tasks:
                return

        lease = self._acquire_lease(task_id)
        if lease is None:
            logger.debug(
                f"[TaskGuard] task_id={task_id} 已由另一个 Agent 进程保护"
            )
            return

        max_seconds = self._timeout_for(entry)
        # Tasker 是事件回调期间的借用句柄，不能保存到 Timer 线程稍后使用。
        timer = threading.Timer(max_seconds, self._on_timeout, args=(task_id,))
        timer.daemon = True
        state = _TaskState(
            entry=entry,
            started_at=time.monotonic(),
            max_seconds=max_seconds,
            timer=timer,
            lease=lease,
        )
        with self._lock:
            self._tasks[task_id] = state
        timer.start()
        logger.info(
            f"[TaskGuard] 保护任务 {entry}: 总超时={max_seconds}秒, task_id={task_id}"
        )

    def _finish_task(self, details: dict) -> None:
        task_id = int(details["task_id"])
        with self._lock:
            state = self._tasks.pop(task_id, None)
        if state is not None:
            state.timer.cancel()
            self._release_lease(state.lease)

_TASK_GUARD = _TaskExecutionGuardCore()


@AgentServer.tasker_sink()
class TaskExecutionGuard(TaskerEventSink):
    """从 Tasker 事件维护每个顶层任务的总超时生命周期。"""

    def on_raw_notification(self, tasker: Tasker, msg: str, details: dict) -> None:
        if msg == "Tasker.Task.Starting":
            _TASK_GUARD._start_task(details)
        elif msg in ("Tasker.Task.Succeeded", "Tasker.Task.Failed"):
            _TASK_GUARD._finish_task(details)


@AgentServer.context_sink()
class TaskExecutionGuardContextSink(ContextEventSink):
    """仅在确已超时时才把原始 Context 句柄转换为 Python 对象。"""

    def _on_raw_notification(self, handle, msg: str, details: dict) -> None:
        # ContextEventSink 的默认实现会为每个节点事件构造 Context；构造过程会
        # 发起 _ContextTaskerReverseRequest，并可能与其他 sink 的控制器反向请求
        # 并发，导致旧版 AgentServer 报 unexpected msg。未超时时必须直接返回。
        task_id = details.get("task_id")
        if task_id is None:
            return

        task_id = int(task_id)
        if not _TASK_GUARD._is_timed_out(task_id):
            return

        context = Context(handle=handle)
        _TASK_GUARD._stop_if_timed_out(context.tasker, task_id)

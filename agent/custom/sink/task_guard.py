"""所有顶层任务共用的总运行时间保护。"""

from dataclasses import dataclass
import threading
import time

from maa.agent.agent_server import AgentServer
from maa.tasker import Tasker, TaskerEventSink

from utils.logger import logger


@dataclass
class _TaskState:
    entry: str
    started_at: float
    max_seconds: int
    timer: threading.Timer
    stopping: bool = False


@AgentServer.tasker_sink()
class TaskExecutionGuard(TaskerEventSink):
    """防止任何流程永久运行，只限制任务总运行时间。"""

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

    @classmethod
    def _timeout_for(cls, entry: str) -> int:
        return cls.ENTRY_TIMEOUTS.get(entry, cls.DEFAULT_MAX_SECONDS)

    def _request_stop(self, tasker: Tasker, task_id: int, reason: str) -> None:
        logger.error(f"[TaskGuard] task_id={task_id} {reason}，主动停止全部流程")
        try:
            tasker.post_stop()
        except Exception:
            logger.exception(f"[TaskGuard] task_id={task_id} 请求停止失败")

    def _on_timeout(self, tasker: Tasker, task_id: int) -> None:
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.stopping:
                return
            state.stopping = True
            elapsed = int(time.monotonic() - state.started_at)
            reason = (
                f"任务 {state.entry} 超过总超时 {state.max_seconds} 秒"
                f"（已运行 {elapsed} 秒）"
            )
        self._request_stop(tasker, task_id, reason)

    def _start_task(self, tasker: Tasker, details: dict) -> None:
        task_id = int(details["task_id"])
        entry = str(details.get("entry", ""))
        if entry == "MaaTaskerPostStop":
            return

        max_seconds = self._timeout_for(entry)
        timer = threading.Timer(max_seconds, self._on_timeout, args=(tasker, task_id))
        timer.daemon = True
        state = _TaskState(
            entry=entry,
            started_at=time.monotonic(),
            max_seconds=max_seconds,
            timer=timer,
        )
        with self._lock:
            previous = self._tasks.pop(task_id, None)
            if previous is not None:
                previous.timer.cancel()
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

    def on_raw_notification(self, tasker: Tasker, msg: str, details: dict) -> None:
        if msg == "Tasker.Task.Starting":
            self._start_task(tasker, details)
        elif msg in ("Tasker.Task.Succeeded", "Tasker.Task.Failed"):
            self._finish_task(details)

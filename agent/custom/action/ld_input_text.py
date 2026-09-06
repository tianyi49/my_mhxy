"""可靠地向模拟器输入中文文本。"""

import json
import os
from pathlib import Path
import subprocess

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


def _controller_config() -> dict:
    try:
        value = json.loads(os.environ.get("PI_CONTROLLER", "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _ldplayer_details(controller_info: dict | None = None) -> tuple[Path, int] | None:
    """从实时控制器信息或 PI_CONTROLLER 定位雷电控制台及实例。"""
    candidates = []
    for controller in (controller_info, _controller_config()):
        if not isinstance(controller, dict):
            continue
        candidates.append(controller)
        adb = controller.get("adb")
        if isinstance(adb, dict):
            candidates.append(adb)

    for candidate in candidates:
        config = candidate.get("config")
        if not isinstance(config, dict):
            continue
        extras = config.get("extras")
        ld = extras.get("ld") if isinstance(extras, dict) else None
        if not isinstance(ld, dict) or not ld.get("enable"):
            continue
        try:
            index = int(ld.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        console = Path(str(ld.get("path", ""))) / "ldconsole.exe"
        if console.is_file():
            return console, index

    # 一些 MXU 版本只提供 adb_path，不带 extras.ld；雷电的 adb 和控制台同目录。
    for candidate in candidates:
        adb_path = candidate.get("adb_path") or candidate.get("path")
        if not adb_path:
            continue
        console = Path(str(adb_path)).parent / "ldconsole.exe"
        if console.is_file():
            return console, 0
    return None


@AgentServer.custom_action("ld_input_text")
class LdInputText(CustomAction):
    """优先使用雷电 call.keyboard，解决通用输入无法写入中文的问题。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except (json.JSONDecodeError, TypeError):
            logger.error("[LdInputText] 输入参数不是有效 JSON")
            return CustomAction.RunResult(success=False)

        text = str(param.get("text", "")).strip() if isinstance(param, dict) else ""
        if not text:
            # 空名字表示邀请列表到此结束，由现有 max_hit 分支正常收尾。
            return CustomAction.RunResult(success=False)
        if any(char in text for char in "\r\n\0") or len(text) > 32:
            logger.error("[LdInputText] 队员名称格式无效")
            return CustomAction.RunResult(success=False)

        try:
            controller_info = context.tasker.controller.info
        except (RuntimeError, ValueError, TypeError, OSError):
            logger.warning("[LdInputText] 无法读取实时控制器信息，尝试环境配置")
            controller_info = None

        ldplayer = _ldplayer_details(controller_info)
        if ldplayer is not None:
            console, index = ldplayer
            try:
                result = subprocess.run(
                    [
                        str(console),
                        "action",
                        "--index",
                        str(index),
                        "--key",
                        "call.input",
                        "--value",
                        text,
                    ],
                    check=False,
                    capture_output=True,
                    timeout=10,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    ),
                )
            except (OSError, subprocess.TimeoutExpired):
                logger.exception("[LdInputText] 雷电中文输入调用失败")
                return CustomAction.RunResult(success=False)

            if result.returncode == 0:
                logger.info(f"[LdInputText] 已通过雷电输入队员名称：{text}")
                return CustomAction.RunResult(success=True)
            logger.error(
                f"[LdInputText] 雷电中文输入返回错误码 {result.returncode}"
            )
            return CustomAction.RunResult(success=False)

        logger.warning("[LdInputText] 未检测到雷电配置，回退 MaaFramework 通用输入")
        job = context.tasker.controller.post_input_text(text).wait()
        return CustomAction.RunResult(success=job.status.succeeded)

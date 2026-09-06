"""在好友搜索结果中按完整角色名选择正确的行。"""

import json
import time
import unicodedata

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


def _normalized(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


@AgentServer.custom_action("select_invite_result")
class SelectInviteResult(CustomAction):
    """关闭输入法后，按完整名字点击对应搜索结果行的展开按钮。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except (json.JSONDecodeError, TypeError):
            logger.error("[SelectInviteResult] 输入参数不是有效 JSON")
            return CustomAction.RunResult(success=False)

        expected = str(param.get("text", "")).strip() if isinstance(param, dict) else ""
        if not expected:
            return CustomAction.RunResult(success=False)

        controller = context.tasker.controller
        # 雷电输入法的“确定”位于画面右上角；关闭后才会刷新搜索结果。
        confirm = controller.post_click(1240, 35).wait()
        if not confirm.status.succeeded:
            logger.error("[SelectInviteResult] 关闭输入法失败")
            return CustomAction.RunResult(success=False)

        time.sleep(1.5)
        image = controller.post_screencap().wait().get()
        detail = context.run_recognition("邀请队员-识别全部搜索结果", image)
        target_name = _normalized(expected)
        matches = [
            result
            for result in (detail.all_results if detail else [])
            if hasattr(result, "text") and _normalized(result.text) == target_name
        ]
        if not matches:
            names = [
                result.text
                for result in (detail.all_results if detail else [])
                if hasattr(result, "text")
            ]
            logger.error(
                f"[SelectInviteResult] 未找到完全匹配的队员「{expected}」，"
                f"当前结果={names}"
            )
            return CustomAction.RunResult(success=False)

        box = matches[0].box
        row_y = box[1] + box[3] // 2
        click = controller.post_click(520, row_y).wait()
        if not click.status.succeeded:
            logger.error(f"[SelectInviteResult] 点击队员「{expected}」所在行失败")
            return CustomAction.RunResult(success=False)

        logger.info(f"[SelectInviteResult] 已选择队员：{expected}，行坐标={row_y}")
        return CustomAction.RunResult(success=True)

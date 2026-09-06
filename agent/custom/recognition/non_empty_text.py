"""用于让空字符串配置在 Pipeline 识别阶段直接跳过。"""

import json

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition


@AgentServer.custom_recognition("non_empty_text")
class NonEmptyText(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        try:
            param = json.loads(argv.custom_recognition_param or "{}")
        except (json.JSONDecodeError, TypeError):
            param = {}
        text = str(param.get("text", "")).strip() if isinstance(param, dict) else ""
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 1, 1) if text else None,
            detail={"configured": bool(text)},
        )

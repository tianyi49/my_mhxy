import json

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition

from utils import logger


@AgentServer.custom_recognition("activity_entry")
class ActivityEntry(CustomRecognition):
    """在活动面板中按活动标题定位同一行的状态按钮。"""

    _DEFAULT_ROI = [316, 76, 834, 433]
    _MAX_ROW_DISTANCE = 70

    @staticmethod
    def _internal_node_name(task_names, button_texts):
        """为每个活动和状态创建独立节点，避免连续识别共享运行状态。"""
        task_key = "_".join(task_names)
        button_key = "_".join(button_texts)
        return f"活动面板入口OCR_{task_key}_{button_key}"

    @staticmethod
    def _parse_param(raw_param):
        if isinstance(raw_param, dict):
            return raw_param
        if not raw_param:
            return {}
        if isinstance(raw_param, str):
            try:
                value = json.loads(raw_param)
            except (TypeError, ValueError):
                return {"task_names": [raw_param]}
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                return {"task_names": [value]}
            if isinstance(value, list):
                return {"task_names": value}
        return {}

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        param = self._parse_param(argv.custom_recognition_param)
        raw_names = param.get("task_names", [])
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        task_names = [str(value).strip() for value in raw_names if str(value).strip()]
        raw_button_texts = param.get("button_texts", ["参加"])
        if isinstance(raw_button_texts, str):
            raw_button_texts = [raw_button_texts]
        button_texts = [
            str(value).strip() for value in raw_button_texts if str(value).strip()
        ]
        roi = param.get("roi", self._DEFAULT_ROI)
        max_row_distance = int(param.get("max_row_distance", self._MAX_ROW_DISTANCE))

        if not task_names or not button_texts:
            return CustomRecognition.AnalyzeResult(box=None, detail="未配置活动名称或按钮文字")

        image = context.tasker.controller.post_screencap().wait().get()
        internal_node = self._internal_node_name(task_names, button_texts)
        reco = context.run_recognition(
            internal_node,
            image,
            pipeline_override={
                internal_node: {
                    "recognition": "OCR",
                    "expected": [""],
                    "roi": roi,
                }
            },
        )
        if not reco or not reco.hit or not reco.all_results:
            logger.info(
                f"[ActivityEntry] 无OCR结果, 活动={task_names}, 按钮={button_texts}"
            )
            return CustomRecognition.AnalyzeResult(box=None, detail="活动面板无OCR结果")

        titles = [
            result
            for result in reco.all_results
            if result.box and any(name in result.text for name in task_names)
        ]
        buttons = [
            result
            for result in reco.all_results
            if result.box and any(text in result.text for text in button_texts)
        ]

        best_pair = None
        best_distance = None
        for title in titles:
            title_y = title.box[1] + title.box[3] / 2
            for button in buttons:
                button_y = button.box[1] + button.box[3] / 2
                row_distance = abs(title_y - button_y)
                if row_distance > max_row_distance or button.box[0] <= title.box[0]:
                    continue
                distance = row_distance * 10 + abs(button.box[0] - title.box[0])
                if best_distance is None or distance < best_distance:
                    best_pair = (title, button)
                    best_distance = distance

        if best_pair is None:
            texts = [result.text for result in reco.all_results if result.text]
            detail = (
                f"识别到活动标题但未找到同行按钮 {button_texts}: {task_names}"
                if titles
                else f"未识别到活动: {task_names}"
            )
            logger.info(f"[ActivityEntry] {detail}, OCR={texts}")
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)

        title, button = best_pair
        logger.info(
            f"[ActivityEntry] 命中活动={title.text}, 标题框={title.box}, 按钮={button.box}"
        )
        return CustomRecognition.AnalyzeResult(
            box=button.box,
            detail=f"定位活动 {title.text} 的按钮 {button.text}",
        )

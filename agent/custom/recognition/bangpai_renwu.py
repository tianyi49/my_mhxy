from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from utils import logger

import json
import re
import unicodedata


@AgentServer.custom_recognition("bangpai_renwu_decide")
class BangpaiRenwuDecide(CustomRecognition):
    """帮派任务面板识别 + 黑名单放弃决策（替代原 ``帮派任务单次点击`` 节点的纯 OCR）。

    对任务追踪面板 roi 做一次 OCR，三选一：
    - 命中黑名单关键词（如「金香玉」）且明确识别到拥有数量为 0 →
      先 ``run_task("bangpai_放弃任务")`` 放弃（终点回主界面），
      确认子链路真实完成后再 ``run_task("主界面-领取帮派任务")`` 重新领取，然后返回**未命中**（box=None）。JumpBack
      弹栈回到中心节点「已领取帮派任务」，其 next 循环（间隔/单次点击）接着处理新领到的任务；
    - 黑名单物品已经拥有，或 OCR 无法可靠识别拥有数量 → 不放弃，继续点击任务提交；
    - 无黑名单且识别到帮派任务（青龙/白虎/朱雀/玄武）→ 返回该 OCR 框，交给节点
      ``action:"Click"`` 点击，继续 pipeline 内链路；
    - 其余 → 未命中。
    """

    _ABANDON_ENTRY = "bangpai_放弃任务"
    _REACQUIRE_ENTRY = "主界面-领取帮派任务"   # 放弃后重新领取的链路入口（主界面→活动→参加→领取）
    _REACQUIRE_MAX_ATTEMPTS = 3
    _ACCEPT_KEYWORD = ["青龙", "白虎", "朱雀", "玄武"]
    _DEFAULT_ROI = [1034, 171, 235, 336]
    _DEFAULT_BLACKLIST = ["金香玉", "九转", "蛇胆酒", "长寿面", "珍露酒"]
    _DEFAULT_BLACKLIST_AFTER8 = ["蛇胆酒"]
    _OCR_COUNT_TOKEN = r"[0-9０-９OoIl|]+"

    @staticmethod
    def _normalize_ocr_count(value: str) -> int:
        """把 OCR 常见的 O/I/l 误识别还原为数字。"""
        normalized = unicodedata.normalize("NFKC", value).translate(
            str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})
        )
        return int(normalized)

    @classmethod
    def _find_item_ownership(cls, full_text: str, item_name: str):
        """读取物品名附近的 ``拥有x/y``；无法可靠读取时返回 None。

        数量必须紧跟在命中的物品名附近，避免把前面的任务进度（例如 2/10）
        错当成物品持有数量。
        """
        match = re.search(
            rf"{re.escape(item_name)}.{{0,16}}?拥有\s*({cls._OCR_COUNT_TOKEN})\s*[/／]\s*({cls._OCR_COUNT_TOKEN})",
            full_text,
        )
        if not match:
            return None

        try:
            return (
                cls._normalize_ocr_count(match.group(1)),
                cls._normalize_ocr_count(match.group(2)),
            )
        except ValueError:
            return None

    @staticmethod
    def _task_really_succeeded(detail) -> bool:
        """排除被全局 ``on_error -> 空节点`` 掩盖的子任务失败。"""
        return bool(
            detail
            and detail.status.succeeded
            and detail.nodes
            and all(node.completed for node in detail.nodes)
        )

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        param: dict = json.loads(argv.custom_recognition_param or "{}")
        roi = self._DEFAULT_ROI
        blacklist = self._DEFAULT_BLACKLIST

        image = context.tasker.controller.post_screencap().wait().get()
        reco = context.run_recognition(
            "帮派任务面板",
            image,
            pipeline_override={
                "帮派任务面板": {
                    "roi": roi,
                    "expected": [""],
                    "recognition": "OCR",
                }
            },
        )

        if not reco or not reco.hit:
            # logger.info("[bangpai_decide] 面板无文字，未命中")
            return CustomRecognition.AnalyzeResult(box=None, detail="帮派面板无文字")

        full_text = "".join(r.text for r in reco.all_results)
        if "8/10" in full_text or "9/10" in full_text or "10/10" in full_text:
            _black_list = self._DEFAULT_BLACKLIST_AFTER8
        else:
            _black_list = self._DEFAULT_BLACKLIST
        # logger.info(f"[bangpai_decide] 生效黑名单={_black_list} 面板 OCR: {full_text}")

        # ① 黑名单物品只有在明确识别为“拥有 0 个”时才放弃。
        #    已拥有时继续提交；数量不明确时也不冒险放弃。
        hit_black = next((kw for kw in _black_list if kw and kw in full_text), None)
        if hit_black:
            ownership = self._find_item_ownership(full_text, hit_black)
            if ownership is None:
                logger.warning(
                    f"[bangpai_decide] 命中黑名单「{hit_black}」，但未可靠识别拥有数量；不放弃，继续提交"
                )
                hit_black = None
            elif ownership[0] > 0:
                logger.info(
                    f"[bangpai_decide] 命中黑名单「{hit_black}」，但已拥有 {ownership[0]}/{ownership[1]}；继续提交"
                )
                hit_black = None

        # ② 确认未拥有：放弃 → 重新领取 → 回中心节点。
        #    本节点返回未命中（box=None），JumpBack 弹栈回到「已领取帮派任务」，
        #    其 next 循环（间隔/单次点击）会接着处理新领到的任务。
        if hit_black:
            ownership = self._find_item_ownership(full_text, hit_black)
            logger.info(
                f"[bangpai_decide] 命中黑名单「{hit_black}」，拥有 {ownership[0]}/{ownership[1]}，放弃后重新领取"
            )
            abandon = context.run_task(self._ABANDON_ENTRY)
            if not self._task_really_succeeded(abandon):
                logger.error(f"[bangpai_decide] 放弃黑名单任务失败：{hit_black}，跳过重新领取")
                return CustomRecognition.AnalyzeResult(box=None, detail=f"黑名单:{hit_black},放弃失败")

            reacquire = None
            for attempt in range(1, self._REACQUIRE_MAX_ATTEMPTS + 1):
                reacquire = context.run_task(
                    self._REACQUIRE_ENTRY,
                    pipeline_override={self._REACQUIRE_ENTRY: {"on_error": []}},
                )
                if self._task_really_succeeded(reacquire):
                    break

                if attempt < self._REACQUIRE_MAX_ATTEMPTS:
                    logger.warning(
                        f"[bangpai_decide] 第{attempt}次重新领取未通过任务栏核验，恢复界面后重试：{hit_black}"
                    )

            if not self._task_really_succeeded(reacquire):
                logger.error(
                    f"[bangpai_decide] 黑名单任务已放弃，连续{self._REACQUIRE_MAX_ATTEMPTS}次重新领取失败：{hit_black}"
                )
                return CustomRecognition.AnalyzeResult(box=None, detail=f"黑名单:{hit_black},重新领取失败")

            logger.info(f"[bangpai_decide] 黑名单任务处理完成：{hit_black}，已重新领取")
            return CustomRecognition.AnalyzeResult(box=None, detail=f"黑名单:{hit_black},已放弃并重新领取")

        # ③ 无需放弃且识别到帮派任务（四堂名）：返回其框，交给节点 action:Click
        for res in reco.all_results:
            if any(_key in res.text for _key in self._ACCEPT_KEYWORD):
                # logger.info(f"[bangpai_decide] 识别到帮派任务，返回框 {res.box}")
                return CustomRecognition.AnalyzeResult(box=res.box, detail="点击帮派任务")

        # ④ 都没有：未命中
        # logger.info("[bangpai_decide] 未识别到帮派任务，未命中")
        return CustomRecognition.AnalyzeResult(box=None, detail="未识别到帮派任务")

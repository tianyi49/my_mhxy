from maa.agent.agent_server import AgentServer
from maa.custom_recognition  import CustomRecognition
from maa.context import Context
from utils import logger
import re


@AgentServer.custom_recognition("OCRNum")
class OCRNum(CustomRecognition):
    @staticmethod
    def _task_really_succeeded(detail) -> bool:
        """确保内层运镖链真实完成，避免被默认空节点掩盖失败。"""
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
        """
        获取活跃度并判断
        """
        logger.info("OCRNum")
        image1 = context.tasker.controller.post_screencap().wait().get()
        recoNum =  context.run_recognition(
            "识别活跃度",
            image1,
            pipeline_override={
                "识别活跃度":{"roi" : [305,586,862,70],
                              "expected":[""],
                              "recognition": "OCR"
                            }
                }
            )
        logger.info(f"识别结果: {recoNum}")
        if not recoNum or not recoNum.hit:
            logger.error("没有识别到活跃度，结束本次任务并上报失败")
            return CustomRecognition.AnalyzeResult(box=None, detail="没有识别到活跃度")

        # 优先读取带“活跃”标签的文本；兼容 OCR 将标签和数字拆成两个文本框的情况。
        texts = [res.text.strip() for res in recoNum.all_results if res.text.strip()]
        num = next(
            (
                OCRNum.convert_to_int(text)
                for text in texts
                if "活跃" in text and OCRNum.convert_to_int(text) is not None
            ),
            None,
        )
        if num is None:
            num = next(
                (
                    OCRNum.convert_to_int(text)
                    for text in texts
                    if re.fullmatch(r"\d{1,3}", text)
                ),
                None,
            )

        if num is None:
            logger.error(f"活跃度 OCR 无有效数字：{texts}")
            return CustomRecognition.AnalyzeResult(box=None, detail="活跃度 OCR 无有效数字")

        if num >= 50:
            logger.info(f"活跃度为 {num}，开始执行运镖")
            escort = context.run_task("活动-运镖-点击日常活动")
            if not self._task_really_succeeded(escort):
                logger.error("活跃度满足条件，但运镖子流程未真实完成")
                return CustomRecognition.AnalyzeResult(box=None, detail="运镖子流程失败")
            return CustomRecognition.AnalyzeResult(box=(0, 0, 0, 0), detail="活跃度满足且运镖完成")

        logger.info(f"活跃度为 {num}，不足 50，本次不执行运镖")
        context.run_task("panduan_zhujiemian")
        return CustomRecognition.AnalyzeResult(box=(0, 0, 0, 0), detail="活跃度不足50")

    def convert_to_int(s):
        match = re.search(r"(\d{1,3})", s)
        if not match:
            return None
        return int(match.group(1))


@AgentServer.custom_recognition("OCRVitality")
class OCRVitality(CustomRecognition):
    def analyze(
         self,
         context: Context,
         argv: CustomRecognition.AnalyzeArg,
     ) -> CustomRecognition.AnalyzeResult:
        """
        识别活力，并判断点击打工次数
        "recommended roi" : [380,103,542,46]
        """
        logger.info("进入识别活力agnet")
        image1 = context.tasker.controller.post_screencap().wait().get()
        recoNum =  context.run_recognition(
            "识别活力",
            image1,
            pipeline_override={
                "识别活力":{"roi" :  [380,103,542,46],
                              "expected":[""],
                              "recognition": "OCR"
                            }
                }

            )
        if not recoNum or not recoNum.hit:
            logger.info("没有识别到活力")
            return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="没有识别到活力")
        for res in recoNum.all_results:
            strnum = re.match(r'^(\d+)/', res.text)
            huoli = int(strnum.group(1))
            logger.info(f"活力为: {huoli}")
            # 点击次数
            num=huoli // 100
            if num == 0:
                logger.info("活力不足，无需打工")
                return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="活力不足，无需打工")
            else:
                for i in range(num):
                    context.run_task("点击打工")
        return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="活力打工完成")

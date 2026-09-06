from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
import re
import time
import math
import unicodedata

from utils import logger

@AgentServer.custom_recognition("zhuogui_hundui")
class zhuogui_hundui(CustomRecognition):
    """
    整体任务结束
    多条件结束任务，
    满足以下条件之一，结束任务：
    1. 时间超过定时的时间
    Uset_time_HH = 23
    Uset_time_MM = 30
    2.活力为0或者活力低于用户指定值
    User_points=0
    """

    _OCR_ATTEMPTS = 3
    _DEFAULT_USER_POINTS = 0
    _DEFAULT_END_HOUR = 23
    _DEFAULT_END_MINUTE = 30

    @staticmethod
    def _parse_non_negative_int(value):
        """从配置或 OCR 文本提取非负整数，无法解析时返回 None。"""
        if isinstance(value, bool):
            return int(value)
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        match = re.search(r"\d+", text)
        if not match:
            return None
        return int(match.group())

    @classmethod
    def _parse_config_int(cls, value, default):
        """空白输入沿用界面默认值，非空脏值仍作为配置错误处理。"""
        if value is None or not str(value).strip():
            return default
        return cls._parse_non_negative_int(value)

    def _recognize_points(self, context: Context, name: str, roi):
        """有限次数重试点数 OCR，避免脏文本进入 int() 导致回调崩溃。"""
        last_text = ""
        for attempt in range(1, self._OCR_ATTEMPTS + 1):
            image = context.tasker.controller.post_screencap().wait().get()
            reco = context.run_recognition(
                name,
                image,
                pipeline_override={
                    name: {
                        "roi": roi,
                        "expected": [""],
                        "recognition": "OCR",
                    }
                },
            )
            if reco and reco.hit and reco.best_result:
                last_text = reco.best_result.text
                value = self._parse_non_negative_int(last_text)
                if value is not None:
                    return value
            logger.warning(
                f"{name} OCR 第 {attempt}/{self._OCR_ATTEMPTS} 次无有效数字: "
                f"{last_text!r}"
            )
            if attempt < self._OCR_ATTEMPTS:
                time.sleep(0.3)
        return None

    def analyze(
         self,
         context: Context,
         argv: CustomRecognition.AnalyzeArg,
     ) -> CustomRecognition.AnalyzeResult:
        # logger.info("zhuogui_hundui")
        
        # 获取自定义参数
        attach = context.get_node_data("混队-抓鬼-判断结束条件").get("attach", {})
        User_points = self._parse_config_int(
            attach.get("User_points"), self._DEFAULT_USER_POINTS
        )
        Uset_time_HH = self._parse_config_int(
            attach.get("Uset_time_HH"), self._DEFAULT_END_HOUR
        )
        Uset_time_MM = self._parse_config_int(
            attach.get("Uset_time_MM"), self._DEFAULT_END_MINUTE
        )
        if None in (User_points, Uset_time_HH, Uset_time_MM):
            return CustomRecognition.AnalyzeResult(
                box=None, detail="捉鬼结束条件配置不是有效整数"
            )

        Received_double_points = self._recognize_points(
            context, "已领取双倍点数", [628, 626, 53, 35]
        )
        Not_Received_double_points = self._recognize_points(
            context, "未领取双倍点数", [910, 624, 63, 37]
        )
        if Received_double_points is None or Not_Received_double_points is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail=f"双倍点数连续 {self._OCR_ATTEMPTS} 次识别失败",
            )

        logger.info(f"已领取双倍点数: {Received_double_points}, 未领取双倍点数: {Not_Received_double_points}")
        # 获取当前时间，并判断是否超过定时的时间Uset_time_HH：Uset_time_MM
        current_time = time.localtime()
        current_hh = current_time.tm_hour
        current_mm = current_time.tm_min
        # 判断点击领取双倍次数
        m = max(0, 1000 - Received_double_points)
        max_click = math.ceil(max(0, min(m, Not_Received_double_points)) / 100)

        # 判断是否满足结束条件
        if Received_double_points + Not_Received_double_points <= User_points: # 活力点数小于用户指定值
            logger.info(f"满足力点数小于用户指定值，任务结束")
            context.run_task("tuichuduiwu")
            return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="活力点数小于用户指定值，捉鬼任务结束")
        elif current_hh > Uset_time_HH or (current_hh == Uset_time_HH and current_mm > Uset_time_MM): # 时间超过定时的时间
            logger.info(f"满足时间超过定时的时间，任务结束")
            context.run_task("tuichuduiwu")
            return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="时间大于用户指定时间，捉鬼任务结束")
        else:
            # 根据点击次数，执行领取双倍点数的任务
            for _ in range(max_click):
                context.run_task("混队-抓鬼-双倍点数领取")
            logger.info(f"未满足任务结束条件，领取双倍点数，并继续开始捉鬼混队")
            context.run_task("tuichuduiwu")
            time.sleep(1)
            try:
                context.run_task("zhuogui_hundui")
            except Exception:
                logger.exception("续跑捉鬼混队失败")
                return CustomRecognition.AnalyzeResult(
                    box=None, detail="续跑捉鬼混队失败"
                )
            return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="未满足结束条件，继续任务")

        # return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="捉鬼任务结束")


@AgentServer.custom_recognition("zhuogui_end_once")
class zhuogui_end_once(CustomRecognition):
    """
    捉鬼单次计算
    """
    def analyze(
             self,
             context: Context,
             argv: CustomRecognition.AnalyzeArg,
         ) -> CustomRecognition.AnalyzeResult:
        
        image = context.tasker.controller.post_screencap().wait().get()
        time.sleep(3)
        image2 = context.tasker.controller.post_screencap().wait().get()
        #我想对比image和image2相似度，按0.7标准，有没有函数
       

        return CustomRecognition.AnalyzeResult(box=(0,0,0,0),detail="")

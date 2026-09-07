from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
import re
import time
import math
import json
import threading
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


@AgentServer.custom_recognition("zhuogui_time_guard")
class ZhuoguiTimeGuard(CustomRecognition):
    """在混队仍正常运行时检查结束时间，避免只能等队伍解散才生效。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        attach = context.get_node_data("混队-抓鬼-判断结束条件").get(
            "attach", {}
        )
        end_hour = zhuogui_hundui._parse_config_int(
            attach.get("Uset_time_HH"), zhuogui_hundui._DEFAULT_END_HOUR
        )
        end_minute = zhuogui_hundui._parse_config_int(
            attach.get("Uset_time_MM"), zhuogui_hundui._DEFAULT_END_MINUTE
        )
        if end_hour is None or end_minute is None:
            return CustomRecognition.AnalyzeResult(
                box=None, detail="捉鬼结束时间配置不是有效整数"
            )

        current_time = time.localtime()
        is_after_end = current_time.tm_hour > end_hour or (
            current_time.tm_hour == end_hour
            and current_time.tm_min > end_minute
        )
        if not is_after_end:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail=f"当前未到捉鬼结束时间 {end_hour:02d}:{end_minute:02d}",
            )

        logger.info(
            f"当前时间已超过 {end_hour:02d}:{end_minute:02d}，"
            "结束混队捉鬼"
        )
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 0, 0),
            detail="已到用户指定结束时间，退出队伍并结束混队捉鬼",
        )


@AgentServer.custom_recognition("zhuogui_team_watchdog")
class ZhuoguiTeamWatchdog(CustomRecognition):
    """连续没有捉鬼进度时触发退队重匹配。

    队伍血条只能证明角色仍在队伍中，不能证明队伍还在执行捉鬼。
    战斗或自动寻路会刷新进度；只有右侧捉鬼任务但长期不推进时，
    也会在更宽松的时间窗后重匹配。
    """

    _DEFAULT_IDLE_TIMEOUT = 180
    _DEFAULT_TASK_ONLY_TIMEOUT = 300
    _STATE_TTL = 8 * 60 * 60
    _states = {}
    _lock = threading.Lock()
    _PROGRESS_RECOGNITIONS = (
        "混队-抓鬼-有效状态-战斗中",
        "混队-抓鬼-有效状态-自动寻路",
    )
    _TASK_RECOGNITION = "混队-抓鬼-有效状态-任务追踪"

    @classmethod
    def _prune_states(cls, now):
        expired = [
            task_id
            for task_id, state in cls._states.items()
            if now - state["last_seen"] > cls._STATE_TTL
        ]
        for task_id in expired:
            cls._states.pop(task_id, None)

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        try:
            param = json.loads(argv.custom_recognition_param or "{}")
        except (TypeError, json.JSONDecodeError):
            param = {}
        idle_timeout = zhuogui_hundui._parse_non_negative_int(
            param.get("idle_timeout")
        )
        if not idle_timeout:
            idle_timeout = self._DEFAULT_IDLE_TIMEOUT
        task_only_timeout = zhuogui_hundui._parse_non_negative_int(
            param.get("task_only_timeout")
        )
        if not task_only_timeout:
            task_only_timeout = self._DEFAULT_TASK_ONLY_TIMEOUT

        progress_name = None
        for name in self._PROGRESS_RECOGNITIONS:
            reco = context.run_recognition(name, argv.image)
            if reco and reco.hit:
                progress_name = name
                break
        task_reco = context.run_recognition(self._TASK_RECOGNITION, argv.image)
        has_task = bool(task_reco and task_reco.hit)

        now = time.monotonic()
        task_id = argv.task_detail.task_id
        with self._lock:
            self._prune_states(now)
            state = self._states.get(task_id)

            if progress_name:
                if state and now - state["idle_since"] >= 30:
                    logger.info(
                        f"[ZhuoguiWatchdog] task_id={task_id} 恢复有效状态："
                        f"{progress_name}"
                    )
                self._states[task_id] = {
                    "idle_since": now,
                    "last_seen": now,
                    "last_log": now,
                }
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={"progress": progress_name},
                )

            current_timeout = task_only_timeout if has_task else idle_timeout

            if state is None:
                state = {
                    "idle_since": now,
                    "last_seen": now,
                    "last_log": now,
                }
                self._states[task_id] = state
                logger.warning(
                    f"[ZhuoguiWatchdog] task_id={task_id} 未检测到战斗或"
                    f"自动寻路，开始 {current_timeout} 秒停滞计时"
                    f"（捉鬼任务追踪={'存在' if has_task else '不存在'}）"
                )
            else:
                state["last_seen"] = now

            idle_seconds = now - state["idle_since"]
            if idle_seconds < current_timeout:
                if now - state["last_log"] >= 60:
                    state["last_log"] = now
                    logger.warning(
                        f"[ZhuoguiWatchdog] task_id={task_id} 已连续 "
                        f"{int(idle_seconds)} 秒无战斗或自动寻路"
                    )
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={
                        "idle_seconds": int(idle_seconds),
                        "idle_timeout": current_timeout,
                        "has_task": has_task,
                    },
                )

            self._states.pop(task_id, None)

        logger.error(
            f"[ZhuoguiWatchdog] task_id={task_id} 连续 "
            f"{int(idle_seconds)} 秒无战斗或自动寻路，退出当前队伍并重新匹配"
        )
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 0, 0),
            detail={
                "idle_seconds": int(idle_seconds),
                "has_task": has_task,
                "action": "leave_and_rematch",
            },
        )


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

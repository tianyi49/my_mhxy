from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from utils import logger

import cv2
import numpy as np
import time
import random

@AgentServer.custom_action("tayin")
class tayin(CustomAction):
    """
    拓印自动描摹
    """
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # 1. 截取当前屏幕
        image = context.tasker.controller.post_screencap().wait().get()
        if image is None:
            logger.error("截图失败")
            return CustomAction.RunResult(success=False)

        # ---------- 参数配置（请根据实际游戏调整）----------
        # 拓印画布区域（相对于屏幕左上角的 [x, y, width, height]）
        # 注意：这里需要是笔画区域，而不是标题文字区域！
        roi = [407, 168, 200, 200]   # 示例，请自行测量
        # 笔画颜色范围（BGR格式，此处为示例金色，实际拓印笔画通常为红色）
        lower_color = [220, 173, 132]   # 示例，请替换为实际红色范围
        upper_color = [225, 191, 148]
       

        # 2. 提取转折点坐标（相对原图）
        turning_points = self._extract_turning_points(
            image, roi, lower_color, upper_color
        )
        if not turning_points:
            logger.warning("未检测到有效笔画，可能画布为空或颜色参数不匹配")
            return CustomAction.RunResult(success=False)

        logger.info(f"提取到 {len(turning_points)} 个转折点")

        # 3. 生成滑动指令序列（每两个相邻点构成一次滑动）
        swipes = self._generate_swipe_sequence(turning_points)
        if not swipes:
            logger.warning("转折点不足，无法生成滑动序列")
            return CustomAction.RunResult(success=False)

        logger.info(f"生成 {len(swipes)} 条滑动指令")

        # 4. 执行连续滑动
        for idx, (x1, y1, x2, y2) in enumerate(swipes):
            
            # 可添加延时，防止速度过快导致识别延迟
            if idx > 0:
                # 滑动速度（每次滑动间隔时间，秒） 在 0.3 秒 到 1.2 秒之间随机生成一个浮点数
                swipe_interval = random.uniform(0.3, 1.2)
                time.sleep(swipe_interval)
            context.tasker.controller.post_swipe(x1, y1, x2, y2).wait()

        logger.info("拓印描摹完成")
        return CustomAction.RunResult(success=True)

    # ------------------ 图像处理核心函数 ------------------
    def _extract_turning_points(self, image, roi, lower_color, upper_color):
        """
        从图像中提取转折点（相对原图坐标）
        """
        x, y, w, h = roi
        roi_img = image[y:y+h, x:x+w]

        # 颜色筛选生成二值掩膜
        lower = np.array(lower_color, dtype=np.uint8)
        upper = np.array(upper_color, dtype=np.uint8)
        mask = cv2.inRange(roi_img, lower, upper)

        # 腐蚀（细化笔画）
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        eroded = cv2.erode(mask, kernel, iterations=1)

        # 中值滤波降噪
        denoised = cv2.medianBlur(eroded, 3)

        # 提取轮廓
        contours, _ = cv2.findContours(denoised, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        turning_points = []
        for cnt in contours:
            peri = cv2.arcLength(cnt, True)
            if peri < 5:   # 忽略太小的轮廓（噪点）
                continue
            # 采用Ramer–Douglas–Peucker算法近似
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            for pt in approx:
                px = int(pt[0][0]) + x   # 还原到原图坐标
                py = int(pt[0][1]) + y
                turning_points.append((px, py))

        # 按轮廓顺序排序（保证轨迹连续性）
        # 如果希望更平滑，可对点进行插值，此处简单处理
        return turning_points

    def _generate_swipe_sequence(self, points, step=1):
        """
        将转折点列表转换为滑动指令序列 [(x1,y1,x2,y2), ...]
        """
        if len(points) < 2:
            return []
        # 可选：每隔 step 个点取一个，减少滑动次数
        if step > 1:
            points = points[::step]
        swipes = []
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i+1]
            swipes.append((x1, y1, x2, y2))
        return swipes
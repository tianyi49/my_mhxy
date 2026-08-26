from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from utils import logger
import cv2
import numpy as np
import time
import random
from skimage.morphology import skeletonize   # 新增，替代 cv2.ximgproc

@AgentServer.custom_action("tayin")
class tayin(CustomAction):
    """
    拓印自动描摹 梦幻西游拓印
    """
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        logger.error("进入tayin")
        # 1. 截取当前屏幕 MAA返回RGB！！！！
        image_rgb = context.tasker.controller.post_screencap().wait().get()
        if image_rgb is None:
            logger.error("截图失败")
            return CustomAction.RunResult(success=False)
        # MAA返回RGB，opencv需要BGR，必须转换通道
        image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        # ---------- 参数配置（请根据实际游戏调整）----------
        roi = [541, 220, 269, 272]          # 拓印画布区域
        lower_color = [132, 172, 220]       # BGR下界
        upper_color = [164, 203, 233]       # BGR上界
        step = 40                           # 采样步长（与测试一致）

        # 2. 提取笔画轨迹点
        turning_points = self._extract_stroke_points(
            image, roi, lower_color, upper_color
        )
        if not turning_points:
            logger.warning("未检测到有效笔画，mask没有找到笔画")
            return CustomAction.RunResult(success=False)
        logger.info(f"提取到 {len(turning_points)} 个轨迹点")

        # 3. 生成滑动指令序列
        swipes = self._generate_swipe_sequence(turning_points, step=step)
        if not swipes:
            logger.warning("转折点不足，无法生成滑动序列")
            return CustomAction.RunResult(success=False)
        logger.info(f"生成 {len(swipes)} 条滑动指令")

        # ---- 可选：保存调试图像（可注释掉） ----
        # self._save_debug_image(image, roi, swipes, "maa_debug.png")

        # 4. 执行连续滑动
        for idx, (x1, y1, x2, y2) in enumerate(swipes):
            if idx > 0:
                swipe_interval = random.uniform(0.25, 0.8)
                time.sleep(swipe_interval)
            context.tasker.controller.post_swipe(x1, y1, x2, y2).wait()

        logger.info("拓印描摹完成")
        return CustomAction.RunResult(success=True)

    def _extract_stroke_points(self, image, roi, lower_color, upper_color):
        """
        提取毛笔笔画中心线轨迹点（使用 skimage 骨架化）
        """
        x, y, w, h = roi
        roi_img = image[y:y+h, x:x+w]

        lower = np.array(lower_color, dtype=np.uint8)
        upper = np.array(upper_color, dtype=np.uint8)
        mask = cv2.inRange(roi_img, lower, upper)

        # 可选：保存mask用于调试
        # cv2.imwrite("mask_debug.png", mask)

        if np.count_nonzero(mask) < 100:
            logger.warning("mask内有效像素过少，颜色阈值不匹配")
            return []

        # 闭运算填充断裂
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=1)

        # 使用 skimage 骨架化
        skeleton_bool = skeletonize(closed > 0)
        skeleton = (skeleton_bool * 255).astype(np.uint8)

        ys, xs = np.where(skeleton > 0)
        if len(xs) == 0:
            logger.warning("骨架细化后无像素点")
            return []

        points_roi = np.stack([xs, ys], axis=-1)
        ordered_points = self._sort_stroke_trace(points_roi)

        # 还原全局坐标
        global_points = [(px + x, py + y) for px, py in ordered_points]
        return global_points

    def _sort_stroke_trace(self, points: np.ndarray):
        """贪心最近点排序（模拟书写顺序）"""
        if len(points) == 0:
            return []
        remaining = points.tolist()
        ordered = []
        cur = remaining.pop(0)
        ordered.append(cur)
        while len(remaining) > 0:
            cur_np = np.array(cur)
            rest_np = np.array(remaining)
            dists = np.sqrt(np.sum((rest_np - cur_np)**2, axis=1))
            idx = int(np.argmin(dists))
            cur = remaining.pop(idx)
            ordered.append(cur)
        return ordered

    def _generate_swipe_sequence(self, points, step=2):
        """采样生成滑动指令"""
        if len(points) < 2:
            return []
        sampled = points[::step]
        swipes = []
        for i in range(len(sampled)-1):
            x1, y1 = sampled[i]
            x2, y2 = sampled[i+1]
            swipes.append((int(x1), int(y1), int(x2), int(y2)))
        return swipes

    # ---------- 可选调试方法 ----------
    def _save_debug_image(self, image, roi, swipes, output_path):
        """保存绘制了滑动轨迹的截图，便于验证坐标"""
        img = image.copy()
        x, y, w, h = roi
        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
        for (x1, y1, x2, y2) in swipes:
            cv2.line(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        if swipes:
            sx, sy = swipes[0][0], swipes[0][1]
            cv2.circle(img, (sx, sy), 5, (255, 0, 0), -1)
        cv2.imwrite(output_path, img)
        logger.info(f"调试图像已保存至 {output_path}")
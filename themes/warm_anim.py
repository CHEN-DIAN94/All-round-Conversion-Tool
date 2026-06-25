# -*- coding: utf-8 -*-
"""
🔥 温暖主题动画模块
- 主按钮温暖呼吸光晕（琥珀 shadow 呼吸）
- 空状态区域萤火虫粒子
- 轻量级：idle 时 CPU < 2%
"""

import math
import random
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QPainter, QFont, QGraphicsDropShadowEffect


class _Firefly:
    """萤火虫粒子。"""
    __slots__ = ('x', 'y', 'vx', 'vy', 'life', 'max_life', 'glow_phase', 'size')

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.vx = random.uniform(-0.4, 0.4)
        self.vy = random.uniform(-0.5, 0.1)
        self.life = 0
        self.max_life = random.randint(80, 160)
        self.glow_phase = random.uniform(0, math.pi * 2)
        self.size = random.randint(3, 6)

    def update(self):
        self.x += self.vx + math.sin(self.life * 0.05) * 0.2
        self.y += self.vy
        self.life += 1
        self.glow_phase += 0.15
        return self.life < self.max_life

    @property
    def alpha(self):
        """呼吸发光 alpha。"""
        t = self.life / self.max_life
        fade = 1.0
        if t < 0.15:
            fade = t / 0.15
        elif t > 0.85:
            fade = (1 - t) / 0.15
        glow = 0.5 + 0.5 * math.sin(self.glow_phase)
        return int(fade * glow * 200)


class ThemeAnimator:
    def __init__(self, window):
        self._window = window
        self._timer = QTimer()
        self._timer.setInterval(80)  # 12fps，节省 CPU
        self._timer.timeout.connect(self._tick)
        self._phase = 0.0
        self._shadow = None
        self._fireflies: list[_Firefly] = []
        self._empty_widget = None
        self._original_paint = None

    def start(self):
        """启动动画。"""
        # 为主按钮添加温暖呼吸光晕
        btn = getattr(self._window, '_start_btn', None)
        if btn:
            self._shadow = QGraphicsDropShadowEffect(btn)
            self._shadow.setBlurRadius(20)
            self._shadow.setColor(QColor(245, 158, 11, 80))
            self._shadow.setOffset(0, 0)
            btn.setGraphicsEffect(self._shadow)

        # 在空状态 widget 上安装萤火虫绘制
        self._empty_widget = getattr(self._window, '_empty_state_widget', None)
        if self._empty_widget:
            self._original_paint = self._empty_widget.paintEvent
            self._empty_widget.paintEvent = self._paint_fireflies

        self._timer.start()

    def stop(self):
        """停止动画并清理。"""
        self._timer.stop()
        btn = getattr(self._window, '_start_btn', None)
        if btn:
            btn.setGraphicsEffect(None)
        self._shadow = None
        self._fireflies.clear()

        # 恢复原始 paintEvent
        if self._empty_widget and self._original_paint:
            self._empty_widget.paintEvent = self._original_paint
            self._empty_widget.update()
        self._empty_widget = None
        self._original_paint = None

    def _tick(self):
        """每帧更新。"""
        self._phase += 0.05

        # 温暖呼吸光晕
        alpha = int(100 + 50 * math.sin(self._phase))
        blur = int(18 + 8 * math.sin(self._phase * 0.8))
        if self._shadow:
            self._shadow.setBlurRadius(blur)
            self._shadow.setColor(QColor(245, 158, 11, alpha))

        # 萤火虫生成（只在空状态可见时）
        if self._empty_widget and self._empty_widget.isVisible():
            if random.random() < 0.1 and len(self._fireflies) < 15:
                w = self._empty_widget.width()
                h = self._empty_widget.height()
                self._fireflies.append(_Firefly(
                    random.randint(20, max(20, w - 20)),
                    random.randint(h // 3, max(h // 3, h - 20))
                ))

        # 更新萤火虫
        self._fireflies = [f for f in self._fireflies if f.update()]

        # 触发重绘
        if self._empty_widget and self._empty_widget.isVisible():
            self._empty_widget.update()

    def _paint_fireflies(self, event):
        """在空状态 widget 上绘制萤火虫。"""
        # 先调用原始绘制
        if self._original_paint:
            self._original_paint(event)

        if not self._fireflies:
            return

        painter = QPainter(self._empty_widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for f in self._fireflies:
            # 外圈光晕
            glow_color = QColor(245, 158, 11, f.alpha // 3)
            painter.setPen(glow_color)
            painter.setBrush(glow_color)
            r = f.size * 2
            painter.drawEllipse(int(f.x - r), int(f.y - r), r * 2, r * 2)

            # 核心亮点
            core_color = QColor(253, 230, 138, f.alpha)
            painter.setPen(core_color)
            painter.setBrush(core_color)
            painter.drawEllipse(int(f.x - f.size), int(f.y - f.size),
                              f.size * 2, f.size * 2)

        painter.end()

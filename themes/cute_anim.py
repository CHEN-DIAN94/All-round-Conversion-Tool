# -*- coding: utf-8 -*-
"""
💖 可爱主题动画模块
- 主按钮柔和呼吸光晕（粉色 shadow 呼吸）
- 空状态区域飘浮心形/星星粒子
- 轻量级：idle 时 CPU < 2%
"""

import math
import random
from PyQt6.QtCore import QTimer, QPointF
from PyQt6.QtGui import QColor, QPainter, QFont, QGraphicsDropShadowEffect


class _Particle:
    """飘浮粒子（心形或星星）。"""
    __slots__ = ('x', 'y', 'vx', 'vy', 'life', 'max_life', 'char', 'size')

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.vx = random.uniform(-0.3, 0.3)
        self.vy = random.uniform(-0.8, -0.3)
        self.life = 0
        self.max_life = random.randint(60, 120)
        self.char = random.choice(['♥', '★', '✦', '♡', '·'])
        self.size = random.randint(8, 14)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.life += 1
        return self.life < self.max_life

    @property
    def alpha(self):
        """渐入渐出 alpha。"""
        t = self.life / self.max_life
        if t < 0.2:
            return int(t / 0.2 * 180)
        elif t > 0.8:
            return int((1 - t) / 0.2 * 180)
        return 180


class ThemeAnimator:
    def __init__(self, window):
        self._window = window
        self._timer = QTimer()
        self._timer.setInterval(66)  # 15fps，节省 CPU
        self._timer.timeout.connect(self._tick)
        self._phase = 0.0
        self._shadow = None
        self._particles: list[_Particle] = []
        self._empty_widget = None
        self._original_paint = None

    def start(self):
        """启动动画。"""
        # 为主按钮添加呼吸光晕
        btn = getattr(self._window, '_start_btn', None)
        if btn:
            self._shadow = QGraphicsDropShadowEffect(btn)
            self._shadow.setBlurRadius(25)
            self._shadow.setColor(QColor(255, 105, 180, 80))
            self._shadow.setOffset(0, 0)
            btn.setGraphicsEffect(self._shadow)

        # 在空状态 widget 上安装粒子绘制
        self._empty_widget = getattr(self._window, '_empty_state_widget', None)
        if self._empty_widget:
            self._original_paint = self._empty_widget.paintEvent
            self._empty_widget.paintEvent = self._paint_particles

        self._timer.start()

    def stop(self):
        """停止动画并清理。"""
        self._timer.stop()
        btn = getattr(self._window, '_start_btn', None)
        if btn:
            btn.setGraphicsEffect(None)
        self._shadow = None
        self._particles.clear()

        # 恢复原始 paintEvent
        if self._empty_widget and self._original_paint:
            self._empty_widget.paintEvent = self._original_paint
            self._empty_widget.update()
        self._empty_widget = None
        self._original_paint = None

    def _tick(self):
        """每帧更新。"""
        self._phase += 0.06

        # 呼吸光晕
        alpha = int(100 + 60 * math.sin(self._phase))
        blur = int(20 + 10 * math.sin(self._phase))
        if self._shadow:
            self._shadow.setBlurRadius(blur)
            self._shadow.setColor(QColor(255, 105, 180, alpha))

        # 粒子生成（只在空状态可见时）
        if self._empty_widget and self._empty_widget.isVisible():
            if random.random() < 0.15 and len(self._particles) < 20:
                w = self._empty_widget.width()
                h = self._empty_widget.height()
                self._particles.append(_Particle(
                    random.randint(20, max(20, w - 20)),
                    random.randint(h // 2, max(h // 2, h - 20))
                ))

        # 更新粒子
        self._particles = [p for p in self._particles if p.update()]

        # 触发重绘
        if self._empty_widget and self._empty_widget.isVisible():
            self._empty_widget.update()

    def _paint_particles(self, event):
        """在空状态 widget 上绘制粒子。"""
        # 先调用原始绘制
        if self._original_paint:
            self._original_paint(event)

        if not self._particles:
            return

        painter = QPainter(self._empty_widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for p in self._particles:
            color = QColor(255, 105, 180, p.alpha)
            painter.setPen(color)
            font = QFont('Segoe UI', p.size)
            painter.setFont(font)
            painter.drawText(int(p.x), int(p.y), p.char)

        painter.end()

# -*- coding: utf-8 -*-
"""
💖 可爱主题动画模块（内存泄漏修复版）

修复点：
1. eventFilter 替代 paintEvent 猴子补丁，消除引用环
2. stop() 显式 disconnect + deleteLater 释放 C++ 对象
3. 原地过滤粒子列表，减少 GC 压力
4. __del__ 兜底清理
"""

import math
import random
from PyQt6.QtCore import QTimer, QObject, QEvent
from PyQt6.QtGui import QColor, QPainter, QFont, QGraphicsDropShadowEffect
from PyQt6.QtWidgets import QWidget


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


class _PaintFilter(QObject):
    """
    事件过滤器：替代 paintEvent 猴子补丁。

    通过 installEventFilter 安装，不修改 widget 的 paintEvent 属性，
    避免 widget → bound method → animator → widget 引用环。
    """

    def __init__(self, animator, parent: QWidget):
        super().__init__(parent)
        self._animator = animator

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            # 让 Qt 先完成默认绘制，再叠加粒子
            self._animator._draw_particles_on(obj)
            return False  # 不拦截，让 Qt 继续处理
        return super().eventFilter(obj, event)


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
        self._paint_filter = None
        self._alive = True

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

        # 用 eventFilter 安装粒子绘制（不修改 paintEvent）
        self._empty_widget = getattr(self._window, '_empty_state_widget', None)
        if self._empty_widget:
            self._paint_filter = _PaintFilter(self, self._empty_widget)
            self._empty_widget.installEventFilter(self._paint_filter)

        self._timer.start()

    def stop(self):
        """停止动画并彻底清理所有资源。"""
        if not self._alive:
            return
        self._alive = False

        # 1. 停止并断开 timer 信号
        self._timer.stop()
        try:
            self._timer.timeout.disconnect(self._tick)
        except TypeError:
            pass  # 已断开

        # 2. 显式释放 shadow effect
        btn = getattr(self._window, '_start_btn', None)
        if btn:
            btn.setGraphicsEffect(None)
        self._shadow = None

        # 3. 移除事件过滤器并 deleteLater
        if self._empty_widget and self._paint_filter:
            self._empty_widget.removeEventFilter(self._paint_filter)
            self._paint_filter.deleteLater()
            self._paint_filter = None

        # 4. 清空粒子
        self._particles.clear()
        w = self._empty_widget
        self._empty_widget = None

        # 5. 触发重绘清除残余
        if w:
            w.update()

    def __del__(self):
        """兜底：外部忘记调用 stop() 时自动清理。"""
        try:
            self.stop()
        except Exception:
            pass

    def _tick(self):
        """每帧更新。"""
        if not self._alive:
            return
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

        # 原地过滤：倒序遍历删除，避免每帧创建新 list
        i = len(self._particles) - 1
        while i >= 0:
            if not self._particles[i].update():
                del self._particles[i]
            i -= 1

        # 触发重绘
        if self._empty_widget and self._empty_widget.isVisible():
            self._empty_widget.update()

    def _draw_particles_on(self, widget):
        """在 widget 上绘制粒子（由事件过滤器调用）。"""
        if not self._alive or not self._particles:
            return

        painter = QPainter(widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for p in self._particles:
            color = QColor(255, 105, 180, p.alpha)
            painter.setPen(color)
            font = QFont('Segoe UI', p.size)
            painter.setFont(font)
            painter.drawText(int(p.x), int(p.y), p.char)

        painter.end()

"""Анимированные кнопки: основа для всех кнопок панели.

Таблица стилей Qt (style.qss) не умеет плавных переходов, поэтому эти кнопки рисуют себя сами:
- наведение — подложка плавно проявляется, значок становится ярче и чуть крупнее;
- нажатие — кнопка на мгновение «проседает» и пружинит обратно;
- включение (у кнопок-переключателей) — заливка цветом акцента растёт кругом от центра;
- reveal — общая прозрачность, чтобы кнопку можно было плавно показать / спрятать;
- у кнопок с иконками Lucide (LucideButton) — ещё и своя анимация значка (icons.py): пружины и «рывки».

Анимация идёт только пока что-то меняется (0,06–0,3 с) и перерисовывает одну маленькую кнопку,
поэтому нагрузки почти не добавляет. Цвета — из текущей темы: set_theme() вызывается при смене темы.
"""

import time
import weakref

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from . import icons

HOVER_IN_MS, HOVER_OUT_MS = 150, 250
PRESS_DOWN_MS, PRESS_UP_MS = 60, 160
CHECK_MS = 280
MORPH_MS = 260

_COLORS = {
    "surface": QColor("#1f2026"), "surface2": QColor("#2c2e36"), "text": QColor("#e8e9ee"), "text_dim": QColor("#9a9ca6"),
    "accent": QColor("#4f8cff"), "accent_hover": QColor("#6c9fff"), "accent_text": QColor("#ffffff"),
}
_RADIUS = 8
_ICON_FONT = "Segoe Fluent Icons"
_buttons = weakref.WeakSet()


def set_theme(theme: dict, icon_font: str):
    """Цвета темы для всех анимированных кнопок (и уже созданных, и будущих)."""
    global _RADIUS, _ICON_FONT
    for key in _COLORS:
        if key in theme:
            _COLORS[key] = QColor(theme[key])
    _RADIUS = int(theme.get("radius", 8))
    _ICON_FONT = icon_font
    for button in list(_buttons):
        try:
            button.update()
        except RuntimeError:  # кнопка уже удалена (Qt удалил её раньше, чем Python забыл о ней)
            _buttons.discard(button)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def restart(animation: QVariantAnimation, start: float, end: float, ms: int):
    """Запустить анимацию заново от start к end.

    Важно: у закончившейся анимации Qt при setEndValue() сразу присылает valueChanged с новым концом —
    будто значение уже там. Без блокировки сигналов это мгновенно ставило кнопку в конечное состояние,
    и со второго раза анимация «перескакивала» (первый раз — плавно, дальше — рывком)."""
    animation.blockSignals(True)
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setDuration(ms)
    animation.blockSignals(False)
    animation.start()


class _Tween:
    """Плавно меняет одно число 0…1 и перерисовывает кнопку."""

    def __init__(self, button: QPushButton, value: float = 0.0):
        self.value = value
        self._button = button
        self._animation = QVariantAnimation(button)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_value)

    def _on_value(self, value):
        self.value = float(value)
        self._button.update()

    def to(self, target: float, ms: int):
        if self._animation.state() == QVariantAnimation.State.Running and self._animation.endValue() == target:
            return
        self._animation.stop()
        if abs(self.value - target) < 1e-3:
            self.value = target
            self._button.update()
            return
        restart(self._animation, self.value, target, max(int(ms * abs(target - self.value)), 1))

    def set(self, value: float):
        self._animation.stop()
        self.value = value
        self._button.update()


class AnimatedButton(QPushButton):
    """Кнопка, которая рисует себя сама. Значок рисует draw_icon(); по умолчанию — символ из шрифта значков."""

    SIZE = 34

    def __init__(self, glyph: str = "", tooltip: str = "", checkable: bool = False):
        super().__init__()
        self._glyph = glyph
        self.setToolTip(tooltip)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Без фокуса, чтобы пробел и стрелки всегда работали как горячие клавиши.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.hover = _Tween(self)
        self.press = _Tween(self)
        self.checked = _Tween(self)
        self.reveal = _Tween(self, 1.0)
        self.toggled.connect(lambda on: self.checked.to(1.0 if on else 0.0, CHECK_MS))
        _buttons.add(self)

    # --- Содержимое -------------------------------------------------------

    def glyph(self) -> str:
        return self._glyph

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    # --- События ----------------------------------------------------------

    def enterEvent(self, event):
        if self.isEnabled():
            self.hover.to(1.0, HOVER_IN_MS)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover.to(0.0, HOVER_OUT_MS)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.press.to(1.0, PRESS_DOWN_MS)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.press.to(0.0, PRESS_UP_MS)
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if not self.isEnabled():
            self.hover.set(0.0)
            self.press.set(0.0)

    def hideEvent(self, event):
        # Спрятанная кнопка не должна «помнить» наведение, когда появится снова.
        self.hover.set(0.0)
        self.press.set(0.0)
        super().hideEvent(event)

    # --- Рисование --------------------------------------------------------

    def icon_color(self) -> QColor:
        h, c = self.hover.value, self.checked.value
        base = mix(_COLORS["text_dim"], _COLORS["text"], 0.55 + 0.45 * h)
        color = mix(base, _COLORS["accent_text"], c)
        if not self.isEnabled():
            color = QColor(_COLORS["text_dim"])
            color.setAlphaF(0.45)
        return color

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(self.reveal.value)
        p.translate(self.width() / 2, self.height() / 2)
        s = 1 - 0.1 * self.press.value
        p.scale(s, s)
        self.draw_background(p)
        self.draw_icon(p, self.icon_color())
        p.end()

    def draw_background(self, p: QPainter):
        w, h = self.width(), self.height()
        rect = QRectF(-w / 2, -h / 2, w, h)
        radius = min(_RADIUS, h / 2)
        hover = self.hover.value
        if hover > 0:
            bg = QColor(_COLORS["surface2"])
            bg.setAlphaF(bg.alphaF() * hover)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, radius, radius)
        checked = self.checked.value
        if checked > 0:
            # Заливка цветом акцента растёт кругом от центра, обрезанная по форме кнопки.
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            p.save()
            p.setClipPath(clip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(_COLORS["accent"], _COLORS["accent_hover"], hover * 0.6))
            r = (w * 0.75) * checked
            p.drawEllipse(QPointF(0, 0), r, r)
            p.restore()

    def draw_icon(self, p: QPainter, color: QColor):
        if not self._glyph:
            return
        font = QFont(_ICON_FONT)
        font.setPointSizeF(13 * (1 + 0.06 * self.hover.value))
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(-self.width() / 2, -self.height() / 2, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)


class _Ticker(QObject):
    """Один общий таймер (~60 кадров/с) для всех иконок, у которых сейчас идёт своя анимация.

    Пружины и ключевые кадры считаются от времени, поэтому кнопке достаточно перерисоваться; таймер
    работает, только пока хоть одна иконка движется, потом сам останавливается."""

    def __init__(self):
        super().__init__()
        self._busy = {}  # кнопка → до какого времени перерисовывать
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def wake(self, button, seconds: float):
        self._busy[button] = time.monotonic() + seconds
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self):
        now = time.monotonic()
        for button, until in list(self._busy.items()):
            try:
                button.update()
            except RuntimeError:  # кнопка уже удалена
                until = 0
            if now > until:
                del self._busy[button]
        if not self._busy:
            self._timer.stop()


_ticker = None


def _wake(button, seconds: float = icons.SETTLE_S):
    global _ticker
    if _ticker is None:
        _ticker = _Ticker()
    _ticker.wake(button, seconds)


class LucideButton(AnimatedButton):
    """Кнопка с иконкой Lucide и её собственной анимацией (icons.ICONS[key]).

    Подложка, нажатие и заливка включённой кнопки — как у всех AnimatedButton."""

    ICON_PX = 20  # размер иконки в кнопке 34×34

    def __init__(self, key: str, tooltip: str = "", checkable: bool = False, **options):
        super().__init__("", tooltip, checkable)
        self._key = key
        self._options = options
        self.motion = icons.Motion()

    @property
    def key(self) -> str:
        return self._key

    def set_icon(self, key: str, **options):
        """Сменить иконку или её вид (например, громкость → без звука, полный экран → выйти)."""
        if key != self._key or options != self._options:
            self._key, self._options = key, options
            self.update()

    def enterEvent(self, event):
        if self.isEnabled():
            self.motion.enter(time.monotonic())
            _wake(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.motion.leave(time.monotonic())
        _wake(self)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.motion.reset()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if not self.isEnabled():
            self.motion.reset()

    def draw_icon(self, p: QPainter, color: QColor):
        self.draw_lucide(p, color, self._key, self.ICON_PX)

    def draw_lucide(self, p: QPainter, color: QColor, key: str, size: float, opacity: float = 1.0):
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.translate(-size / 2, -size / 2)
        p.scale(size / 24, size / 24)
        icons.ICONS[key](p, color, self.motion, time.monotonic(), **self._options)
        p.restore()


class SeekButton(LucideButton):
    """«На 5 секунд назад / вперёд»: стрелка по кругу с цифрой; при наведении проворачивается на пружине."""

    def __init__(self, forward: bool, seconds: int, tooltip: str):
        super().__init__("seek_forward" if forward else "seek_back", tooltip, seconds=seconds)


class StopButton(AnimatedButton):
    """«Стоп»: контур квадрата и залитый квадрат внутри с зазором 2 px (в шрифте такого нет)."""

    SIDE, PEN, GAP = 14.0, 1.5, 2.0

    def __init__(self, tooltip: str):
        super().__init__("", tooltip)

    def draw_icon(self, p: QPainter, color: QColor):
        side, half = self.SIDE, self.PEN / 2
        outer = QRectF(-side / 2, -side / 2, side, side)
        p.setPen(QPen(color, self.PEN))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outer.adjusted(half, half, -half, -half), 2.5, 2.5)
        inset = self.PEN + self.GAP
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(outer.adjusted(inset, inset, -inset, -inset), 1.2, 1.2)


class SettingsButton(LucideButton):
    """Шестерёнка (быстрое меню) с текущей скоростью в правом нижнем углу; не 1× — цветом акцента."""

    def __init__(self, tooltip: str):
        super().__init__("settings", tooltip)
        self._badge = ""
        self._highlight = False

    def set_badge(self, text: str, highlight: bool = False):
        if (text, highlight) != (self._badge, self._highlight):
            self._badge, self._highlight = text, highlight
            self.update()

    def draw_icon(self, p: QPainter, color: QColor):
        super().draw_icon(p, color)
        if not self._badge:
            return
        font = QFont("Segoe UI")
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        w = p.fontMetrics().horizontalAdvance(self._badge) + 6
        h = 12
        rect = QRectF(self.width() / 2 - w - 0.5, self.height() / 2 - h - 0.5, w, h)  # целиком внутри кнопки
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COLORS["accent"] if self._highlight else _COLORS["surface"])
        p.drawRoundedRect(rect, h / 2, h / 2)
        p.setPen(_COLORS["accent_text"] if self._highlight else color)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._badge)


class PlayButton(LucideButton):
    """Большая круглая кнопка: при наведении — мягкое кольцо и толчок значка; ▶ и ⏸ плавно сменяют друг друга."""

    SIZE = 40
    RING = 3  # на сколько кольцо выходит за круг при наведении (кнопка на 2·RING больше круга)
    ICON_PX = 17

    def __init__(self, tooltip: str):
        super().__init__("play", tooltip)
        self.setFixedSize(self.SIZE + 2 * self.RING, self.SIZE + 2 * self.RING)
        self.morph = _Tween(self)  # 0 — ▶, 1 — ⏸

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE + 2 * self.RING, self.SIZE + 2 * self.RING)

    def set_playing(self, playing: bool):
        self.morph.to(1.0 if playing else 0.0, MORPH_MS)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.reveal.value)
        p.translate(self.width() / 2, self.height() / 2)
        h = self.hover.value
        s = (1 - 0.08 * self.press.value) * (1 + 0.04 * h)
        p.scale(s, s)
        r = self.SIZE / 2
        p.setPen(Qt.PenStyle.NoPen)
        if self.isEnabled():
            if h > 0:
                ring = QColor(_COLORS["accent"])
                ring.setAlphaF(0.28 * h)
                p.setBrush(ring)
                p.drawEllipse(QPointF(0, 0), r + self.RING * h, r + self.RING * h)
            p.setBrush(mix(_COLORS["accent"], _COLORS["accent_hover"], h))
            icon = _COLORS["accent_text"]
        else:
            p.setBrush(_COLORS["surface2"])
            icon = _COLORS["text_dim"]
        p.drawEllipse(QPointF(0, 0), r, r)
        # ▶ уменьшается и гаснет, ⏸ вырастает и проявляется (и наоборот).
        t = self.morph.value
        for key, amount, dx in (("play", 1 - t, 1.0), ("pause", t, 0.0)):
            if amount <= 0.01:
                continue
            p.save()
            p.translate(dx, 0)  # треугольник визуально по центру, если чуть сдвинуть вправо
            k = 0.6 + 0.4 * amount
            p.scale(k, k)
            self.draw_lucide(p, icon, key, self.ICON_PX, amount)
            p.restore()
        p.end()

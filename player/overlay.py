"""Надпись поверх видео (например, текущая скорость при удержании кнопки мыши).

Обычный виджет Qt не может лечь поверх окна mpv, поэтому надпись — отдельное
маленькое прозрачное окно без рамки, которое ставится над областью видео.

Вид — «стекло с оттенком акцента» (макет `концепты/уведомление_стекло*.png`): полупрозрачная
капсула цвета поверхности темы, подкрашенная акцентом, блик сверху, обводка цвета акцента
и мягкая тень. Размыть видео под стеклом нельзя (окно не видит кадр mpv) — стекло просто прозрачное.

Появляется «пружинкой» (макет `концепты/уведомление_пружинка.gif`, вариант B1): вырастает с 80 %
с лёгким перелётом и проявляется; исчезает — гаснет и чуть уменьшается. Новое сообщение поверх
видимого (replace_animated=True): старое сразу уходит своей анимацией (его копия — второе окно
`_ghost`), новое выпрыгивает пружинкой. У надписи скорости (replace_animated=False) смена текста
(2.0× → 2.3×) не анимируется.
"""

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene, QLabel

from .anim_button import restart

_OFFSET_FROM_TOP = 20
_SHADOW_MARGIN = 22  # место вокруг капсулы под тень (окно больше капсулы)
_PAD_X, _PAD_Y = 16, 6  # от края капсулы до текста
_SHADOW_BLUR = 16
_SHADOW_OFFSET_Y = 4
_SHADOW_ALPHA = 170
_SURFACE_ALPHA_DARK = 120  # тёмное стекло
_SURFACE_ALPHA_LIGHT = 95  # светлое стекло — прозрачнее, иначе видео почти не просвечивает
_ACCENT_ALPHA = 60
_BORDER_WIDTH = 1.5

SHOW_MS = 650
HIDE_MS = 250
_START_SCALE = 0.8
_OVERSHOOT = 1.2      # перелёт за 100 % (QEasingCurve.OutBack)
_FADE_IN_PART = 0.4   # проявляется за первые 40 % появления
_HIDE_SCALE = 0.92


def _with_alpha(color: str, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(alpha)
    return result


def _blurred(image: QImage, radius: float) -> QImage:
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(0)
    painter = QPainter(result)
    scene.render(painter, QRectF(result.rect()), QRectF(image.rect()))
    painter.end()
    return result


class VideoOverlay(QLabel):
    def __init__(self, parent, replace_animated: bool = False):
        super().__init__(
            parent,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("videoOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Размер и текст — в коде (sizeHint / paintEvent): поля окна под тень стиль Qt затирал своими.
        self._surface = QColor("#1f2026")
        self._accent = QColor("#4f8cff")
        self._surface_alpha = _SURFACE_ALPHA_DARK
        self._shadow = None  # (размер капсулы, картинка тени) — тень пересчитывается, только когда капсула меняет размер
        self._card_cache = None  # (ключ, картинка) — см. _card()
        self._grow = QEasingCurve(QEasingCurve.Type.OutBack)
        self._grow.setOvershoot(_OVERSHOOT)
        self._hiding = False
        self._progress = 1.0  # 0…1 появления (или исчезновения, если _hiding)
        self._hide_from = (1.0, 1.0)  # масштаб и прозрачность, с которых началось исчезновение
        self._replace_animated = replace_animated
        self._ghost = None  # копия уходящего сообщения (только при replace_animated)
        self._frozen_card = None  # у копии: готовая картинка старого сообщения
        self._animation = QVariantAnimation(self)
        self._animation.valueChanged.connect(self._on_progress)
        self._animation.finished.connect(self._on_finished)
        self.hide()

    def set_theme(self, theme: dict):
        # Всё рисуется вручную: у прозрачного окна Qt не рисует фон из стилей.
        self._surface = QColor(theme["surface"])
        self._accent = QColor(theme.get("notify", theme["accent"]))  # «Своя» тема: свой цвет уведомлений
        light = self._surface.lightness() > 128
        self._surface_alpha = _SURFACE_ALPHA_LIGHT if light else _SURFACE_ALPHA_DARK
        self.update()

    def show_text(self, text: str, video_rect: QRect):
        """video_rect — область видео в глобальных координатах экрана."""
        replace = self._replace_animated and self.isVisible()
        if replace:
            self._hand_over_to_ghost()
        self.setText(text)
        self.adjustSize()
        x = video_rect.center().x() - self.width() // 2
        y = video_rect.top() + _OFFSET_FROM_TOP - _SHADOW_MARGIN
        self.move(x, y)
        if replace or not self.isVisible() or self._hiding:
            if self._hiding and self.isVisible() and not replace:
                self._animation.stop()  # исчезала — сразу вернуть целиком, без второй пружинки
                self._hiding = False
                self._progress = 1.0
            else:
                self._hiding = False
                self._progress = 0.0
                restart(self._animation, 0.0, 1.0, SHOW_MS)
            self.show()
        self.raise_()  # новое — поверх уходящего
        self.update()

    def _hand_over_to_ghost(self):
        """Старое сообщение отдать копии: она уходит с анимацией с того вида, что был на экране."""
        if self._ghost is None:
            self._ghost = VideoOverlay(self.parentWidget())
        self._animation.stop()
        self._ghost._fade_out_copy(self._card(), self.pos(), self.size(), *self._scale_and_opacity())

    def _fade_out_copy(self, card: QImage, pos, size, scale: float, opacity: float):
        self._animation.stop()
        self._frozen_card = card
        self.resize(size)
        self.move(pos)
        self._hiding = False
        self._progress = 1.0
        self.show()
        self._start_hide(scale, opacity)

    def hide_animated(self):
        """Плавно спрятать (обычный hide() прячет сразу)."""
        if not self.isVisible() or self._hiding:
            return
        self._start_hide(*self._scale_and_opacity())

    def _start_hide(self, scale: float, opacity: float):
        self._hide_from = (scale, opacity)
        self._hiding = True
        self._progress = 0.0
        restart(self._animation, 0.0, 1.0, HIDE_MS)

    def _on_progress(self, value):
        self._progress = float(value)
        self.update()

    def _on_finished(self):
        if self._hiding:
            self._hiding = False
            self.hide()

    def _scale_and_opacity(self) -> tuple[float, float]:
        t = self._progress
        if self._hiding:
            e = QEasingCurve(QEasingCurve.Type.InOutCubic).valueForProgress(t)
            scale, opacity = self._hide_from
            return scale * (1.0 - (1.0 - _HIDE_SCALE) * e), opacity * (1.0 - e)
        scale = _START_SCALE + (1.0 - _START_SCALE) * self._grow.valueForProgress(t)
        opacity = QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(min(1.0, t / _FADE_IN_PART))
        return scale, opacity

    def sizeHint(self) -> QSize:
        self.ensurePolished()  # шрифт — из style.qss
        metrics = self.fontMetrics()
        m = _SHADOW_MARGIN
        return QSize(metrics.horizontalAdvance(self.text()) + 2 * (_PAD_X + m), metrics.height() + 2 * (_PAD_Y + m))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _pill(self) -> QRectF:
        m = _SHADOW_MARGIN
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _shadow_image(self, pill: QRectF) -> QImage:
        size = pill.size().toSize()
        if self._shadow is None or self._shadow[0] != size:
            m = _SHADOW_MARGIN
            image = QImage(size.width() + 2 * m, size.height() + 2 * m, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, _SHADOW_ALPHA))
            radius = pill.height() / 2
            painter.drawRoundedRect(QRectF(m, m, size.width(), size.height()), radius, radius)
            painter.end()
            self._shadow = (size, _blurred(image, _SHADOW_BLUR))
        return self._shadow[1]

    def _card(self) -> QImage:
        """Готовая картинка уведомления (тень + стекло + текст) в полном размере.

        Анимация масштабирует уже готовую картинку целиком: если перерисовывать текст в каждом
        промежуточном размере, Windows по-разному подгоняет буквы к пикселям и они «дрожат»."""
        if self._frozen_card is not None:
            return self._frozen_card
        color = self.palette().color(QPalette.ColorRole.WindowText)  # цвет — из style.qss
        ratio = self.devicePixelRatioF()
        key = (self.size(), ratio, self.text(), self._surface.name(), self._accent.name(), self._surface_alpha, color.name())
        if self._card_cache is not None and self._card_cache[0] == key:
            return self._card_cache[1]
        image = QImage((QSizeF(self.size()) * ratio).toSize(), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(0)
        pill = self._pill()
        radius = pill.height() / 2
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = _SHADOW_MARGIN
        painter.drawImage(QPointF(pill.x() - m, pill.y() - m + _SHADOW_OFFSET_Y), self._shadow_image(pill))

        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)
        painter.fillPath(path, _with_alpha(self._surface.name(), self._surface_alpha))
        painter.fillPath(path, _with_alpha(self._accent.name(), _ACCENT_ALPHA))
        shine = QLinearGradient(pill.topLeft(), pill.bottomLeft())  # блик сверху — «стекло»
        shine.setColorAt(0.0, QColor(255, 255, 255, 46))
        shine.setColorAt(0.5, QColor(255, 255, 255, 10))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        half = _BORDER_WIDTH / 2
        painter.setPen(QPen(_with_alpha(self._accent.name(), 235), _BORDER_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pill.adjusted(half, half, -half, -half), radius - half, radius - half)

        painter.setPen(color)
        painter.setFont(self.font())
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()
        self._card_cache = (key, image)
        return image

    def paintEvent(self, event):
        scale, opacity = self._scale_and_opacity()
        if opacity <= 0.0:
            return
        card = self._card()
        painter = QPainter(self)
        painter.setOpacity(opacity)
        if scale != 1.0:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            center = self._pill().center()
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)
        painter.drawImage(QPointF(0, 0), card)
        painter.end()

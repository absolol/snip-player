"""Свой заголовок окна в стиле «Капсулы».

Слева капсула с иконкой и меню, по центру — капсула с именем файла (щелчок — сведения о видео),
справа — капсула с круглыми кнопками окна («закрыть» — цвета акцента темы).
"""

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .i18n import tr
from . import anim_button
from .anim_button import LucideButton, restart

# Значки кнопок окна из шрифта Windows (Segoe Fluent Icons / MDL2).
_GLYPHS = {"minimize": "", "maximize": "", "restore": "", "close": ""}

# Обводка круглых кнопок: None — без обводки, "soft" — мягкая, "accent" — цвета акцента.
# Пока выключена; позже включается из настроек через TitleBar.set_outline().
OUTLINE_STYLES = (None, "soft", "accent")

_TITLE_MAX_WIDTH = 520
_PIN_SIZE = 24      # булавка «Поверх всех окон» рядом с иконкой (иконка 20 px)
_PIN_MS = 220       # капсула плавно расширяется, булавка проявляется


class TitlePin(LucideButton):
    """Булавка «Поверх всех окон» в левой капсуле (макет `концепты/поверх_окон_булавка_наклон.png`):
    без заливки, цвета интерфейса, наклон 45° вправо; при наведении подпрыгивает, щелчок выключает режим."""

    ICON_PX = 20

    def __init__(self, tooltip: str):
        super().__init__("pin", tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def icon_color(self) -> QColor:
        return anim_button.mix(anim_button._COLORS["accent"], anim_button._COLORS["accent_hover"], self.hover.value)

    def draw_background(self, p: QPainter):
        pass  # без заливки и без подложки при наведении

    def draw_icon(self, p: QPainter, color: QColor):
        p.rotate(45)
        super().draw_icon(p, color)


def _window_button(glyph: str, tooltip: str, name: str) -> QPushButton:
    button = QPushButton(_GLYPHS[glyph])
    button.setObjectName(name)
    button.setToolTip(tooltip)
    button.setFixedSize(26, 26)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _pill() -> QWidget:
    pill = QWidget()
    pill.setObjectName("titlePill")
    pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return pill


def _repolish(widget: QWidget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class TitleCapsule(QPushButton):
    """Капсула с именем файла. Когда открыт файл, по щелчку показывает сведения о нём
    (стрелка ▾ / ▴ — закрыто / открыто); без файла это просто надпись, за неё тянут окно."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleText")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._title = ""
        self._clickable = False
        self._open = False
        self._max_width = _TITLE_MAX_WIDTH

    @property
    def clickable(self) -> bool:
        return self._clickable

    def set_title(self, text: str, clickable: bool):
        self._title, self._clickable = text, clickable
        self.setProperty("clickable", clickable)
        _repolish(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        self.setToolTip(text + "\n" + tr("Щёлкните, чтобы увидеть сведения о видео") if clickable else text)
        self.setVisible(bool(text))
        self._update_text()

    def set_max_width(self, width: int):
        self._max_width = width
        self._update_text()

    def set_open(self, is_open: bool):
        self._open = is_open
        self.setProperty("open", is_open)
        _repolish(self)
        self._update_text()

    def _update_text(self):
        # Длинное имя сокращается многоточием посередине.
        arrow = ("   ▴" if self._open else "   ▾") if self._clickable else ""
        room = self._max_width - 36 - self.fontMetrics().horizontalAdvance(arrow)
        name = self.fontMetrics().elidedText(f"▶  {self._title}", Qt.TextElideMode.ElideMiddle, max(room, 20))
        self.setText(name + arrow)


class TitleBar(QWidget):
    minimizeClicked = Signal()
    maximizeClicked = Signal()
    closeClicked = Signal()
    titleClicked = Signal()
    pinClicked = Signal()  # щелчок по булавке «Поверх всех окон» — выключить режим

    HEIGHT = 48
    PILL_HEIGHT = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)

        # Слева: иконка (меню «Файл / Вид / Справка» убрано по просьбе пользователя — всё есть в шестерёнке).
        self.left_pill = _pill()
        self.icon_label = QLabel()
        self.icon_label.setObjectName("titleIcon")
        self.icon_label.setFixedSize(18, 18)
        self.left_pill.setFixedHeight(self.PILL_HEIGHT)
        left = QHBoxLayout(self.left_pill)
        left.setContentsMargins(9, 0, 9, 0)
        left.setSpacing(0)
        left.addWidget(self.icon_label)
        self.pin_button = TitlePin(tr("Поверх всех окон — щёлкните, чтобы выключить"))
        self.pin_button.setFixedSize(0, _PIN_SIZE)
        self.pin_button.hide()
        self.pin_button.clicked.connect(self.pinClicked)
        left.addWidget(self.pin_button)
        self._pin_shown = 0.0
        self._pin_animation = QVariantAnimation(self)
        self._pin_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pin_animation.valueChanged.connect(self._on_pin_value)

        # По центру: имя файла (щелчок — сведения о видео).
        self.title_label = TitleCapsule()
        self.title_label.setFixedHeight(self.PILL_HEIGHT - 4)
        self.title_label.clicked.connect(self.titleClicked)

        # Справа: кнопки окна.
        self.right_pill = _pill()
        self.min_button = _window_button("minimize", tr("Свернуть"), "titleButton")
        self.max_button = _window_button("maximize", tr("Развернуть"), "titleButton")
        self.close_button = _window_button("close", tr("Закрыть"), "closeButton")
        self.min_button.clicked.connect(self.minimizeClicked)
        self.max_button.clicked.connect(self.maximizeClicked)
        self.close_button.clicked.connect(self.closeClicked)
        self.right_pill.setFixedHeight(self.PILL_HEIGHT)
        right = QHBoxLayout(self.right_pill)
        right.setContentsMargins(5, 0, 5, 0)
        right.setSpacing(6)
        for button in (self.min_button, self.max_button, self.close_button):
            right.addWidget(button)

        layout = QHBoxLayout(self)
        # Отступ сверху побольше: у окна скруглённые углы, капсулы не должны к ним прилипать.
        layout.setContentsMargins(10, 7, 10, 5)
        layout.setSpacing(8)
        # Боковые капсулы — в местах одной ширины (по большей из них): так капсула с именем стоит ровно по
        # центру окна и не сдвигается, когда левая капсула расширяется (булавка «поверх всех окон»).
        self.left_side, self.right_side = QWidget(), QWidget()
        for side, pill, align in ((self.left_side, self.left_pill, Qt.AlignmentFlag.AlignLeft),
                                  (self.right_side, self.right_pill, Qt.AlignmentFlag.AlignRight)):
            side_layout = QHBoxLayout(side)
            side_layout.setContentsMargins(0, 0, 0, 0)
            side_layout.addWidget(pill, 0, align | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.left_side)
        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.right_side)

        self.set_active(True)
        self.set_outline(None)

    # --- Содержимое -------------------------------------------------------

    def set_icon(self, icon: QIcon):
        self.icon_label.setPixmap(icon.pixmap(18, 18))

    def set_pinned(self, pinned: bool, animated: bool = True):
        """Булавка рядом с иконкой — пока включено «Поверх всех окон». Появляется и уходит плавно."""
        target = 1.0 if pinned else 0.0
        if animated and self.isVisible():
            restart(self._pin_animation, self._pin_shown, target, max(int(_PIN_MS * abs(target - self._pin_shown)), 1))
        else:
            self._pin_animation.stop()
            self._on_pin_value(target)

    def _on_pin_value(self, value):
        t = float(value)
        self._pin_shown = t
        # Капсула расширяется: место под булавку и зазор растут вместе (правое поле чуть меньше —
        # у булавки свой прозрачный край), булавка проявляется.
        self.pin_button.setFixedWidth(round(_PIN_SIZE * t))
        self.left_pill.layout().setSpacing(round(4 * t))
        self.left_pill.layout().setContentsMargins(9, 0, 9 - round(2 * t), 0)
        self.pin_button.reveal.set(t)
        self.pin_button.setVisible(t > 0)
        self._update_title()

    def set_title(self, text: str, clickable: bool = False):
        self.title_label.set_title(text, clickable)
        self._update_title()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_title()

    def _update_title(self):
        side = max(self.left_pill.sizeHint().width(), self.right_pill.sizeHint().width())
        self.left_side.setFixedWidth(side)
        self.right_side.setFixedWidth(side)
        # Капсула с именем не шире свободного места между боковыми капсулами.
        free = self.width() - 2 * side - 80
        self.title_label.set_max_width(max(min(free, _TITLE_MAX_WIDTH), 60))

    # --- Состояние окна ---------------------------------------------------

    def set_maximized(self, maximized: bool):
        self.max_button.setText(_GLYPHS["restore" if maximized else "maximize"])
        self.max_button.setToolTip(tr("Свернуть в окно") if maximized else tr("Развернуть"))

    def set_active(self, active: bool):
        self.title_label.setProperty("active", active)
        _repolish(self.title_label)

    def set_outline(self, style):
        """Обводка круглых кнопок окна: None, "soft" или "accent" (см. OUTLINE_STYLES)."""
        self.setProperty("outline", style or "none")
        for button in (self.min_button, self.max_button, self.close_button):
            _repolish(button)

    def set_max_hover(self, hover: bool):
        """Подсветка кнопки «Развернуть», когда мышь над ней обрабатывает Windows (см. window_chrome)."""
        if self.max_button.property("ncHover") != hover:
            self.max_button.setProperty("ncHover", hover)
            _repolish(self.max_button)

    def set_max_pressed(self, pressed: bool):
        if self.max_button.property("ncPressed") != pressed:
            self.max_button.setProperty("ncPressed", pressed)
            _repolish(self.max_button)

    def is_drag_area(self, widget) -> bool:
        """Можно ли за этот виджет перетаскивать окно: пустое место, капсулы (но не меню и кнопки), иконка,
        имя — пока не открыт файл (потом щелчок по имени показывает сведения о видео)."""
        if widget is self.title_label:
            return not self.title_label.clickable
        return widget in (self, self.left_side, self.right_side, self.left_pill, self.right_pill, self.icon_label)

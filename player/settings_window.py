"""Окно «Настройки» (макет `концепты/настройки_*.png`).

Слева разделы, справа карточки с настройками. Изменения применяются сразу (Prefs.changed),
кнопки «Сохранить» нет. Окно без системного заголовка: свой заголовок-капсула, а перетаскивание,
тень и скруглённые углы — как у главного окна (WindowChrome). Цвета — из style.qss
(раздел «Окно „Настройки“»), самодельные переключатели и иконки красятся через set_theme().
"""

from PySide6.QtCore import QEasingCurve, QEvent, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import dialogs, registration
from .anim_button import restart
from .i18n import LANG, num, tr
from .i18n import rate as rate_text
from .icons import part
from .overlay import SHOW_MS as OVERLAY_SHOW_MS
from .overlay import _SHADOW_MARGIN as OVERLAY_MARGIN
from .overlay import VideoOverlay
from .paths import APP_NAME
from .prefs import RANGES, Prefs
from .themes import NOTIFY_SHADES, SWATCHES, notify_shade
from .title_bar import _window_button
from .window_chrome import WindowChrome

TOGGLE_MS = 160

SECTIONS = {
    tr("Воспроизведение"): '<polygon points="6 3 20 12 6 21 6 3"/>',
    tr("Внешний вид"): '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 '
                   '10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    tr("Окно"): '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/><path d="M6 4v4"/>',
    tr("Скриншоты"): '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
                 '<circle cx="12" cy="13" r="3"/>',
    tr("Обрезка и сохранение"): '<circle cx="6" cy="6" r="3"/><path d="M8.12 8.12 12 12"/><path d="M20 4 8.12 15.88"/>'
                            '<circle cx="6" cy="18" r="3"/><path d="M14.8 14.8 20 20"/>',
    tr("Система"): '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/>'
               '<line x1="12" x2="12" y1="17" y2="21"/>',
}

_colors = {"accent": "#4f8cff", "accent_text": "#ffffff", "surface2": "#2c2e36", "border": "#363842",
           "text": "#e8e9ee", "text_dim": "#9a9ca6"}


class Toggle(QAbstractButton):
    """Переключатель «вкл / выкл»: кружок плавно переезжает, дорожка заливается акцентом."""

    def __init__(self, checked: bool):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_value)
        self.toggled.connect(lambda on: restart(self._animation, self._pos, 1.0 if on else 0.0, TOGGLE_MS))

    def set_silently(self, checked: bool):
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._animation.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def _on_value(self, value):
        self._pos = float(value)
        self.update()

    def paintEvent(self, event):
        t = self._pos
        off_track, on_track = QColor(_colors["surface2"]), QColor(_colors["accent"])
        track = QColor(*(round(a + (b - a) * t) for a, b in zip(off_track.getRgb()[:3], on_track.getRgb()[:3])))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(_colors["border"]), 1) if t < 0.5 else Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0.5, 0.5, 39, 21), 10.5, 10.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_colors["accent_text"] if t >= 0.5 else _colors["text_dim"]))
        p.drawEllipse(QRectF(3 + 18 * t, 3, 16, 16))
        p.end()


class _Icon(QWidget):
    def __init__(self, svg: str, parent=None, size: int = 17):
        super().__init__(parent)
        self.svg, self.size_ = svg, size
        self.active = False
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.size_ / 24, self.size_ / 24)
        part(p, self.svg, QColor(_colors["accent"] if self.active else _colors["text_dim"]))
        p.end()


class Swatch(QAbstractButton):
    """Цветной кружок. same — «как интерфейс»: пунктирное кольцо и точка цвета внутри."""

    def __init__(self, color: str, tooltip: str, same: bool = False):
        super().__init__()
        self.color, self.same = QColor(color), same
        self.selected = False  # не checkable: повторный щелчок по выбранному не должен снимать выбор
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(26, 26)

    def set_color(self, color: str):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(4, 4, 18, 18)
        ring = QColor(_colors["text"])
        if self.same:
            p.setPen(QPen(ring, 1.4, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(circle.adjusted(0.7, 0.7, -0.7, -0.7))
            circle = circle.adjusted(4, 4, -4, -4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(circle)
        if self.selected or self.underMouse():
            ring.setAlpha(255 if self.selected else 90)
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(1, 1, 24, 24))
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class SwatchRow(QWidget):
    """Ряд кружков + «Свой…». chosen(значение) — выбран кружок, own_requested — нажали «Свой…»."""

    chosen = Signal(str)
    own_requested = Signal()

    def __init__(self, items: list[tuple[str, str, str]], same_first: bool = False):
        """items — (значение, цвет, подсказка)."""
        super().__init__()
        self.setObjectName("settingsRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._swatches: dict[str, Swatch] = {}
        for i, (value, color, tooltip) in enumerate(items):
            swatch = Swatch(color, tooltip, same=same_first and i == 0)
            swatch.clicked.connect(lambda _=False, v=value: self.chosen.emit(v))
            self._swatches[value] = swatch
            layout.addWidget(swatch)
        self._own = Swatch("#000000", tr("Свой цвет"))  # виден, только когда выбран свой цвет
        self._own.clicked.connect(self.own_requested)
        self._own.hide()
        layout.addWidget(self._own)
        layout.addSpacing(6)
        button = QPushButton(tr("Свой…"))
        button.setObjectName("editButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(self.own_requested)
        layout.addWidget(button)

    def set_colors(self, colors: dict[str, str]):
        for value, color in colors.items():
            self._swatches[value].set_color(color)

    def set_value(self, value: str, own_color: str | None = None):
        """value — значение кружка; не из ряда (свой цвет) — показать кружок своего цвета выбранным."""
        for key, swatch in self._swatches.items():
            swatch.selected = key == value
            swatch.update()
        own = value not in self._swatches
        self._own.setVisible(own)
        self._own.selected = own
        if own and own_color:
            self._own.set_color(own_color)


class NotifyPreview(QWidget):
    """Предпросмотр уведомления (макет `концепты/своя_тема_предпросмотр.png`): кадр открытого видео и поверх —
    настоящее уведомление (VideoOverlay, то же стекло и пружинка). Само окно уведомления не показывается:
    его готовая картинка (`_card`) рисуется здесь с тем же масштабом и прозрачностью, что в плеере."""

    TEXT = tr("Повтор включён")

    def __init__(self):
        super().__init__()
        self.setFixedHeight(96)
        self._frame: QImage | None = None
        self._border = QColor("#363842")
        self._overlay = VideoOverlay(None)
        self._overlay._animation.valueChanged.connect(self.update)

    def set_frame(self, frame: QImage | None):
        self._frame = frame
        self.update()

    def set_theme(self, theme: dict, stylesheet: str):
        self._border = QColor(theme["border"])
        self._background = QColor("#202127") if QColor(theme["bg"]).lightness() < 128 else QColor("#3a3d46")
        self._overlay.setStyleSheet(stylesheet)  # шрифт и цвет текста — как у уведомлений плеера
        self._overlay.set_theme(theme)
        self._overlay.setText(self.TEXT)
        self._overlay.adjustSize()
        self.play()

    def play(self):
        """Уведомление выпрыгивает заново — видно и цвет, и анимацию."""
        ov = self._overlay
        ov._hiding = False
        ov._progress = 0.0
        restart(ov._animation, 0.0, 1.0, OVERLAY_SHOW_MS)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 10, 10)
        p.setClipPath(shape)
        if self._frame is not None and not self._frame.isNull():
            # «Обложкой»: по ширине, кусок у верха кадра — там, где в плеере появляются уведомления.
            frame = self._frame
            source_h = frame.width() * self.height() / max(self.width(), 1)
            top = max(0.0, min(frame.height() * 0.15, frame.height() - source_h))
            p.drawImage(QRectF(self.rect()), frame, QRectF(0, top, frame.width(), min(source_h, frame.height())))
        else:
            p.fillRect(self.rect(), getattr(self, "_background", QColor("#202127")))
        ov = self._overlay
        scale, opacity = ov._scale_and_opacity()
        if opacity > 0:
            card = ov._card()
            size = card.deviceIndependentSize()
            target = QRectF((self.width() - size.width()) / 2, 14 - OVERLAY_MARGIN, size.width(), size.height())
            p.setOpacity(opacity)
            center = target.center()
            p.translate(center)
            p.scale(scale, scale)
            p.translate(-center)
            p.drawImage(target, card)
            p.resetTransform()
            p.setOpacity(1.0)
        p.setClipping(False)
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)
        p.end()


class Segmented(QWidget):
    """Выбор одного из вариантов: кнопки в общей капсуле, выбранная — цветом акцента."""

    chosen = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str):
        super().__init__()
        self.setObjectName("segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons = {}
        bold = QFont("Segoe UI", 10)
        bold.setWeight(QFont.Weight.DemiBold)  # выбранный вариант — жирный, ширина — по нему
        for value, title in options:
            button = QPushButton(title)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(title) + 26)
            button.clicked.connect(lambda _=False, v=value: self.chosen.emit(v))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button)
        self.set_value(current)

    def set_value(self, value: str):
        if value in self._buttons:
            self._buttons[value].setChecked(True)


class Stepper(QWidget):
    """Число с кнопками − / + (пределы и шаг — prefs.RANGES)."""

    changed = Signal(object)

    def __init__(self, key: str, value, fmt):
        super().__init__()
        self.setObjectName("stepper")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._low, self._high, self._step = RANGES[key]
        self._fmt = fmt
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        self._minus, self._plus = QPushButton("−"), QPushButton("+")
        self._label = QLabel()
        self._label.setObjectName("stepValue")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for button, direction in ((self._minus, -1), (self._plus, 1)):
            button.setObjectName("stepButton")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoRepeat(True)
            button.clicked.connect(lambda _=False, d=direction: self._bump(d))
        layout.addWidget(self._minus)
        layout.addWidget(self._label)
        layout.addWidget(self._plus)
        self.set_value(value)

    def set_value(self, value):
        self._value = value
        self._label.setText(self._fmt(value))
        self._minus.setEnabled(value > self._low)
        self._plus.setEnabled(value < self._high)

    def _bump(self, direction: int):
        value = round(min(max(self._value + direction * self._step, self._low), self._high), 2)
        if isinstance(self._step, int):
            value = int(value)
        if value != self._value:
            self.set_value(value)
            self.changed.emit(value)


def _row(title: str, hint: str | None, control: QWidget | None) -> QWidget:
    row = QWidget()
    row.setObjectName("settingsRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(16, 11, 14, 11)
    layout.setSpacing(16)
    text = QVBoxLayout()
    text.setSpacing(2)
    if title:
        label = QLabel(title)
        label.setObjectName("settingsRowTitle")
        text.addWidget(label)
    if hint:
        label = QLabel(hint)
        label.setObjectName("settingsRowHint")
        label.setWordWrap(True)
        text.addWidget(label)
    layout.addLayout(text, 1)
    if control is not None:
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


def _card(rows: list[QWidget]) -> QFrame:
    card = QFrame()
    card.setObjectName("settingsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(0)
    for i, row in enumerate(rows):
        if i:
            line = QFrame()
            line.setObjectName("settingsLine")
            layout.addWidget(line)
        layout.addWidget(row)
    return card


def _seconds(value) -> str:
    return tr("{n} с", n=num(value))


def _rate(value) -> str:
    return rate_text(value)  # 2.0 → «2,0×», 2.25 → «2,25×» (по-английски — с точкой)


class _Header(QWidget):
    """Заголовок окна: иконка, капсула «Настройки», круглая кнопка «закрыть». Тянуть — за пустое место."""

    maximizeClicked = Signal()  # нужен WindowChrome; окно настроек не разворачивается

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.max_button = object()  # кнопки «Развернуть» нет (None совпал бы с пустым местом окна в WindowChrome)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.icon = QLabel()
        self.icon.setStyleSheet("background: transparent;")
        layout.addWidget(self.icon)
        layout.addStretch(1)
        self.title = QPushButton(tr("Настройки"))
        self.title.setObjectName("settingsTitle")
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.title)
        layout.addStretch(1)
        self.close_button = _window_button("close", tr("Закрыть (Esc)"), "closeButton")  # как у главного окна
        layout.addWidget(self.close_button)

    def is_drag_area(self, child) -> bool:
        return child is self or child is self.title or child is self.icon

    def set_max_hover(self, hover: bool):
        pass

    def set_max_pressed(self, pressed: bool):
        pass


class SettingsWindow(QWidget):
    def __init__(self, owner, prefs: Prefs, themes: dict[str, dict], current_theme):
        super().__init__(owner, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("settingsWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(f"{tr('Настройки')} — {APP_NAME}")
        self.resize(820, 600)
        self.setMinimumSize(760, 480)
        self.prefs = prefs
        self._owner = owner
        self._themes = themes
        self._current_theme = current_theme  # функция: id темы сейчас
        self._icons: list[_Icon] = []
        self._toggles: list[Toggle] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 14)
        layout.setSpacing(10)
        self.header = _Header(self)
        self.header.close_button.clicked.connect(self.close)
        layout.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(14)
        layout.addLayout(body, 1)
        side = QWidget()
        side.setObjectName("settingsSide")
        side.setFixedWidth(210)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 4, 0, 0)
        side_layout.setSpacing(2)
        self.pages = QStackedWidget()
        self._nav = QButtonGroup(self)
        builders = [self._playback_page, self._look_page, self._window_page, self._screenshots_page,
                    self._export_page, self._system_page]
        for index, ((name, svg), build) in enumerate(zip(SECTIONS.items(), builders)):
            button = QPushButton(name)
            button.setObjectName("settingsNav")
            button.setCheckable(True)
            button.setFixedHeight(36)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            icon = _Icon(svg, button)
            icon.move(12, 9)
            self._icons.append(icon)
            button.toggled.connect(lambda on, i=index: on and self._show_page(i))
            self._nav.addButton(button)
            side_layout.addWidget(button)
            self.pages.addWidget(self._page(name, build()))
        side_layout.addStretch(1)
        body.addWidget(side)
        body.addWidget(self.pages, 1)
        self._nav.buttons()[0].setChecked(True)

        self.chrome = WindowChrome(self, self.header)
        self.chrome.install()
        self.chrome.disable_maximize()
        self.prefs.changed.connect(self._sync)

    # --- Страницы ---------------------------------------------------------

    def _page(self, title: str, cards: list[QWidget]) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("settingsPageTitle")
        layout.addWidget(label)
        for card in cards:
            layout.addWidget(card)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    def open_page(self, index: int):
        """Открыть раздел (например, «Внешний вид» из шестерёнки → «Оформление…»)."""
        self._nav.buttons()[index].setChecked(True)

    def _show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        for i, icon in enumerate(self._icons):
            icon.active = i == index
            icon.update()

    def _toggle(self, key: str) -> Toggle:
        toggle = Toggle(self.prefs.get(key))
        toggle.toggled.connect(lambda on: self.prefs.set(key, on))
        toggle.setProperty("prefKey", key)
        self._toggles.append(toggle)
        return toggle

    def _segmented(self, key: str, options) -> Segmented:
        control = Segmented(options, self.prefs.get(key))
        control.chosen.connect(lambda value: self.prefs.set(key, value))
        self._segments = getattr(self, "_segments", {})
        self._segments[key] = control
        return control

    def _stepper(self, key: str, fmt) -> Stepper:
        control = Stepper(key, self.prefs.get(key), fmt)
        control.changed.connect(lambda value: self.prefs.set(key, value))
        self._steppers = getattr(self, "_steppers", {})
        self._steppers[key] = control
        return control

    def _playback_page(self):
        return [
            _card([_row(tr("Продолжать с места, где остановились"), tr("Для каждого видео запоминается своё место"),
                        self._toggle("resume")),
                   _row(tr("В конце видео"), None, self._segmented(
                       "end_action", [("stop", tr("Остановиться")), ("next", tr("Следующее в папке")),
                                      ("repeat", tr("Повтор"))]))]),
            _card([_row(tr("Перемотка стрелками ← →"), None, self._stepper("seek_step", _seconds)),
                   _row(tr("Перемотка с Shift"), None, self._stepper("seek_small_step", _seconds)),
                   _row(tr("Шаг громкости ↑ ↓"), None, self._stepper("volume_step", lambda v: tr("{n} %", n=v)))]),
            _card([_row(tr("Ускорение при удержании"), tr("Мышь на видео или пробел: сначала эта скорость…"),
                        self._stepper("hold_rate", _rate)),
                   _row(tr("Предел ускорения"), tr("…а если потянуть мышь вправо — до этой"),
                        self._stepper("hold_rate_max", _rate))]),
        ]

    def _look_page(self):
        # Оформление — только своё (строки «Тема» нет, 30.10.2026): основа, цвет интерфейса, цвет уведомлений.
        self._accent_row = SwatchRow([(color, color, name) for color, name in SWATCHES])
        self._accent_row.chosen.connect(lambda color: self.prefs.set("custom_accent", color))
        self._accent_row.own_requested.connect(self._choose_accent)
        self._notify_row = SwatchRow([(key, "#000000", name) for key, name in NOTIFY_SHADES], same_first=True)
        self._notify_row.chosen.connect(lambda shade: self.prefs.set("custom_notify", shade))
        self._notify_row.own_requested.connect(self._choose_notify)
        self.preview = NotifyPreview()
        # Любой щелчок по кружку — уведомление выпрыгивает заново (и по уже выбранному: посмотреть ещё раз).
        for row in (self._accent_row, self._notify_row):
            row.chosen.connect(lambda _value: self.preview.play())
        preview_row = QWidget()
        preview_row.setObjectName("settingsRow")
        preview_layout = QVBoxLayout(preview_row)
        preview_layout.setContentsMargins(16, 10, 14, 12)
        preview_layout.setSpacing(6)
        preview_title = QLabel(tr("Так будут выглядеть уведомления"))
        preview_title.setObjectName("settingsRowTitle")
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview)
        self._custom_card = _card([
            _row(tr("Основа"), tr("Фон и текст подбираются сами — всё остаётся читаемым"),
                 self._segmented("custom_base", [("dark", tr("Тёмная")), ("light", tr("Светлая"))])),
            _row(tr("Цвет интерфейса"), tr("Кнопки, шкала, выделение, кнопка «закрыть»"), self._accent_row),
            _row(tr("Цвет уведомлений"), tr("Оттенки цвета интерфейса: как он, светлее, глубже, соседние"),
                 self._notify_row),
            preview_row,
        ])
        self._update_custom_rows()
        # Язык — первой карточкой (макет `концепты/язык_настройки_*.png`). Название на обоих языках: если
        # переключили по ошибке, строку легко найти. Действует после перезапуска (i18n.py).
        language = Segmented([("ru", "Русский"), ("en", "English")], self.prefs.get("language") or LANG)
        language.chosen.connect(self._choose_language)
        self._segments = getattr(self, "_segments", {})
        self._segments["language"] = language
        return [
            _card([_row("Язык · Language", tr("Сменится после перезапуска плеера"), language)]),
            self._custom_card,
            _card([_row(tr("Обводка кнопок окна"), tr("Кружки «свернуть / развернуть / закрыть» в заголовке"),
                        self._segmented("window_outline", [("none", tr("Нет")), ("soft", tr("Мягкая")),
                                                           ("accent", tr("Акцент"))])),
                   _row(tr("Кнопка «Стоп» на панели"), None, self._toggle("show_stop"))]),
            _card([_row(tr("Уведомления поверх видео"), tr("«Скриншот сохранён», «Повтор включён» и т. п."),
                        self._toggle("messages")),
                   _row(tr("Сколько держать уведомление"), None, self._stepper("message_seconds", _seconds))]),
        ]

    def _window_page(self):
        return [_card([_row(tr("Открывать новые видео в том же окне"),
                            tr("Двойной щелчок по видео, когда плеер уже открыт, — файл откроется в нём, а не в новом "
                               "окне. Выключение подействует со следующего запуска плеера"),
                            self._toggle("single_instance"))])]

    def _screenshots_page(self):
        folder = QWidget()
        folder.setObjectName("settingsRow")
        layout = QHBoxLayout(folder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._folder_label = QLabel()
        self._folder_label.setObjectName("settingsPath")
        layout.addWidget(self._folder_label)
        change = QPushButton(tr("Изменить…"))
        change.setObjectName("editButton")
        change.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        change.clicked.connect(self._choose_folder)
        layout.addWidget(change)
        self._update_folder_label()
        return [_card([_row(tr("Папка"), None, folder),
                       _row(tr("Формат"), tr("PNG — без потерь, JPG — файлы меньше"),
                            self._segmented("screenshot_format", [("png", "PNG"), ("jpg", "JPG")])),
                       _row(tr("Копировать в буфер обмена"), tr("Чтобы сразу вставить скриншот в чат или документ"),
                            self._toggle("screenshot_clipboard"))])]

    def _export_page(self):
        return [_card([
            _row(tr("Кодирование"), tr("Видеокарта — быстрее; процессор — если с видеокартой что-то не так"),
                 self._segmented("encoder", [("auto", tr("Видеокарта")), ("cpu", tr("Процессор"))])),
            _row(tr("Качество по умолчанию"), tr("«Без потерь» — точно по кадру; «Быстро» — по ключевым кадрам"),
                 self._segmented("export_quality", [("lossless", tr("Без потерь")), ("fast", tr("Быстро"))])),
            _row(tr("Способ по умолчанию"), tr("«С удалением» — старый файл уходит в корзину"),
                 self._segmented("save_mode", [("copy", tr("Как копию")), ("replace", tr("С удалением"))])),
        ])]

    def _system_page(self):
        buttons = QWidget()
        buttons.setObjectName("settingsRow")
        layout = QHBoxLayout(buttons)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._install_button = QPushButton(tr("Сделать плеером для видео"))
        self._install_button.setObjectName("splitButton")
        self._uninstall_button = QPushButton(tr("Убрать регистрацию"))
        self._uninstall_button.setObjectName("editButton")
        for button in (self._install_button, self._uninstall_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout.addWidget(button)
        self._install_button.clicked.connect(self._register)
        self._uninstall_button.clicked.connect(self._unregister)
        self._status = QLabel()
        self._status.setObjectName("settingsStatus")
        self._update_status()
        return [_card([
            _row(tr("Плеер для видео в Windows"),
                 tr("Добавляет «Snip Player» в «Открыть с помощью» (только для вашего пользователя). Чтобы видео "
                    "открывались двойным щелчком: Открыть с помощью → Выбрать другое приложение → Snip Player → Всегда"),
                 None),
            _row(tr("Сейчас"), None, self._status),
            _row(None, None, buttons),
        ])]

    # --- Действия ---------------------------------------------------------

    def _update_custom_rows(self):
        accent = self.prefs.get("custom_accent")
        self._accent_row.set_value(accent, accent)
        self._notify_row.set_colors({key: notify_shade(accent, key) for key, _ in NOTIFY_SHADES})
        self._notify_row.set_value(self.prefs.get("custom_notify"), self.prefs.get("custom_notify_color"))

    def _choose_language(self, lang: str):
        """Язык меняется после перезапуска: плеер сразу предлагает перезапуститься (вопрос — на новом языке)."""
        self.prefs.set("language", lang)
        if lang != LANG:
            self._owner.offer_restart(lang, self)

    def _pick_color(self, initial: str, title: str) -> str | None:
        color = QColorDialog.getColor(QColor(initial), self, title)
        return color.name() if color.isValid() else None

    def _choose_accent(self):
        color = self._pick_color(self.prefs.get("custom_accent"), tr("Цвет интерфейса"))
        if color:
            self.prefs.set("custom_accent", color)

    def _choose_notify(self):
        shade = self.prefs.get("custom_notify")
        start = self.prefs.get("custom_notify_color") if shade == "own" else \
            notify_shade(self.prefs.get("custom_accent"), shade)
        color = self._pick_color(start, tr("Цвет уведомлений"))
        if color:
            self.prefs.set("custom_notify_color", color)
            self.prefs.set("custom_notify", "own")

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Папка для скриншотов"), self._owner.screenshot_folder())
        if folder:
            self.prefs.set("screenshot_dir", folder)

    def _update_folder_label(self):
        folder = self._owner.screenshot_folder()
        metrics = QFontMetrics(self._folder_label.font())
        self._folder_label.setText(metrics.elidedText(folder, Qt.TextElideMode.ElideMiddle, 300))
        self._folder_label.setToolTip(folder)

    def _update_status(self):
        state = registration.status()
        text = {"ok": tr("✓ Зарегистрирован"), "none": tr("Не зарегистрирован"),
                "moved": tr("Зарегистрирован для другой папки — нажмите «Сделать плеером» ещё раз"),
                "outdated": tr("Регистрация устарела — нажмите «Сделать плеером» ещё раз")}[state]
        self._status.setText(text)
        self._status.setProperty("ok", state == "ok")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._uninstall_button.setEnabled(state != "none")

    def _register(self):
        try:
            registration.install()
        except OSError as error:
            dialogs.error(self, tr("Не удалось сделать плеером для видео"), tr("Запись в реестр не удалась: {error}", error=error))
        self._update_status()

    def _unregister(self):
        try:
            registration.uninstall()
        except OSError as error:
            dialogs.error(self, tr("Не удалось убрать регистрацию"), tr("Запись в реестр не удалась: {error}", error=error))
        self._update_status()

    # --- Связь с плеером -------------------------------------------------

    def _sync(self, key: str):
        """Значение поменялось не здесь (или поправлено, как hold_rate ↔ предел) — показать его."""
        value = self.prefs.get(key)
        for toggle in self._toggles:
            if toggle.property("prefKey") == key and toggle.isChecked() != value:
                toggle.set_silently(value)
        if key in getattr(self, "_segments", {}):
            self._segments[key].set_value(value)
        if key in getattr(self, "_steppers", {}):
            self._steppers[key].set_value(value)
        if key == "screenshot_dir":
            self._update_folder_label()
        if key.startswith("custom_"):
            self._update_custom_rows()

    def set_theme(self, theme_id: str, theme: dict, icon):
        _colors.update({k: theme[k] for k in _colors})
        self.header.icon.setPixmap(icon.pixmap(20, 20))
        self.chrome.set_border_color(theme["border"])
        if hasattr(self, "preview"):
            self.preview.set_theme(theme, self._owner.styleSheet())
        for widget in self._icons + self._toggles + self.findChildren(Swatch):
            widget.update()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and getattr(self, "chrome", None) is not None:
            handled, result = self.chrome.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def event(self, event):
        # Горячие клавиши плеера (пробел, стрелки, Esc…) действуют во всём приложении; пока активно
        # окно настроек, клавиши — его: иначе Esc не закрывал окно, а пробел ставил видео на паузу.
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

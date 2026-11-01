"""Нижняя панель управления: таймлайн, кнопки, время, скорость, громкость.

Кнопки — анимированные, с иконками Lucide и их собственными анимациями (anim_button.py, icons.py).
Кнопки кадров видны только на паузе (выезжают и уезжают), ползунок громкости выезжает при наведении
на динамик, в узком окне лишние кнопки плавно сжимаются к центру и исчезают.
"""

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .anim_button import AnimatedButton, LucideButton, PlayButton, SeekButton, SettingsButton, StopButton, restart
from .i18n import num, tr
from .timeline import Timeline
from .utils import format_time

QWIDGETSIZE_MAX = 16777215  # «без ограничения» для maximumHeight
GROW_MS = 420  # открытие / закрытие редактора: панель растёт (SlideHolder.grow_to)

# Значки из системного шрифта Windows (Segoe Fluent Icons / Segoe MDL2 Assets).
ICONS = {
    "open": "",
    "volume": "",
    "mute": "",
    "fullscreen": "",
    "window": "",
    "theme": "",
    "settings": "",
    "prev_file": "",
    "next_file": "",
    "frame_back": "",
    "frame_forward": "",
    "screenshot": "",
    "repeat": "",
    "pin": "",
    "cut": "",
    "undo": "",
    "redo": "",
}

SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

REVEAL_MS = 220          # выезд / уезд кнопок кадров и ползунка громкости
VOLUME_CLOSE_DELAY_MS = 500  # ползунок громкости прячется не сразу, а когда мышь ушла и не вернулась


def icon_button(icon: str, tooltip: str, checkable: bool = False) -> AnimatedButton:
    """Кнопка со значком из шрифта Windows (для мест, где ещё нет иконки Lucide, — например, в редакторе)."""
    return AnimatedButton(ICONS[icon], tooltip, checkable)


def lucide_button(key: str, tooltip: str, checkable: bool = False, **options) -> LucideButton:
    """Кнопка с иконкой Lucide и её собственной анимацией (icons.py)."""
    return LucideButton(key, tooltip, checkable, **options)


def _speed_text(speed: float) -> str:
    """0.25 → «0,25×», 1.0 → «1×» (по-английски — с точкой)."""
    return num(speed) + "×"


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("editSeparator")
    line.setFixedSize(1, 22)
    return line


class Collapsible(QWidget):
    """Ряд виджетов, который плавно выезжает (ширина 0 → полная) и уезжает обратно.

    Два независимых «крана»: open (например, кнопки кадров — только на паузе) и fit (в узком окне
    кнопка не помещается). Видимая доля = open × fit. Виджеты внутри не сжимаются — их открывает /
    закрывает край контейнера (anchor="left") или они сжимаются к своему центру (anchor="center");
    анимированные кнопки вдобавок гаснут. Совсем закрытый ряд прячется, чтобы не оставлять зазоров."""

    def __init__(self, widgets, leading: int = 0, spacing: int = 6, opened: bool = True, anchor: str = "left",
                 gap_before: int = 0, gap_after: int = 0):
        super().__init__()
        self._inner = QWidget(self)
        layout = QHBoxLayout(self._inner)
        # gap_before / gap_after — зазор до соседней кнопки; он сжимается вместе с рядом (без рывка в конце).
        layout.setContentsMargins(gap_before, 0, gap_after, 0)
        layout.setSpacing(spacing)
        if leading:
            layout.addSpacing(leading)
        for widget in widgets:
            layout.addWidget(widget)
        self._widgets = widgets
        self._anchor = anchor
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._open = _Factor(self, 1.0 if opened else 0.0)
        self._fit = _Factor(self, 1.0)
        self._apply()

    @property
    def opened(self) -> bool:
        return self._open.target == 1.0

    @property
    def fits(self) -> bool:
        return self._fit.target == 1.0

    def full_width(self) -> int:
        return self._inner.layout().sizeHint().width()

    def _visible_part(self) -> float:
        return self._open.value * self._fit.value

    def sizeHint(self) -> QSize:
        return QSize(round(self.full_width() * self._visible_part()), self._inner.layout().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_open(self, opened: bool, animated: bool = True):
        self._open.to(1.0 if opened else 0.0, animated and self._on_screen())

    def set_fit(self, fits: bool, animated: bool = True):
        self._fit.to(1.0 if fits else 0.0, animated and self._on_screen())

    def _on_screen(self) -> bool:
        # Сам закрытый ряд спрятан, поэтому смотрим на панель вокруг: видна она — значит, анимировать.
        parent = self.parentWidget()
        return parent is not None and parent.isVisible()

    def _apply(self):
        part = self._visible_part()
        for widget in self._widgets:
            if isinstance(widget, AnimatedButton):
                widget.reveal.set(part)
        full = self._inner.layout().sizeHint()
        width = round(full.width() * part)
        self.setFixedWidth(width)
        self._place_inner()
        target = self._open.target * self._fit.target
        # Закрытый ряд — спрятать (иначе соседние кнопки оставляли бы вокруг него пустые зазоры).
        if part == 0 and target == 0:
            self.hide()  # явно: иначе Qt показывает ряд снова, когда показывается панель
        elif target > 0 and self.isHidden() and self.parentWidget() is not None:
            # Без родителя (ряд ещё не вставлен в панель) show() на миг показал бы его отдельным окном
            # с рамкой — при запуске плеера мелькали два маленьких окна. В панели он покажется сам.
            self.show()
        self.updateGeometry()
        # Сразу же раздвинуть соседей (до панели включительно): иначе Qt сдвинет их лишь на следующем
        # шаге, и на один кадр растущая кнопка наезжала на соседнюю.
        w = self.parentWidget()
        while w is not None:
            if w.layout() is not None:
                w.layout().activate()
            if w.objectName() == "controlBar" or w.isWindow():
                break
            w = w.parentWidget()

    def _place_inner(self):
        full = self._inner.layout().sizeHint()
        x = 0 if self._anchor == "left" else round((self.width() - full.width()) / 2)
        self._inner.setGeometry(x, max((self.height() - full.height()) // 2, 0), full.width(), full.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_inner()


class _Factor:
    """Плавное число 0…1 для Collapsible: при каждом шаге контейнер пересчитывает ширину."""

    def __init__(self, owner: Collapsible, value: float):
        self.value = self.target = value
        self._owner = owner
        self._animation = QVariantAnimation(owner)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_value)

    def _on_value(self, value):
        self.value = float(value)
        self._owner._apply()

    def to(self, target: float, animated: bool):
        if target == self.target:
            return
        self.target = target
        self._animation.stop()
        if not animated:
            self.value = target
            self._owner._apply()
            return
        if target > 0 and self._owner.isHidden():
            self._owner.show()  # показать (пока нулевой ширины), чтобы было видно, как он выезжает
        restart(self._animation, self.value, target, max(int(REVEAL_MS * abs(target - self.value)), 1))


class VolumeBox(QWidget):
    """Динамик + ползунок громкости, который выезжает при наведении и прячется, когда мышь ушла."""

    def __init__(self, mute_button: AnimatedButton, slider: QSlider):
        super().__init__()
        self.slider = slider
        self.slider_box = Collapsible([slider], leading=4, opened=False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(mute_button)
        layout.addWidget(self.slider_box)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(VOLUME_CLOSE_DELAY_MS)
        self._close_timer.timeout.connect(self._close_if_left)
        slider.sliderReleased.connect(lambda: self._close_timer.start())

    def full_width(self) -> int:
        return self.layout().itemAt(0).widget().width() + self.slider_box.full_width()

    def enterEvent(self, event):
        self._close_timer.stop()
        self.slider_box.set_open(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._close_timer.start()
        super().leaveEvent(event)

    def _close_if_left(self):
        if self.slider.isSliderDown() or self.underMouse():
            return  # громкость ещё тянут или мышь вернулась
        self.slider_box.set_open(False)


class SlideHolder(QWidget):
    """Контейнер, который можно плавно «опустить»: панель внутри не сжимается,
    а уезжает вниз за край, пока высота контейнера уменьшается до нуля."""

    def __init__(self, child: QWidget, parent=None):
        super().__init__(parent)
        self._child = child
        child.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._animation.setDuration(250)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shown = True

        self._animation.finished.connect(self._on_animation_finished)

        # Плавная смена высоты при открытии / закрытии редактора (макет `концепты/редактор_появление.gif`,
        # вариант A): нижний край панели закреплён, ряд редактора выезжает из-под видео.
        self._grow = QVariantAnimation(self)
        # Плавный разгон и торможение: с OutCubic почти половина пути проходила за первые 0,09 с — видео
        # уменьшалось рывком в начале.
        self._grow.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._grow.valueChanged.connect(self._on_grow_value)
        self._grow.finished.connect(self._on_grow_finished)
        self._grow_done = None
        self._grow_step = None
        self._grow_after = None
        self._anchor_bottom = False

    def sizeHint(self) -> QSize:
        return self._child.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def resizeEvent(self, event):
        self._place_child()

    def _place_child(self):
        height = self._child.sizeHint().height()
        top = self.height() - height if self._anchor_bottom else 0
        self._child.setGeometry(0, top, self.width(), height)

    def child_resized(self):
        """Вызывать, когда содержимое панели меняет высоту (например, открыт редактор)."""
        self.updateGeometry()
        self._place_child()

    def grow_to(self, target: int, on_finished=None, on_step=None, after_step=None):
        """Плавно сменить высоту с текущей на target (нижний край на месте), затем вызвать on_finished.
        on_step(высота) — на каждом кадре до раскладки (шкала меняет толщину в том же кадре);
        after_step() — после раскладки (во весь экран: окно панели подгоняет высоту и место)."""
        self._grow_done = on_finished
        self._grow_step = on_step
        self._grow_after = after_step
        self.setFixedHeight(self.height())  # до первого кадра — прежняя высота (иначе Qt сразу даст новую)
        self._anchor_bottom = True
        self._place_child()
        restart(self._grow, self.height(), target, GROW_MS)

    def _on_grow_value(self, value):
        # Всё за один кадр и сразу (без отложенной раскладки Qt): толщина шкалы, высота панели,
        # раскладка панели и окна. Иначе на отдельных кадрах высота уже новая, а место панели
        # в окне ещё старое, и нижний ряд кнопок прыгал на 10–30 px.
        if self._grow_step is not None:
            self._grow_step(round(value))
        self.setFixedHeight(round(value))
        if self._child.layout() is not None:
            self._child.layout().activate()
        self._place_child()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()
        if self._grow_after is not None:
            self._grow_after()

    def _on_grow_finished(self):
        self._grow_step = None
        self._grow_after = None
        self._anchor_bottom = False
        self.setMinimumHeight(0)
        self.setMaximumHeight(QWIDGETSIZE_MAX)
        done, self._grow_done = self._grow_done, None
        if done is not None:
            done()
        self.child_resized()

    def _on_animation_finished(self):
        if self._shown:
            self.setMaximumHeight(QWIDGETSIZE_MAX)  # снять ограничение: панель может вырасти

    @property
    def shown(self) -> bool:
        return self._shown

    def slide(self, show: bool, animated: bool = True):
        if show == self._shown:
            return
        self._shown = show
        target = self._child.sizeHint().height() if show else 0
        self._animation.stop()
        if animated:
            self._animation.setStartValue(self.height())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.setMaximumHeight(QWIDGETSIZE_MAX if show else 0)


class ControlBar(QWidget):
    playClicked = Signal()
    stopClicked = Signal()
    seekRequested = Signal(int)
    scrubRequested = Signal(int)
    volumeChanged = Signal(int)
    muteClicked = Signal()
    rateChanged = Signal(float)
    editClicked = Signal()
    fullscreenClicked = Signal()
    seekByClicked = Signal(int)       # перемотка на столько миллисекунд (−5 с / +5 с)
    fileStepClicked = Signal(int)     # −1 — предыдущее видео в папке, +1 — следующее
    frameStepClicked = Signal(int)    # −1 — кадр назад, +1 — кадр вперёд
    screenshotClicked = Signal()
    repeatToggled = Signal(bool)
    onTopToggled = Signal(bool)

    SEEK_STEP_MS = 5000

    def __init__(self, edit_bar: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("controlBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Панель редактора живёт внутри нижней панели и по умолчанию скрыта.
        self.edit_bar = edit_bar
        self.edit_bar.hide()

        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.seekRequested)
        self._duration = 0
        # При перемотке мышью счётчик обновляется сразу, не дожидаясь таймера окна.
        self.timeline.scrubRequested.connect(self.scrubRequested)
        self.timeline.seekRequested.connect(lambda ms: self._show_time(ms))
        self.timeline.scrubRequested.connect(lambda ms: self._show_time(ms))

        self.play_button = PlayButton(tr("Воспроизведение / пауза (Пробел)"))
        # «Стоп» по умолчанию спрятан (пауза + перемотка в начало делают то же); включится в настройках.
        self.stop_button = StopButton(tr("Стоп"))
        self.back_button = SeekButton(False, self.SEEK_STEP_MS // 1000, tr("Назад на 5 секунд (←)"))
        self.forward_button = SeekButton(True, self.SEEK_STEP_MS // 1000, tr("Вперёд на 5 секунд (→)"))
        self.prev_file_button = lucide_button("prev_file", tr("Предыдущее видео в папке (PgUp)"))
        self.next_file_button = lucide_button("next_file", tr("Следующее видео в папке (PgDn)"))
        self.frame_back_button = lucide_button("frame_back", tr("Кадр назад (,)"))
        self.frame_forward_button = lucide_button("frame_forward", tr("Кадр вперёд (.)"))
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("timeLabel")

        self.mute_button = lucide_button("volume", tr("Без звука (M)"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume_slider.setToolTip(tr("Громкость (↑ / ↓)"))
        self.volume_slider.valueChanged.connect(self.volumeChanged)
        self.volume_box = VolumeBox(self.mute_button, self.volume_slider)

        self.screenshot_button = lucide_button("screenshot", tr("Скриншот кадра (P) — в «Изображения» и в буфер обмена"))
        self.edit_button = lucide_button("cut", tr("Обрезка видео (C)"), checkable=True)
        # Шестерёнка: быстрое меню (скорость, повтор, поверх всех окон, тема); в углу — текущая скорость.
        self.settings_button = SettingsButton(tr("Скорость, поверх всех окон, настройки"))
        self.fullscreen_button = lucide_button("fullscreen", tr("Во весь экран (F)"))
        self._build_quick_menu()

        self.play_button.clicked.connect(self.playClicked)
        self.stop_button.clicked.connect(self.stopClicked)
        self.mute_button.clicked.connect(self.muteClicked)
        self.edit_button.clicked.connect(self.editClicked)
        self.settings_button.clicked.connect(self._show_quick_menu)
        self.fullscreen_button.clicked.connect(self.fullscreenClicked)
        self.back_button.clicked.connect(lambda: self.seekByClicked.emit(-self.SEEK_STEP_MS))
        self.forward_button.clicked.connect(lambda: self.seekByClicked.emit(self.SEEK_STEP_MS))
        self.prev_file_button.clicked.connect(lambda: self.fileStepClicked.emit(-1))
        self.next_file_button.clicked.connect(lambda: self.fileStepClicked.emit(1))
        self.frame_back_button.clicked.connect(lambda: self.frameStepClicked.emit(-1))
        self.frame_forward_button.clicked.connect(lambda: self.frameStepClicked.emit(1))
        self.screenshot_button.clicked.connect(self.screenshotClicked)

        # Выдвижные ряды несут зазор до соседа в себе (gap_before / gap_after), а у самого ряда кнопок
        # промежутков нет: иначе в конце анимации исчезал промежуток ряда, и соседи прыгали на 6 px.
        G = 6
        # Пред. / след. видео — только если в папке есть другие видео; кадры — только на паузе.
        self.prev_box = Collapsible([self.prev_file_button], gap_after=G, opened=False, anchor="center")
        self.next_box = Collapsible([self.next_file_button], gap_before=G, opened=False, anchor="center")
        self.stop_box = Collapsible([self.stop_button], gap_before=G, opened=False, anchor="center")
        self.frame_group = Collapsible([_separator(), self.frame_back_button, self.frame_forward_button],
                                       gap_before=G + 4, opened=False)  # откроется на паузе с открытым видео
        self.screenshot_box = Collapsible([self.screenshot_button, _separator()], spacing=10,
                                          gap_after=10, anchor="center")

        # Что прячется, когда окно слишком узкое, — по очереди, пока остальное не поместится.
        # Всё спрятанное доступно и так: клавишами (, . PgUp PgDn P).
        self._optional_groups = [
            [self.frame_group],               # , и .
            [self.prev_box, self.next_box],   # PgUp / PgDn
            [self.screenshot_box],            # P
        ]

        buttons = QHBoxLayout()
        buttons.setSpacing(0)
        for item in (self.prev_box, self.back_button, G, self.play_button, G, self.forward_button,
                     self.next_box, self.stop_box, self.frame_group, 14, self.time_label, None,
                     self.volume_box, 14, _separator(), 10, self.screenshot_box,
                     self.edit_button, G, self.settings_button, G, self.fullscreen_button):
            if item is None:
                buttons.addStretch(1)
            elif isinstance(item, int):
                buttons.addSpacing(item)
            else:
                buttons.addWidget(item)
        self._buttons_row = buttons
        # Закрытые ряды прятались ещё до того, как попали в панель; при переносе в панель Qt снова
        # делает их видимыми — спрятать заново.
        for box in (self.prev_box, self.next_box, self.stop_box, self.volume_box.slider_box):
            box._apply()

        layout = QVBoxLayout(self)
        # Круглая кнопка «Пуск» выше остальных (вокруг неё кольцо при наведении) — поля чуть меньше,
        # чтобы панель осталась прежней высоты.
        layout.setContentsMargins(12, 6, 12, 7)
        layout.setSpacing(1)
        layout.addWidget(self.edit_bar)
        layout.addWidget(self.timeline)
        layout.addLayout(buttons)

        self.set_media_loaded(False)

    # --- Обновление из окна -----------------------------------------------

    def set_media_loaded(self, loaded: bool):
        self._media_loaded = loaded
        self.frame_group.set_open(loaded and not self.play_button_playing(), animated=False)
        for widget in (self.play_button, self.stop_button, self.timeline, self.edit_button, self.back_button,
                       self.forward_button, self.prev_file_button, self.next_file_button, self.frame_back_button,
                       self.frame_forward_button, self.screenshot_button):
            widget.setEnabled(loaded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_buttons()

    def _fit_buttons(self):
        """В узком окне плавно прячет необязательные кнопки, чтобы остальные не налезали друг на друга.

        Считается по полным (не сжатым) размерам: иначе Qt сначала сжимает кнопки, и они наползают
        друг на друга. Для каждого выдвижного ряда место считается так, будто он открыт целиком, —
        поэтому ни анимация, ни выезд кнопок кадров на паузе ничего не сдвигают за край. Меняются только
        те группы, которым это нужно, — без «показать всё, потом спрятать лишнее» (от этого кнопки мигали)."""
        margins = self.layout().contentsMargins()
        room = self.width() - margins.left() - margins.right()
        spacing = self._buttons_row.spacing()  # 0: зазоры у выдвижных рядов внутри них самих
        folding = [w for group in self._optional_groups for w in group]
        # Ширина ряда, если бы все кнопки были видны и всё выдвижное — открыто.
        need = self._buttons_row.sizeHint().width()
        for w in folding + [self.volume_box]:
            current = 0 if w.isHidden() else w.sizeHint().width() + spacing
            need += w.full_width() + spacing - current
        widths = [sum(w.full_width() + spacing for w in group) for group in self._optional_groups]
        hide = 0
        while hide < len(widths) and need > room:
            need -= widths[hide]
            hide += 1
        for index, group in enumerate(self._optional_groups):
            for widget in group:
                widget.set_fit(index >= hide)

    def set_editing(self, editing: bool, keep_zoom: bool = False, morph: bool = False):
        """morph — шкала меняет толщину плавно (вместе с ростом панели при открытии / закрытии редактора)."""
        self.edit_bar.setVisible(editing)
        self.edit_button.setChecked(editing)
        if morph:
            self.timeline.begin_morph()
        else:
            self.timeline.set_edit_mode(editing, keep_zoom)

    def set_has_neighbors(self, has: bool):
        """Кнопки «пред. / след. видео» — только если в папке есть другие видео."""
        self.prev_box.set_open(has)
        self.next_box.set_open(has)

    def set_stop_visible(self, visible: bool):
        self.stop_box.set_open(visible)

    def set_seek_step(self, seconds: int):
        """Шаг кнопок «−N с / +N с» (настройка «Перемотка стрелками»): цифра на иконке и подсказка."""
        self.SEEK_STEP_MS = seconds * 1000
        self.back_button.set_icon("seek_back", seconds=seconds)
        self.forward_button.set_icon("seek_forward", seconds=seconds)
        self.back_button.setToolTip(tr("Назад на {n} с (←)", n=seconds))
        self.forward_button.setToolTip(tr("Вперёд на {n} с (→)", n=seconds))

    # --- Быстрое меню шестерёнки ------------------------------------------

    def _build_quick_menu(self):
        self.quick_menu = QMenu(self)
        self.speed_menu = self.quick_menu.addMenu(tr("Скорость"))
        self._speed_group = QActionGroup(self)
        self._speed_actions = {}
        for speed in SPEEDS:
            action = self.speed_menu.addAction(_speed_text(speed))
            action.setCheckable(True)
            action.triggered.connect(lambda checked, s=speed: self.set_rate(s))
            self._speed_group.addAction(action)
            self._speed_actions[speed] = action
        self.quick_menu.addSeparator()
        # Подпись клавиши — после табуляции: так она видна в меню, но не становится второй горячей клавишей.
        self.repeat_action = QAction(tr("Повтор") + "\tL", self, checkable=True)
        self.repeat_action.toggled.connect(self.repeatToggled)
        self.on_top_action = QAction(tr("Поверх всех окон"), self, checkable=True)
        self.on_top_action.toggled.connect(self.onTopToggled)
        # «Повтор» в меню не показывается (клавиша L и настройки); действие остаётся — L переключает его.
        self.quick_menu.addAction(self.on_top_action)
        self.quick_menu.addSeparator()
        self.set_rate(1.0)

    def _show_quick_menu(self):
        # Меню открывается над шестерёнкой: панель внизу окна.
        button = self.settings_button
        size = self.quick_menu.sizeHint()
        top_right = button.mapToGlobal(QPoint(button.width(), 0))
        self.quick_menu.popup(QPoint(top_right.x() - size.width(), top_right.y() - size.height() - 4))

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, rate: float):
        """Скорость воспроизведения (из меню шестерёнки): галочка в меню, цифра на шестерёнке, сигнал окну."""
        self._rate = rate
        self._speed_actions[rate].setChecked(True)
        self.speed_menu.setTitle(tr("Скорость: {rate}", rate=_speed_text(rate)))
        self.settings_button.set_badge(_speed_text(rate), highlight=rate != 1.0)
        self.rateChanged.emit(rate)

    def set_playing(self, playing: bool):
        self.play_button.set_playing(playing)
        self._playing = playing
        # Кнопки кадров — только на паузе и только при открытом видео (без видео «пауза» ничего не значит).
        self.frame_group.set_open(not playing and getattr(self, "_media_loaded", False))

    def play_button_playing(self) -> bool:
        return getattr(self, "_playing", False)

    def set_time(self, position: int, duration: int):
        self.timeline.set_duration(duration)
        self.timeline.set_position(position)
        # Пока курсор тянут, видео не успевает перематываться за мышью — показываем время под мышью.
        dragged = self.timeline.drag_time()
        self._duration = duration
        self._show_time(dragged if dragged is not None else position)

    def _show_time(self, ms: int):
        self.time_label.setText(f"{format_time(ms)} / {format_time(self._duration)}")

    def set_volume(self, value: int):
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(value)
        self.volume_slider.blockSignals(False)

    def set_muted(self, muted: bool):
        self.mute_button.set_icon("volume", muted=muted)

    def set_fullscreen(self, fullscreen: bool):
        self.fullscreen_button.set_icon("fullscreen", exit_mode=fullscreen)
        self.fullscreen_button.setToolTip(tr("Выйти из полноэкранного режима (F / Esc)") if fullscreen
                                          else tr("Во весь экран (F)"))

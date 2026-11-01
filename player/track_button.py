"""Кнопка «Звук: 2 из 3» на панели редактора: какие звуковые дорожки попадут в сохранённое видео
(макет `концепты/звуковые_дорожки.png`).

Видна, только если в видео больше одной звуковой дорожки (OBS пишет игру, микрофон, Discord отдельно).
Список открывается над кнопкой: галочка — дорожка сохраняется, наушники — слушать её в плеере сейчас.
Выбор не запоминается: у каждого открытого файла сначала отмечены все дорожки.
"""

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget, QWidgetAction)

from .i18n import tr
from .icons import part

AUDIO_LINES = ('<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/>'
               '<path d="M22 10v3"/>')  # Lucide audio-lines
HEADPHONES = ('<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1'
              'a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>')  # Lucide headphones
CHECK = '<path d="M20 6 9 17l-5-5"/>'
ROW_WIDTH = 340

_colors = {"accent": "#4f8cff", "accent_text": "#ffffff", "text": "#e8e9ee", "text_dim": "#9a9ca6"}


class _Check(QWidget):
    """Галочка: отмечено — квадрат цвета интерфейса с белой галочкой, нет — пустая рамка."""

    def __init__(self):
        super().__init__()
        self.on = True
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, 1, 16, 16)
        if self.on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(_colors["accent"]))
            p.drawRoundedRect(box, 4, 4)
            p.translate(2, 2)
            p.scale(14 / 24, 14 / 24)
            part(p, CHECK, QColor(_colors["accent_text"]))
        else:
            p.setPen(QPen(QColor(_colors["text_dim"]), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.end()


class _Listen(QAbstractButton):
    """Наушники: слушать эту дорожку в плеере. Звучащая сейчас — цветом интерфейса в кружке."""

    def __init__(self):
        super().__init__()
        self.active = False
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tr("Слушать эту дорожку в плеере"))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.active or self.underMouse():
            back = QColor(_colors["accent"] if self.active else _colors["text_dim"])
            back.setAlpha(45 if self.active else 30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(back)
            p.drawEllipse(QRectF(0, 0, 30, 30))
        p.translate(6, 6)
        p.scale(18 / 24, 18 / 24)
        part(p, HEADPHONES, QColor(_colors["accent"] if self.active else _colors["text_dim"]))
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class _TrackRow(QWidget):
    """Строка списка: галочка, «Дорожка 2 · Микрофон», сведения мелко, наушники справа."""

    toggled = Signal()

    def __init__(self, title: str, info: str):
        super().__init__()
        self.setObjectName("saveOption")  # тот же вид, что у пунктов меню сохранения
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(ROW_WIDTH)
        self.check = _Check()
        self.listen = _Listen()
        name = QLabel(title)
        name.setObjectName("saveOptionTitle")
        details = QLabel(info)
        details.setObjectName("saveOptionText")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        if info:
            text.addWidget(details)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 6, 7)
        layout.setSpacing(10)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)
        layout.addWidget(self.listen, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.toggled.emit()


class TrackButton(QPushButton):
    """selectionChanged() — поменялись галочки; listenRequested(номер дорожки с 0) — нажали наушники."""

    selectionChanged = Signal()
    listenRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(tr("Какие звуковые дорожки сохранить"))
        self.setIconSize(QSize(16, 16))
        self._tracks: list[dict] = []
        self._chosen: list[bool] = []
        self._rows: list[_TrackRow] = []
        self.menu = QMenu(self)
        self.menu.setObjectName("saveMenu")
        self.clicked.connect(self._show_menu)
        self.current_track = None  # функция: какая дорожка звучит сейчас (номер с 0 или None) — задаёт окно
        self.hide()

    # --- Дорожки ----------------------------------------------------------

    def set_tracks(self, tracks: list[dict]):
        """tracks — media_info.audio_tracks(): [{"title": …, "info": …}, …]. Все сразу отмечены."""
        self._tracks = tracks
        self._chosen = [True] * len(tracks)
        self._build_menu()
        self._update_text()
        self.setVisible(len(tracks) > 1)

    @property
    def selection(self) -> list[int] | None:
        """Номера (с 0) отмеченных дорожек; None — все (как раньше, без выбора)."""
        if all(self._chosen):
            return None
        return [i for i, on in enumerate(self._chosen) if on]

    def set_listening(self, index: int | None):
        for i, row in enumerate(self._rows):
            row.listen.active = i == index
            row.listen.update()

    def set_theme(self, theme: dict):
        _colors.update({k: theme[k] for k in _colors})
        icon = QPixmap(32, 32)
        icon.setDevicePixelRatio(2)
        icon.fill(Qt.GlobalColor.transparent)
        p = QPainter(icon)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(16 / 24, 16 / 24)
        part(p, AUDIO_LINES, QColor(theme["text"]))
        p.end()
        self.setIcon(QIcon(icon))
        for row in self._rows:
            row.check.update()
            row.listen.update()

    # --- Меню -------------------------------------------------------------

    def _build_menu(self):
        self.menu.clear()
        self._rows = []
        header = QLabel(tr("Звук в сохранённом видео").upper())
        header.setObjectName("tipsGroup")
        header.setContentsMargins(10, 6, 0, 4)
        self._add(header)
        for i, track in enumerate(self._tracks):
            row = _TrackRow(track["title"], track["info"])
            row.toggled.connect(lambda i=i: self._toggle(i))
            row.listen.clicked.connect(lambda _=False, i=i: self._listen(i))
            self._rows.append(row)
            self._add(row)
        hint = QLabel(tr("🎧 — послушать дорожку, пока смотрите видео"))
        hint.setObjectName("saveOptionText")
        hint.setContentsMargins(10, 6, 0, 4)
        self._add(hint)

    def _add(self, widget: QWidget):
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(widget)
        self.menu.addAction(action)

    def _toggle(self, index: int):
        self._chosen[index] = not self._chosen[index]
        self._rows[index].check.on = self._chosen[index]
        self._rows[index].check.update()
        self._update_text()
        self.selectionChanged.emit()

    def _listen(self, index: int):
        self.set_listening(index)
        self.listenRequested.emit(index)

    def _variants(self) -> list[str]:
        total = len(self._tracks)
        return [tr("Без звука")] + [tr("Звук: {n} из {total}", n=n, total=total) for n in range(1, total + 1)]

    def _update_text(self):
        chosen = sum(self._chosen)
        variants = self._variants()
        text = variants[chosen] if self._tracks else ""
        # Ширина — по самой длинной надписи: при смене галочек соседние кнопки не прыгают.
        self.ensurePolished()
        metrics = self.fontMetrics()
        self.setText("")
        empty = self.sizeHint().width()
        self.setMinimumWidth(empty + max((metrics.horizontalAdvance(v + "  ▾") for v in variants), default=0))
        self.setText(f"{text}  ▾")

    def _show_menu(self):
        if self.current_track is not None:
            self.set_listening(self.current_track())
        # Как меню сохранения: над кнопкой, правый край — по кнопке.
        self.menu.adjustSize()
        size = self.menu.sizeHint()
        top_left = self.mapToGlobal(QPoint(self.width() - size.width(), 0))
        top_left.setY(top_left.y() - size.height() - 4)
        self.menu.exec(top_left)

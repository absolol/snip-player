"""Панель «Сведения о видео» — выпадает под капсулой с именем файла по щелчку на неё.

Это всплывающее окно (Qt.Popup): закрывается щелчком мимо или клавишей Esc и само
перехватывает мышь, пока открыто. Появляется плавно, как остальные меню (smooth_popups.py).
"""

from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .child_processes import start_outside
from .i18n import tr
from .media_info import as_text

WIDTH = 360


def _button(text: str, name: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _line() -> QFrame:
    line = QFrame()
    line.setObjectName("infoLine")
    line.setFixedHeight(1)
    return line


class _ElidedLabel(QLabel):
    """Длинное значение (папка) сокращается многоточием посередине по настоящей ширине подписи (уже со
    шрифтом из стиля), полностью — в подсказке. Раньше считалось до стиля, и конец пути срезало без «…»."""

    def __init__(self, text: str):
        super().__init__(text)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width())
        if elided != self.text():
            self.setText(elided)
        self.setToolTip(self._full if elided != self._full else "")


class InfoPanel(QFrame):
    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("infoPanel")
        self.setProperty("smoothPopup", True)  # плавное появление (smooth_popups.py)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Щелчок по капсуле при открытой панели только закрывает её, а не открывает снова.
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setFixedWidth(WIDTH)
        self._background, self._border, self._radius = QColor("#1f2026"), QColor("#363842"), 8
        self._path, self._groups = "", None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        self.name_label = QLabel()
        self.name_label.setObjectName("infoName")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body)
        layout.addSpacing(2)
        layout.addWidget(_line())

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.copy_button = _button(tr("Копировать"), "editButton", tr("Скопировать сведения как текст"))
        self.copy_button.clicked.connect(self._copy)
        self.folder_button = _button(tr("Открыть папку"), "editButton", tr("Показать файл в Проводнике"))
        self.folder_button.clicked.connect(self._open_folder)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # --- Содержимое -------------------------------------------------------

    def set_colors(self, background: str, border: str, radius: int):
        # Фон рисуется вручную: у прозрачного окна Qt не рисует фон из стилей.
        self._background, self._border, self._radius = QColor(background), QColor(border), radius
        self.update()

    def set_info(self, path: str, groups):
        """groups — из media_info.collect(); None — сведения ещё собираются."""
        self._path, self._groups = path, groups
        self.name_label.setText(Path(path).name)
        self._clear_body()
        if groups is None:
            wait = QLabel(tr("Собираю сведения…"))
            wait.setObjectName("infoKey")
            self.body.addWidget(_line())
            self.body.addWidget(wait)
        else:
            for title, rows in groups:
                self._add_group(title, rows)
        self.copy_button.setEnabled(groups is not None)
        self.copy_button.setText(tr("Копировать"))
        if self.isVisible():
            self.adjustSize()

    def _clear_body(self):
        def clear(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    clear(item.layout())
        clear(self.body)

    def _add_group(self, title: str, rows):
        self.body.addWidget(_line())
        heading = QLabel(title.upper())
        heading.setObjectName("infoGroup")
        self.body.addWidget(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        grid.setColumnMinimumWidth(0, 116)
        grid.setColumnStretch(1, 1)
        for row, (key, value) in enumerate(rows):
            value_label = _ElidedLabel(value)
            value_label.setObjectName("infoValue")
            if key:
                key_label = QLabel(key)
                key_label.setObjectName("infoKey")
                grid.addWidget(key_label, row, 0)
                grid.addWidget(value_label, row, 1)
            else:
                value_label.setObjectName("infoKey")
                grid.addWidget(value_label, row, 0, 1, 2)
        self.body.addLayout(grid)

    # --- Кнопки -----------------------------------------------------------

    def _copy(self):
        if self._groups is None:
            return
        QGuiApplication.clipboard().setText(as_text(Path(self._path).name, self._groups))
        self.copy_button.setText(tr("Скопировано ✓"))
        QTimer.singleShot(1500, lambda: self.copy_button.setText(tr("Копировать")))

    def _open_folder(self):
        self.close()
        start_outside(["explorer", "/select,", str(Path(self._path))])

    # --- Показ ------------------------------------------------------------

    def show_under(self, anchor: QWidget):
        """Открыть под виджетом anchor, по его центру, не выходя за край экрана."""
        self.adjustSize()
        bottom = anchor.mapToGlobal(QPoint(anchor.width() // 2, anchor.height()))
        x, y = bottom.x() - self.width() // 2, bottom.y() + 6
        screen = (anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        self.move(x, y)
        self.show()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._background)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        p.end()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()

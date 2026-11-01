"""Окна-сообщения в стиле плеера (макет `концепты/окна_сообщений.png`) вместо системных QMessageBox.

Окно без рамки Windows: фон и скруглённые углы как у окна настроек, круглый крестик, значок в кружке
(галочка / вопрос — цветом интерфейса, ошибка — красным), заголовок, текст, по желанию — пояснение
в карточке, кнопки справа (главная — цветом интерфейса). Тянуть — за любое место, кроме кнопок.
Esc и крестик — как «Отмена» (для вопроса — «нет»), Enter — главная кнопка.

    info(parent, заголовок, текст)              — сообщение
    error(parent, заголовок, текст)             — ошибка
    ask(parent, заголовок, текст, да, нет)      — вопрос: True / False
    saved(parent, путь, пояснение)              — «Видео сохранено»: True — нажали «Показать в папке»
"""

from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import plural, tr
from .icons import part
from .themes import DEFAULT_THEME, build_custom_theme, build_stylesheet, load_themes
from .title_bar import _window_button
from .window_chrome import HTCAPTION, WindowChrome

_ICONS = {  # Lucide: круг-галочка, круг-вопрос, круг-восклицание
    "ok": '<path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/>',
    "question": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "error": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/>'
             '<line x1="12" x2="12.01" y1="16" y2="16"/>',
}
WIDTH = 470
_MARGINS = (20, 14, 14, 18)  # поля окна: слева, сверху, справа, снизу

_theme: dict | None = None  # текущее оформление плеера (set_theme из MainWindow.apply_theme)


def set_theme(theme: dict):
    global _theme
    _theme = theme


def _current_theme() -> dict:
    if _theme is not None:
        return _theme
    base = load_themes()[DEFAULT_THEME]  # окно ошибки до появления главного окна (main.py)
    return build_custom_theme(base, base["accent"], base["accent"])


class _Badge(QWidget):
    """Значок в кружке-подложке с оттенком того же цвета."""

    def __init__(self, kind: str, color: str):
        super().__init__()
        self._kind, self._color = kind, QColor(color)
        self.setFixedSize(44, 44)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        back = QColor(self._color)
        back.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(back)
        p.drawEllipse(QRectF(0, 0, 44, 44))
        p.translate(10, 10)
        part(p, _ICONS[self._kind], self._color)
        p.end()


class _Header(QObject):
    """Для WindowChrome: «заголовок» — всё окно, кроме кнопок; кнопки «Развернуть» нет."""

    maximizeClicked = Signal()

    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._dialog = dialog
        self.max_button = object()

    def isVisible(self) -> bool:
        return True

    def is_drag_area(self, widget) -> bool:
        return widget is not None and not isinstance(widget, QPushButton)

    def set_max_hover(self, hover: bool):
        pass

    def set_max_pressed(self, pressed: bool):
        pass


class _DialogChrome(WindowChrome):
    """Как у главного окна (тень, скруглённые углы Windows 11), но размер не меняется: края — не зоны размера."""

    def hit_test(self, pos) -> int:
        child = self.window.childAt(pos)
        if child is None or self.title_bar.is_drag_area(child):
            return HTCAPTION
        return 0


class PlayerDialog(QDialog):
    def __init__(self, parent, kind: str, title: str, lines: list[tuple[str, str]], buttons: list[tuple[str, str, object]],
                 note: str | None = None, default=None, cancel=None):
        """lines — (стиль: "dlgText" / "dlgFile" / "dlgDim", текст); buttons — (надпись, стиль, результат)."""
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("playerDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(title)
        self.setModal(True)
        self.result_value = cancel
        self._cancel = cancel
        theme = _current_theme()
        if parent is None:
            self.setStyleSheet(build_stylesheet(theme))  # без главного окна стиль не наследуется
        self.setFixedWidth(WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_MARGINS)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addStretch(1)
        close = _window_button("close", tr("Закрыть (Esc)"), "titleButton")
        close.clicked.connect(self.reject)
        top.addWidget(close)
        layout.addLayout(top)

        head = QHBoxLayout()
        head.setSpacing(14)
        color = theme.get("danger", "#e5484d") if kind == "error" else theme["accent"]
        head.addWidget(_Badge(kind, color), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(4)
        # Точная ширина переносимых строк — иначе Qt ошибается с их высотой и окно выходит выше нужного.
        text_width = WIDTH - _MARGINS[0] - _MARGINS[2] - 44 - 14
        heading = QLabel(title)
        heading.setObjectName("dlgTitle")
        heading.setWordWrap(True)
        heading.setFixedWidth(text_width)
        text.addWidget(heading)
        for style, line in lines:
            label = QLabel(line)
            label.setObjectName(style)
            label.setWordWrap(True)
            label.setFixedWidth(text_width)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(label)
        text.addStretch(1)  # строки — сразу под заголовком (иначе Qt раздвигал их по высоте колонки)
        head.addLayout(text, 1)
        layout.addLayout(head)

        if note:
            box = QFrame()
            box.setObjectName("dlgNote")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 10)
            label = QLabel(note)
            label.setObjectName("dlgDim")
            label.setWordWrap(True)
            label.setFixedWidth(WIDTH - _MARGINS[0] - _MARGINS[2] - 24)
            box_layout.addWidget(label)
            layout.addWidget(box)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 6, 0)
        row.addStretch(1)
        self.buttons: dict[object, QPushButton] = {}
        for caption, style, value in buttons:
            button = QPushButton(caption)
            button.setObjectName(style)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, v=value: self._finish(v))
            row.addWidget(button)
            self.buttons[value] = button
        layout.addLayout(row)
        if default in self.buttons:
            self.buttons[default].setDefault(True)
            self.buttons[default].setFocus()

        self.ensurePolished()
        for label in self.findChildren(QLabel):
            label.ensurePolished()  # шрифт из стиля — до расчёта высоты
            if label.wordWrap():
                label.setFixedHeight(label.heightForWidth(label.width()))
        self.adjustSize()
        self.chrome = _DialogChrome(self, _Header(self))
        self.chrome.install()
        self.chrome.disable_maximize()
        self.chrome.set_border_color(theme["border"])

    def _finish(self, value):
        self.result_value = value
        self.accept()

    def reject(self):
        self.result_value = self._cancel
        super().reject()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and getattr(self, "chrome", None) is not None:
            handled, result = self.chrome.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def run(self):
        """Показать по центру окна-владельца, дождаться ответа."""
        owner = self.parentWidget()
        if owner is not None and owner.isVisible():
            center = owner.window().frameGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        self.exec()
        return self.result_value


def info(parent, title: str, text: str = "", note: str | None = None, kind: str = "info"):
    lines = [("dlgText", text)] if text else []
    PlayerDialog(parent, kind, title, lines, [(tr("Понятно"), "dlgPrimary", True)], note, default=True).run()


def error(parent, title: str, text: str = "", note: str | None = None):
    lines = [("dlgText", text)] if text else []
    PlayerDialog(parent, "error", title, lines, [(tr("Понятно"), "dlgSecondary", True)], note, default=True).run()


def ask(parent, title: str, text: str, yes: str, no: str | None = None, danger: bool = False) -> bool:
    """Вопрос. По умолчанию (Enter) — «нет»: так случайно ничего не потерять."""
    no = tr("Отмена") if no is None else no
    buttons = [(no, "dlgSecondary", False), (yes, "dlgDanger" if danger else "dlgPrimary", True)]
    return bool(PlayerDialog(parent, "question", title, [("dlgText", text)], buttons, default=False, cancel=False).run())


def saved_files(parent, paths: list[str], note: str = "") -> bool:
    """«Сохранено 3 файла» (куски отдельно): имена файлов, папка мельче. True — «Показать в папке»."""
    files = [Path(p) for p in paths]
    word = plural(len(files), ("файл", "файла", "файлов"), ("file", "files"))
    shown = files if len(files) <= 6 else files[:5]
    lines = [("dlgFile", f.name) for f in shown]
    if len(shown) < len(files):
        lines.append(("dlgDim", tr("… и ещё {n}", n=len(files) - len(shown))))
    lines.append(("dlgDim", str(files[0].parent)))
    buttons = [(tr("Показать в папке"), "dlgSecondary", "folder"), (tr("Готово"), "dlgPrimary", None)]
    title = tr("Сохранено {n} {word}", n=len(files), word=word)
    return PlayerDialog(parent, "ok", title, lines, buttons, note or None, default=None).run() == "folder"


def saved(parent, path: str, note: str = "", title: str | None = None) -> bool:
    """«Видео сохранено»: имя файла крупно, папка мельче, пояснение — в карточке. True — «Показать в папке»."""
    title = tr("Видео сохранено") if title is None else title
    file = Path(path)
    lines = [("dlgFile", file.name), ("dlgDim", str(file.parent))]
    buttons = [(tr("Показать в папке"), "dlgSecondary", "folder"), (tr("Готово"), "dlgPrimary", None)]
    return PlayerDialog(parent, "ok", title, lines, buttons, note or None, default=None).run() == "folder"

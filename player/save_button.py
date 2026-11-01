"""Кнопка сохранения со стрелкой: основная часть сохраняет выбранным способом,
стрелка открывает меню «Сохранить как копию» / «Сохранить с удалением» / «Сохранить куски отдельно»
с пояснениями (макет `концепты/куски_отдельно.png`)."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget, QWidgetAction

from .i18n import plural, tr

SAVE_MODES = {
    "copy": (
        tr("Сохранить как копию"),
        tr("Обрезанное видео сохраняется в новый файл — вы выберете имя и папку. "
           "Исходное видео остаётся без изменений."),
    ),
    "replace": (
        tr("Сохранить с удалением"),
        tr("Исходный файл заменяется обрезанной версией под тем же именем. "
           "Старое видео отправляется в корзину Windows — при необходимости его можно оттуда восстановить."),
    ),
    "pieces": (
        tr("Сохранить куски отдельно"),
        tr("Каждый выделенный кусок — в свой файл, в папку, которую вы выберете. Ничего не выделено — "
           "все оставленные куски."),
    ),
}


_CHECK_WIDTH = 18  # колонка под галочку выбранного способа


class _ModeOption(QWidget):
    """Пункт меню: название и пояснение под ним."""

    clicked = Signal()

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("saveOption")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(330)

        # Галочка выбранного способа — в своей колонке: заголовки и пояснения обоих пунктов стоят ровно
        # (раньше «✓» стоял в тексте заголовка и сдвигал его вправо).
        self.check = QLabel()
        self.check.setObjectName("saveOptionTitle")
        self.check.setFixedWidth(_CHECK_WIDTH)
        self.title = QLabel(title)
        self.title.setObjectName("saveOptionTitle")
        self.text = text = QLabel(description)
        text.setObjectName("saveOptionText")
        text.setWordWrap(True)
        # Точная ширина — иначе Qt ошибается с высотой переносимого текста.
        text.setFixedWidth(self.width() - 24 - _CHECK_WIDTH)
        text.setFixedHeight(text.heightForWidth(text.width()))

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)
        title_row.addWidget(self.check)
        title_row.addWidget(self.title, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 9)
        layout.setSpacing(3)
        layout.addLayout(title_row)
        text_row = QHBoxLayout()
        text_row.setContentsMargins(_CHECK_WIDTH, 0, 0, 0)
        text_row.addWidget(text)
        layout.addLayout(text_row)

    def set_description(self, description: str):
        self.text.setText(description)
        self.text.ensurePolished()
        self.text.setFixedHeight(self.text.heightForWidth(self.text.width()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


class SaveButton(QWidget):
    saveRequested = Signal(str)  # "copy", "replace" или "pieces"
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "copy"

        self.main = QPushButton()
        self.main.setObjectName("saveMain")
        self.arrow = QPushButton("▾")
        self.arrow.setObjectName("saveArrow")
        self.arrow.setToolTip(tr("Выбрать способ сохранения"))
        for button in (self.main, self.arrow):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.main.clicked.connect(lambda: self.saveRequested.emit(self._mode))
        self.arrow.clicked.connect(self._show_menu)

        self.menu = QMenu(self)
        self.menu.setObjectName("saveMenu")
        self._options = {}
        for mode, (title, description) in SAVE_MODES.items():
            option = _ModeOption(title, description)
            option.clicked.connect(lambda m=mode: self._choose(m))
            action = QWidgetAction(self.menu)
            action.setDefaultWidget(option)
            self.menu.addAction(action)
            self._options[mode] = option

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self.main)
        layout.addWidget(self.arrow)
        self.set_mode("copy")

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str):
        self._mode = mode
        title, description = SAVE_MODES[mode]
        self.main.setText(title)
        self.main.setToolTip(f"{description}\n\nCtrl+S")
        for key, option in self._options.items():
            option.check.setText("✓" if key == mode else "")
        self.modeChanged.emit(mode)

    def set_pieces_count(self, count: int):
        """Сколько файлов получится у «Сохранить куски отдельно» — в пояснении пункта меню."""
        word = plural(count, ("файл", "файла", "файлов"), ("file", "files"))
        self._options["pieces"].set_description(
            SAVE_MODES["pieces"][1] + " " + tr("Сейчас: {n} {word}.", n=count, word=word))

    def _choose(self, mode: str):
        """Выбор в меню сразу сохраняет и запоминает способ для основной кнопки."""
        self.menu.close()
        self.set_mode(mode)
        self.saveRequested.emit(mode)

    def _show_menu(self):
        # Меню открывается над кнопкой: панель редактора внизу окна.
        self.menu.adjustSize()
        top_left = self.mapToGlobal(QPoint(self.width() - self.menu.sizeHint().width(), 0))
        top_left.setY(top_left.y() - self.menu.sizeHint().height() - 4)
        self.menu.exec(top_left)

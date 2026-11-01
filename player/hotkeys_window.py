"""Окно «Горячие клавиши» (макет `концепты/горячие_клавиши.png`).

В стиле окна настроек: свой заголовок-капсула, карточки по группам, клавиши «кнопками» (как подсказки
редактора, `edit_bar._keys`). Шаги перемотки и громкости, скорость ускорения — из настроек, поэтому
содержимое собирается заново при каждом открытии (`refresh`).
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .edit_bar import _keys
from .i18n import num, plural, tr
from .paths import APP_NAME
from .settings_window import _Header
from .window_chrome import WindowChrome


def _seconds(n) -> str:
    word = plural(int(n), ("секунду", "секунды", "секунд"), ("second", "seconds"))
    return tr("на {n} {word}", n=num(n), word=word)


def _rate(value: float) -> str:
    return num(value) + "×"


def _groups(prefs) -> tuple[list, list]:
    hold, hold_max = _rate(prefs.get("hold_rate")), _rate(prefs.get("hold_rate_max"))
    left = [
        (tr("Воспроизведение"), [
            (tr("Пробел"), tr("пауза / воспроизведение")), (tr("Зажать пробел"), tr("ускорение {rate}", rate=hold)),
            (tr("ЛКМ по видео"), tr("пауза / воспроизведение")),
            (tr("Зажать ЛКМ"), tr("ускорение, тянуть ← → — 1×…{rate}", rate=hold_max)),
            ("F", tr("во весь экран (и двойной щелчок)")), ("Esc", tr("выйти из полноэкранного")),
        ]),
        (tr("Перемотка"), [
            ("← / →", _seconds(prefs.get("seek_step"))), ("Shift + ← / →", _seconds(prefs.get("seek_small_step"))),
            (", / .", tr("кадр назад / вперёд")), ("PgUp / PgDn", tr("предыдущее / следующее видео")),
        ]),
        (tr("Звук и прочее"), [
            ("↑ / ↓", tr("громкость (шаг {n} %)", n=prefs.get("volume_step"))), ("M", tr("без звука")),
            ("P", tr("скриншот кадра")), ("L", tr("повтор вкл / выкл")), ("Ctrl + O", tr("открыть файл")),
            ("Ctrl + ,", tr("настройки")), ("Ctrl + Q", tr("выход")),
        ]),
    ]
    right = [
        (tr("Редактор"), [
            ("C", tr("открыть / закрыть редактор")), ("S", tr("разрезать здесь")),
            (tr("ЛКМ по куску"), tr("выделить кусок")), (tr("Ctrl + ЛКМ"), tr("выделить несколько")),
            ("Ctrl + X", tr("удалить / вернуть")), (tr("Тянуть маркер"), tr("подвинуть разрез")),
            (tr("ПКМ по маркеру"), tr("убрать разрез")), (tr("Колесо"), tr("масштаб шкалы")),
            (tr("Shift + колесо"), tr("прокрутить шкалу")), ("Ctrl + Z / Ctrl + Y", tr("отменить / вернуть")),
            ("Ctrl + S", tr("сохранить")),
        ]),
    ]
    return left, right


def _group_card(name: str, rows: list[tuple[str, str]]) -> QFrame:
    card = QFrame()
    card.setObjectName("settingsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    title = QLabel(name.upper())
    title.setObjectName("tipsGroup")
    layout.addWidget(title)
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(7)
    for row, (keys, text) in enumerate(rows):
        grid.addWidget(_keys(keys), row, 0)
        label = QLabel(text)
        label.setObjectName("tipText")
        grid.addWidget(label, row, 1)
    grid.setColumnStretch(1, 1)
    layout.addLayout(grid)
    return card


class HotkeysWindow(QWidget):
    WIDTH = 900

    def __init__(self, owner, prefs):
        super().__init__(owner, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("settingsWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(f"{tr('Горячие клавиши')} — {APP_NAME}")
        self.prefs = prefs
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 14)
        layout.setSpacing(10)
        self.header = _Header(self)
        self.header.title.setText(tr("Горячие клавиши"))
        self.header.close_button.clicked.connect(self.close)
        layout.addWidget(self.header)
        self._body = QWidget()
        self._body.setObjectName("settingsRow")
        layout.addWidget(self._body)
        hint = QLabel(tr("Шаги перемотки и громкости, скорость ускорения — в Настройки → «Воспроизведение»"))
        hint.setObjectName("settingsRowHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.chrome = WindowChrome(self, self.header)
        self.chrome.install()
        self.chrome.disable_maximize()
        self.refresh()

    def refresh(self):
        """Собрать карточки заново — с текущими шагами и скоростями из настроек."""
        old = self._body.layout()
        if old is not None:
            QWidget().setLayout(old)  # старую раскладку со всеми карточками — в отдельный виджет, он удалится
        columns = QHBoxLayout(self._body)
        columns.setContentsMargins(6, 4, 6, 0)
        columns.setSpacing(12)
        for groups in _groups(self.prefs):
            column = QVBoxLayout()
            column.setSpacing(12)
            for name, rows in groups:
                column.addWidget(_group_card(name, rows))
            column.addStretch(1)
            columns.addLayout(column, 1)
        self.setFixedWidth(self.WIDTH)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

    def set_theme(self, theme: dict, icon):
        self.header.icon.setPixmap(icon.pixmap(20, 20))
        self.chrome.set_border_color(theme["border"])

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and getattr(self, "chrome", None) is not None:
            handled, result = self.chrome.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def event(self, event):
        # Как в окне настроек: пока это окно активно, клавиши — его (Esc закрывает, пробел не трогает видео).
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

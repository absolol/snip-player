"""Пробел: короткое нажатие — пауза / воспроизведение, удержание — ускорение 2×.

Обычное сочетание клавиш так не умеет (оно срабатывает сразу при нажатии и не знает,
сколько клавишу держат), поэтому нажатия пробела ловятся фильтром событий приложения.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

HOLD_DELAY_MS = 250  # держат дольше — это удержание, а не нажатие


class SpaceKey(QObject):
    tapped = Signal()        # короткое нажатие
    holdStarted = Signal()   # держат дольше HOLD_DELAY_MS
    holdEnded = Signal()

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._down = False
        self._holding = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HOLD_DELAY_MS)
        self._timer.timeout.connect(self._on_hold)
        QApplication.instance().installEventFilter(self)

    def _ours(self, obj) -> bool:
        """Нажатие в окне плеера (или в его панели во весь экран), а не в диалоге или открытом меню."""
        if QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None:
            return False
        window = QApplication.activeWindow()
        return window is not None and (window is self._window or window.parentWidget() is self._window)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) or event.key() != Qt.Key.Key_Space:
            return False
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False  # Shift+пробел и т. п. — не наше
        if not (self._down or self._ours(obj)):
            return False
        if event.isAutoRepeat():
            return True  # пока держат, Windows повторяет нажатие — эти повторы не нужны
        if kind == QEvent.Type.KeyPress:
            if not self._down:
                self._down = True
                self._holding = False
                self._timer.start()
            return True
        # Отпустили. Событие отпускания приходит тому виджету, где сейчас фокус, —
        # поэтому смотрим на своё состояние, а не на то, кому оно пришло.
        if self._down:
            self._down = False
            self._timer.stop()
            if self._holding:
                self._holding = False
                self.holdEnded.emit()
            else:
                self.tapped.emit()
            return True
        return False

    def _on_hold(self):
        if self._down:
            self._holding = True
            self.holdStarted.emit()

    def cancel_hold(self):
        """Удержание не получилось (например, видео на паузе) — отпускание станет обычным нажатием."""
        self._holding = False

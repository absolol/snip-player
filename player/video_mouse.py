"""Отслеживание левой кнопки мыши над видео.

mpv рисует видео в собственном окне и забирает себе события мыши, поэтому Qt
не узнаёт о нажатиях над видео. Здесь состояние кнопки опрашивается напрямую у Windows.
"""

import ctypes
import time

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

_user32 = ctypes.windll.user32
_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02
_SM_SWAPBUTTON = 23


def _left_button_down() -> bool:
    # GetAsyncKeyState смотрит на физические кнопки, поэтому учитываем,
    # что левша мог поменять кнопки местами в настройках Windows.
    vk = _VK_RBUTTON if _user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class VideoMouseTracker(QObject):
    holdStarted = Signal()      # кнопку держат над видео дольше HOLD_DELAY_MS
    holdMoved = Signal(int)     # смещение курсора по X от точки нажатия, в пикселях
    holdEnded = Signal()
    clicked = Signal()          # короткий щелчок (не удержание)
    doubleClicked = Signal()

    HOLD_DELAY_MS = 250  # короче — это обычный щелчок, а не удержание
    DOUBLE_CLICK_MS = 400
    # Не чаще 30 мс: пока есть окно mpv, постоянно работающий таймер быстрее ~20 мс сбивал ВСЕ анимации Qt
    # до ~32 кадров/с (кадры через 31 мс). 30 мс хватает: щелчок длится 60–120 мс — поймаем 2–4 раза.
    POLL_MS = 30

    def __init__(self, video_widget, window):
        super().__init__(window)
        self._video = video_widget
        self._window = window

        self._down = False
        self._tracking = False  # нажатие началось над видео
        self._holding = False
        self._press_pos = QPoint()
        self._press_time = 0.0
        self._last_click_time = None

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _is_over_video(self, pos: QPoint) -> bool:
        if not (self._video.isVisible() and self._window.isActiveWindow()):
            return False
        if QApplication.activePopupWidget() is not None:  # открыто меню
            return False
        # Поверх видео может лежать другое окно плеера (панель во весь экран, подсказки) —
        # щелчок по нему не щелчок по видео.
        under = QApplication.widgetAt(pos)
        if under is not None and under.window() is not self._window:
            return False
        return self._video.rect().contains(self._video.mapFromGlobal(pos))

    def _poll(self):
        down = _left_button_down()
        now = time.monotonic() * 1000

        if down and not self._down:
            self._down = True
            self._press_pos = QCursor.pos()
            self._press_time = now
            self._tracking = self._is_over_video(self._press_pos)

        elif down and self._tracking:
            if not self._holding and now - self._press_time >= self.HOLD_DELAY_MS:
                self._holding = True
                self.holdStarted.emit()
            if self._holding:
                self.holdMoved.emit(QCursor.pos().x() - self._press_pos.x())

        elif not down and self._down:
            self._down = False
            if self._holding:
                self._holding = False
                self.holdEnded.emit()
            elif self._tracking:
                # Каждый щелчок срабатывает сразу (без ожидания второго), как на YouTube:
                # при двойном щелчке два переключения паузы отменяют друг друга.
                self.clicked.emit()
                if self._last_click_time is not None and now - self._last_click_time <= self.DOUBLE_CLICK_MS:
                    self._last_click_time = None
                    self.doubleClicked.emit()
                else:
                    self._last_click_time = now
            self._tracking = False


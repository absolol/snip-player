"""Окно без системного заголовка, но с родным поведением Windows.

Qt создаёт окно без рамки (FramelessWindowHint), а здесь ему возвращаются системные
стили рамки. Windows тогда сама делает: перетаскивание за заголовок, изменение размера
за края, привязку к краям экрана (Aero Snap), Win+стрелки, анимации сворачивания,
тень и скруглённые углы Windows 11, а при наведении на «Развернуть» — меню раскладок.
Сообщения WM_NCCALCSIZE / WM_NCHITTEST перехватываются, чтобы системный заголовок
не рисовался, а наш заголовок вёл себя как настоящий.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QColor, QCursor

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi

_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_SETCURSOR = 0x0020
WM_SYSCOMMAND = 0x0112
_SC_SIZE, _SC_MOVE, _SC_MAXIMIZE, _SC_RESTORE = 0xF000, 0xF010, 0xF030, 0xF120

WM_MOUSEMOVE = 0x0200
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCMOUSELEAVE = 0x02A2

HTCAPTION = 2
HTMAXBUTTON = 9
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
_RESIZE_ZONES = {HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT}
_SYSTEM_ZONES = _RESIZE_ZONES | {HTCAPTION}

_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_SYSMENU = 0x00080000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED

_SM_CXSIZEFRAME, _SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 32, 33, 92
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_DONOTROUND, _DWMWCP_ROUND = 1, 2
_DWMWA_COLOR_NONE = 0xFFFFFFFE

_TME_LEAVE, _TME_NONCLIENT = 0x02, 0x10


class _MARGINS(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


class WindowChrome:
    RESIZE_BORDER = 5  # ширина «хватательной» полосы по краям, в логических пикселях

    def __init__(self, window, title_bar):
        self.window = window
        self.title_bar = title_bar
        self.hwnd = None

    def install(self):
        """Вызывать после создания окна (когда у него уже есть winId)."""
        self.hwnd = int(self.window.winId())
        style = _user32.GetWindowLongPtrW(self.hwnd, _GWL_STYLE)
        style |= _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
        _user32.SetWindowLongPtrW(self.hwnd, _GWL_STYLE, style)
        # Полоска рамки в 1 пиксель внутрь окна — по ней Windows рисует тень.
        _dwmapi.DwmExtendFrameIntoClientArea(self.hwnd, ctypes.byref(_MARGINS(0, 0, 1, 0)))
        self._set_corners(_DWMWCP_ROUND)
        _user32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)

    def disable_maximize(self):
        """Окно без «Развернуть» (окно настроек): двойной щелчок по заголовку его не разворачивает."""
        style = _user32.GetWindowLongPtrW(self.hwnd, _GWL_STYLE) & ~_WS_MAXIMIZEBOX
        _user32.SetWindowLongPtrW(self.hwnd, _GWL_STYLE, style)
        _user32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)

    def set_topmost(self, topmost: bool):
        """«Поверх всех окон». Через WinAPI, а не флагом Qt: флаг пересоздаёт окно Windows,
        и mpv потерял бы окно, в которое рисует видео."""
        if self.hwnd:
            after = ctypes.c_void_p(-1 if topmost else -2)  # HWND_TOPMOST / HWND_NOTOPMOST
            _user32.SetWindowPos(self.hwnd, after, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # NOSIZE|NOMOVE|NOACTIVATE

    def set_border_color(self, color: str):
        """Цвет тонкой рамки окна (Windows 11)."""
        self._border_color = color
        if not self.hwnd:
            return
        c = QColor(color)
        self._set_border(c.red() | (c.green() << 8) | (c.blue() << 16))

    def set_fullscreen(self, fullscreen: bool):
        """Во весь экран рамка и скруглённые углы не нужны — иначе по краям экрана видны тонкие линии."""
        if not self.hwnd:
            return
        if fullscreen:
            self._set_border(_DWMWA_COLOR_NONE)
            self._set_corners(_DWMWCP_DONOTROUND)
        else:
            self._set_corners(_DWMWCP_ROUND)
            self.set_border_color(getattr(self, "_border_color", "#363842"))

    def _set_border(self, colorref: int):
        value = ctypes.c_uint(colorref)
        _dwmapi.DwmSetWindowAttribute(self.hwnd, _DWMWA_BORDER_COLOR, ctypes.byref(value), 4)

    def _set_corners(self, preference: int):
        value = ctypes.c_int(preference)
        _dwmapi.DwmSetWindowAttribute(self.hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(value), 4)

    # --- Сообщения Windows ------------------------------------------------

    def handle(self, message) -> tuple[bool, int]:
        """Возвращает (обработано, результат) — как ожидает QWidget.nativeEvent."""
        msg = wintypes.MSG.from_address(int(message))
        if self.hwnd is None or msg.hWnd != self.hwnd:
            return False, 0
        kind = msg.message

        if kind == WM_NCCALCSIZE and msg.wParam:
            # Вся площадь окна — наша. Развёрнутое окно Windows выдвигает за края экрана
            # на толщину рамки, поэтому в этом случае отступаем внутрь.
            if _user32.IsZoomed(self.hwnd):
                params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
                dpi = _user32.GetDpiForWindow(self.hwnd)
                pad = _user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi)
                bx = _user32.GetSystemMetricsForDpi(_SM_CXSIZEFRAME, dpi) + pad
                by = _user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi) + pad
                rect = params.rgrc[0]
                rect.left += bx
                rect.right -= bx
                rect.top += by
                rect.bottom -= by
            return True, 0

        if kind == WM_NCHITTEST:
            code = self.hit_test(self.window.mapFromGlobal(QCursor.pos()))
            return (True, code) if code else (False, 0)

        # Qt у окна без рамки не пропускает к Windows нажатия в «системных» зонах и
        # команды перемещения / изменения размера. Отдаём их Windows напрямую.
        if kind in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK) and msg.wParam in _SYSTEM_ZONES:
            return True, self._default(msg)
        if kind == WM_SYSCOMMAND and (msg.wParam & 0xFFF0) in (_SC_SIZE, _SC_MOVE, _SC_MAXIMIZE, _SC_RESTORE):
            return True, self._default(msg)
        if kind == WM_SETCURSOR and (msg.lParam & 0xFFFF) in _RESIZE_ZONES:
            return True, self._default(msg)  # стрелки изменения размера у краёв

        # Кнопку «Развернуть» Windows считает своей (ради меню раскладок),
        # поэтому подсветку и нажатие для неё делаем сами.
        if kind == WM_NCMOUSEMOVE:
            over_max = msg.wParam == HTMAXBUTTON
            self.title_bar.set_max_hover(over_max)
            if over_max:
                track = _TRACKMOUSEEVENT(ctypes.sizeof(_TRACKMOUSEEVENT), _TME_LEAVE | _TME_NONCLIENT, self.hwnd, 0)
                _user32.TrackMouseEvent(ctypes.byref(track))
        elif kind in (WM_NCMOUSELEAVE, WM_MOUSEMOVE):
            self.title_bar.set_max_hover(False)
            self.title_bar.set_max_pressed(False)
        elif kind in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK) and msg.wParam == HTMAXBUTTON:
            self.title_bar.set_max_pressed(True)
            return True, 0
        elif kind == WM_NCLBUTTONUP and msg.wParam == HTMAXBUTTON:
            self.title_bar.set_max_pressed(False)
            self.title_bar.maximizeClicked.emit()
            return True, 0
        return False, 0

    def _default(self, msg) -> int:
        return _user32.DefWindowProcW(msg.hWnd, msg.message, msg.wParam, msg.lParam)

    def hit_test(self, pos) -> int:
        """Что под точкой pos (координаты окна): край, заголовок, кнопка или 0 — обычная область."""
        w = self.window
        if w.isFullScreen():
            return 0
        if not w.isMaximized():
            b = self.RESIZE_BORDER
            left, right = pos.x() < b, pos.x() >= w.width() - b
            top, bottom = pos.y() < b, pos.y() >= w.height() - b
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM
        if not self.title_bar.isVisible():
            return 0
        child = w.childAt(pos)
        if child is self.title_bar.max_button:
            return HTMAXBUTTON
        if self.title_bar.is_drag_area(child):
            return HTCAPTION
        return 0

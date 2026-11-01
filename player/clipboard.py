"""Картинка в буфер обмена Windows — «лёгкая» запись.

QClipboard.setImage кладёт кадр сразу в трёх видах (две несжатые копии по 32 бита + PNG):
1920×1080 — около 18 МБ. Журнал буфера Windows (Win+V) ограничен по объёму, и такая запись
вытесняла из него почти все прежние (проверено: из 17 записей оставалось 5). Здесь — как у «Ножниц»:
одна несжатая картинка 24 бита (CF_DIB; остальные виды Windows досчитает сама) и PNG. Вытесняется
всего 2–3 старые записи — меньше никак: большие картинки журнал всё равно считает по объёму.
"""

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
_kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
_kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
_user32.OpenClipboard.argtypes = (wintypes.HWND,)
_user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.RegisterClipboardFormatW.argtypes = (wintypes.LPCWSTR,)
_user32.RegisterClipboardFormatW.restype = wintypes.UINT

_CF_DIB = 8
_GMEM_MOVEABLE = 0x0002
_BMP_FILE_HEADER = 14  # BMP-файл без этого заголовка — это и есть CF_DIB


def _encoded(image: QImage, fmt: str) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, fmt)
    buffer.close()
    return bytes(data)


def _put(fmt: int, data: bytes) -> bool:
    handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    pointer = _kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    _kernel32.GlobalUnlock(handle)
    if not _user32.SetClipboardData(fmt, handle):
        _kernel32.GlobalFree(handle)  # буфер не взял — память наша
        return False
    return True


def copy_image(image: QImage) -> bool:
    """True — картинка в буфере обмена."""
    image = image.convertToFormat(QImage.Format.Format_RGB888)  # кадр видео без прозрачности — 24 бита
    dib = _encoded(image, "BMP")[_BMP_FILE_HEADER:]
    png = _encoded(image, "PNG")
    for _ in range(10):  # буфер может быть на миг занят другой программой
        if _user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        _user32.EmptyClipboard()
        ok = _put(_CF_DIB, dib)
        _put(_user32.RegisterClipboardFormatW("PNG"), png)
        return ok
    finally:
        _user32.CloseClipboard()

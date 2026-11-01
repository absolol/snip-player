"""Иконка программы, нарисованная кодом в цветах текущей темы.

Скруглённый квадрат с градиентом акцентного цвета и белый треугольник «Play»,
разрезанный наискосок — плеер с обрезкой.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap, QTransform

_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _draw(size: int, accent: QColor, accent2: QColor, mark: QColor) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    s = float(size)
    gradient = QLinearGradient(0, 0, s, s)
    gradient.setColorAt(0.0, accent2)
    gradient.setColorAt(1.0, accent)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)

    # Треугольник «Play», чуть смещённый вправо — так он выглядит по центру.
    triangle = QPainterPath()
    triangle.moveTo(QPointF(s * 0.36, s * 0.24))
    triangle.lineTo(QPointF(s * 0.78, s * 0.50))
    triangle.lineTo(QPointF(s * 0.36, s * 0.76))
    triangle.closeSubpath()

    # Наискосок — тонкий разрез через треугольник.
    cut = QPainterPath()
    cut.addRect(QRectF(-s, -s * 0.035, 3 * s, s * 0.07))
    cut = QTransform().translate(s * 0.55, s * 0.52).rotate(-58).map(cut)
    if size >= 20:  # на самых мелких размерах разрез не виден, оставляем целый треугольник
        triangle = triangle.subtracted(cut)

    p.setBrush(mark)
    p.drawPath(triangle)
    p.end()
    return pixmap


def make_app_icon(accent: str, accent_hover: str, mark: str = "#ffffff") -> QIcon:
    icon = QIcon()
    a, a2, m = QColor(accent), QColor(accent_hover), QColor(mark)
    for size in _SIZES:
        icon.addPixmap(_draw(size, a, a2, m))
    return icon


def save_ico(path, accent: str, accent_hover: str, mark: str = "#ffffff"):
    """Файл .ico со всеми размерами (для Проводника: иконка видеофайлов и «Открыть с помощью»).
    Каждый размер — PNG внутри ICO (так умеют все Windows начиная с Vista)."""
    import struct

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    a, a2, m = QColor(accent), QColor(accent_hover), QColor(mark)
    images = []
    for size in _SIZES:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        _draw(size, a, a2, m).save(buffer, "PNG")
        buffer.close()
        images.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 в заголовке ICO означает 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    with open(path, "wb") as f:
        f.write(header + entries + blobs)

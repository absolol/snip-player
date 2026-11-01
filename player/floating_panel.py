"""Панель управления поверх видео в полноэкранном режиме.

Если прятать панель, уменьшая её высоту, на каждом кадре меняется и размер области видео:
mpv заново подгоняет картинку, и видео с чёрными полями дёргаются. Поэтому во весь экран
панель живёт в отдельном окне без рамки поверх видео (видео всегда занимает весь экран),
а прячется сдвигом этого окна вниз — такое движение Windows рисует идеально плавно.

Так же сверху живёт капсула с именем файла (edge="top"): окно по её размеру, по центру экрана,
прозрачное вокруг неё, прячется сдвигом вверх.
"""

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt
from PySide6.QtWidgets import QLayout, QVBoxLayout, QWidget

SLIDE_MS = 220


class FloatingPanel(QWidget):
    TOP_MARGIN = 12  # отступ капсулы сверху от края экрана

    def __init__(self, owner: QWidget, edge: str = "bottom"):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("floatingPanel")
        self._edge = edge
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self)
        if edge == "top":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            layout.setContentsMargins(0, self.TOP_MARGIN, 0, 0)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Размер окна задаёт place() сам. Без этого Qt держал минимальную высоту по старому содержимому:
        # после закрытия редактора окно оставалось высоким, и низ панели уходил за край экрана.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        self._screen = QRect()
        self._shown = False
        self._animation = QPropertyAnimation(self, b"pos", self)
        self._animation.setDuration(SLIDE_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_finished)

    @property
    def shown(self) -> bool:
        return self._shown

    def attach(self, content: QWidget, screen: QRect):
        """Забирает панель управления и показывает её внизу экрана screen."""
        self.layout().addWidget(content)
        content.show()
        self._screen = QRect(screen)
        self._shown = True
        self.place()
        self.show()
        self.raise_()

    def detach(self, content: QWidget):
        self._animation.stop()
        self.layout().removeWidget(content)
        self._shown = False
        self.hide()

    def _width(self) -> int:
        return self._screen.width() if self._edge == "bottom" else self.sizeHint().width()

    def _position(self, shown: bool) -> QPoint:
        height = self.sizeHint().height()
        if self._edge == "top":
            x = self._screen.left() + (self._screen.width() - self._width()) // 2
            return QPoint(x, self._screen.top() if shown else self._screen.top() - height)
        y = self._screen.bottom() + 1 - height if shown else self._screen.bottom() + 1
        return QPoint(self._screen.left(), y)

    def place(self):
        """Подогнать размер и место (например, после открытия редактора — панель стала выше)."""
        size = (self._width(), self.sizeHint().height())
        if self._animation.state() != QPropertyAnimation.State.Running:
            # Высота и место — одним вызовом: по отдельности (resize, потом move) окно на кадр вырастало
            # вниз за край экрана, а потом прыгало вверх (так дёргалась панель при открытии редактора).
            position = self._position(self._shown)
            self.setGeometry(position.x(), position.y(), *size)
        else:
            self.resize(*size)

    def slide(self, show: bool):
        if show == self._shown:
            return
        self._shown = show
        if show and not self.isVisible():
            self.move(self._position(False))
            self.show()
            self.raise_()
        self._animation.stop()
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(self._position(show))
        self._animation.start()

    def _on_finished(self):
        if not self._shown:
            self.hide()  # спрятанная панель не должна выглядывать на соседнем мониторе

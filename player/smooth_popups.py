"""Плавное появление выпадающих списков и меню.

Встроенная анимация Qt «раскатывает» список, сдвигая заранее снятую картинку крупными шагами,
и в первых кадрах показывает пустую рамку — выглядит как потеря кадров. Здесь она выключена,
а вместо неё любое меню и список появляются уже нарисованными: проявляются и чуть сдвигаются
к своему месту (короткая анимация через прозрачность окна — она идёт ровно, кадр за кадром).
"""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QWidget

DURATION_MS = 140
SLIDE_PX = 6


def _is_popup(widget: QWidget) -> bool:
    if isinstance(widget, QMenu) or widget.property("smoothPopup"):  # свои панели, например сведения о видео
        return True
    # Окошко со списком у QComboBox — внутренний класс Qt.
    return widget.metaObject().className() == "QComboBoxPrivateContainer"


class SmoothPopups(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        for effect in (Qt.UIEffect.UI_AnimateCombo, Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu):
            app.setEffectEnabled(effect, False)
        app.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and _is_popup(obj):
            self._animate(obj)
        return False

    def _animate(self, popup: QWidget):
        end = popup.pos()
        # Меню, открытое вверх (над кнопкой), выезжает снизу вверх; открытое вниз — сверху вниз.
        opened_up = popup.geometry().center().y() < QCursor.pos().y()
        start = end + QPoint(0, SLIDE_PX if opened_up else -SLIDE_PX)

        popup.setWindowOpacity(0.0)
        popup.move(start)

        group = QParallelAnimationGroup(popup)
        fade = QPropertyAnimation(popup, b"windowOpacity", group)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(popup, b"pos", group)
        slide.setStartValue(start)
        slide.setEndValue(end)
        for animation in (fade, slide):
            animation.setDuration(DURATION_MS)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(animation)
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

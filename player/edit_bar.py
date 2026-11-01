"""Панель редактора: появляется внутри нижней панели по кнопке с ножницами или клавише C."""

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .anim_button import restart
from .controls import icon_button
from .i18n import plural, tr
from .save_button import SaveButton
from .track_button import TrackButton

# Подсказки в кружке «i» (макет `концепты/подсказки_редактора.png`, вариант A): группы — в две колонки.
# Клавиши: « + » — нажать вместе, « / » — или.
TIPS = [
    [(tr("Разрезы"), [("S", tr("разрезать здесь")), (tr("Тянуть маркер"), tr("подвинуть разрез")),
                      (tr("ПКМ по маркеру"), tr("убрать разрез"))]),
     (tr("Куски"), [(tr("ЛКМ"), tr("выделить кусок")), (tr("Ctrl + ЛКМ"), tr("выделить несколько")),
                    ("Ctrl + X", tr("удалить / вернуть"))])],
    [(tr("Таймлайн"), [(tr("Колесо"), tr("увеличить / уменьшить")), (tr("Shift + колесо"), tr("прокрутить")),
                       (", / .", tr("кадр назад / вперёд"))]),
     (tr("Правка"), [("Ctrl + Z / Ctrl + Y", tr("отменить / вернуть")), ("Ctrl + S", tr("сохранить"))])],
]
TIPS_SHOW_MS, TIPS_HIDE_MS = 180, 120
TIPS_RISE = 6  # на столько пикселей окно поднимается, проявляясь


def _text_button(text: str, tooltip: str, name: str = "editButton") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    # Кнопки не сжимаются: если места мало, обрезается надпись справа, а не текст на кнопках.
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return button


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("editSeparator")
    line.setFixedSize(1, 22)
    return line


def _removed_text(count: int) -> str:
    if not count:
        return ""
    word = plural(count, ("кусок", "куска", "кусков"), ("segment", "segments"))
    return tr("Удаляется {n} {word}", n=count, word=word)


def _delete_text(restore: bool, several: bool) -> str:
    """Надпись кнопки «Удалить кусок» / «Вернуть кусок» (и «куски», если их несколько)."""
    if restore:
        return tr("⭯  Вернуть куски") if several else tr("⭯  Вернуть кусок")
    return tr("🗑  Удалить куски") if several else tr("🗑  Удалить кусок")


def _keys(text: str) -> QWidget:
    """Клавиши «кнопками»: «Ctrl + X» → [Ctrl] + [X], «Z / Y» → [Z] / [Y]."""
    box = QWidget()
    box.setObjectName("tipKeys")
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    for i, variant in enumerate(text.split(" / ")):
        if i:
            layout.addWidget(_tip_label("/", "tipSep"))
        for j, key in enumerate(variant.split(" + ")):
            if j:
                layout.addWidget(_tip_label("+", "tipSep"))
            layout.addWidget(_tip_label(key, "tipKeyCap"))
    layout.addStretch(1)
    return box


def _tip_label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class TipsPopup(QFrame):
    """Подсказки над кружком «i»: карточка цвета темы с тенью и «хвостиком» к кружку. Отдельное окно
    без рамки — чтобы ложиться поверх видео. Появляется плавно: проявляется и чуть поднимается."""

    SHADOW = 22   # поля окна под тень
    TAIL = 8      # высота «хвостика»
    TAIL_X = 40   # «хвостик» — на столько пикселей от левого края карточки
    RADIUS = 14

    def __init__(self, parent):
        # WindowTransparentForInput: прозрачные поля окна под тень лежат на кружке «i»; без этого мышь
        # оказывалась «над подсказками», кружок получал «мышь ушла», окно пряталось и снова появлялось — мигало.
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setObjectName("tipsPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._background, self._border = QColor("#1f2026"), QColor("#363842")
        self._shadow = None  # (размер, картинка) — тень пересчитывается только при смене размера

        layout = QVBoxLayout(self)
        m = self.SHADOW
        layout.setContentsMargins(m + 18, m + 14, m + 18, m + self.TAIL + 16)
        layout.setSpacing(10)
        layout.addWidget(_tip_label(tr("Как резать видео"), "tipsTitle"))
        columns = QHBoxLayout()
        columns.setSpacing(26)
        for column in TIPS:
            grid = QGridLayout()  # одна сетка на колонку — описания всех групп начинаются ровно
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(6)
            row = 0
            for index, (group, tips) in enumerate(column):
                if index:
                    grid.setRowMinimumHeight(row, 6)
                    row += 1
                grid.addWidget(_tip_label(group.upper(), "tipsGroup"), row, 0, 1, 2)
                row += 1
                for key, text in tips:
                    grid.addWidget(_keys(key), row, 0)
                    grid.addWidget(_tip_label(text, "tipText"), row, 1)
                    row += 1
            grid.setRowStretch(row, 1)
            columns.addLayout(grid)
        layout.addLayout(columns)

        self._hiding = False
        self._tail_x = self.TAIL_X  # где «хвостик» (от левого края карточки) — над центром кружка
        self._target = QPoint()
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_progress)
        self._animation.finished.connect(self._on_finished)
        self.hide()

    def set_colors(self, background: str, border: str):
        # Фон рисуется вручную: у прозрачного окна Qt не рисует фон из стилей.
        self._background, self._border = QColor(background), QColor(border)
        self.update()

    def _card(self) -> QRectF:
        m = self.SHADOW
        return QRectF(self.rect()).adjusted(m, m, -m, -m - self.TAIL)

    def _shadow_image(self) -> QImage:
        if self._shadow is None or self._shadow[0] != self.size():
            image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            p = QPainter(image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(self._card().translated(0, 6), self.RADIUS, self.RADIUS)
            p.end()
            self._shadow = (self.size(), _blurred(image, 22))
        return self._shadow[1]

    def paintEvent(self, event):
        card = self._card()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawImage(0, 0, self._shadow_image())
        shape = QPainterPath()
        shape.addRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        tail = QPainterPath()
        x = card.left() + self._tail_x
        tail.moveTo(x - 7, card.bottom() - 1)
        tail.lineTo(x, card.bottom() + self.TAIL - 1)
        tail.lineTo(x + 7, card.bottom() - 1)
        tail.closeSubpath()
        shape = shape.united(tail)  # «хвостик» — одна фигура с карточкой, рамка обходит и его
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._background)
        p.drawPath(shape)
        p.end()

    def show_above(self, anchor: QWidget):
        """Показать над anchor: «хвостик» указывает на его центр."""
        self.adjustSize()
        center = anchor.mapToGlobal(QPoint(anchor.width() // 2, 0))
        # Карточка — в пределах окна плеера (и экрана): у правого края она сдвигается влево,
        # а «хвостик» остаётся над кружком. Раньше карточка вылезала за окно, а у края экрана — за экран.
        card_w = self.width() - 2 * self.SHADOW
        bounds = anchor.window().frameGeometry().intersected(anchor.screen().availableGeometry())
        left = center.x() - self.TAIL_X
        left = max(bounds.left() + 8, min(left, bounds.right() - 8 - card_w))
        self._tail_x = max(20, min(center.x() - left, card_w - 20))
        x = left - self.SHADOW
        y = center.y() - self.height() + self.SHADOW - 4
        self._target = QPoint(x, y)
        start = 0.0 if not self.isVisible() else self._progress_now()
        self._hiding = False
        self.move(x, y + round(TIPS_RISE * (1 - start)))
        self.setWindowOpacity(start)
        self.show()
        self.raise_()
        restart(self._animation, start, 1.0, round(TIPS_SHOW_MS * (1 - start)) or 1)

    def hide_animated(self):
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        start = self._progress_now()
        restart(self._animation, start, 0.0, round(TIPS_HIDE_MS * start) or 1)

    def _progress_now(self) -> float:
        return float(self.windowOpacity())

    def _on_progress(self, value):
        value = float(value)
        self.setWindowOpacity(value)
        if not self._hiding:  # проявляясь — поднимается на место; гаснет — на месте
            self.move(self._target.x(), self._target.y() + round(TIPS_RISE * (1 - value)))

    def _on_finished(self):
        if self._hiding:
            self._hiding = False
            self.hide()


def _blurred(image: QImage, radius: float) -> QImage:
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(0)
    painter = QPainter(result)
    scene.render(painter, QRectF(result.rect()), QRectF(image.rect()))
    painter.end()
    return result


class InfoButton(QPushButton):
    """Кружок «i»: при наведении показывает подсказки."""

    def __init__(self, parent=None):
        super().__init__("i", parent)
        self.setObjectName("infoButton")
        self.setFixedSize(20, 20)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup = TipsPopup(self)

    def enterEvent(self, event):
        self.popup.show_above(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.popup.hide_animated()
        super().leaveEvent(event)


class EditBar(QWidget):
    splitClicked = Signal()
    deleteClicked = Signal()
    undoClicked = Signal()
    redoClicked = Signal()
    resetClicked = Signal()
    saveRequested = Signal(str)  # "copy", "replace" или "pieces"
    cancelExportClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editBar")

        self.split_button = _text_button(tr("✂  Разрезать"), tr("Разрезать видео в текущей позиции (S)"), "splitButton")
        self.delete_button = _text_button(_delete_text(False, False), tr("Удалить / вернуть выделенные куски (Ctrl+X)"))
        self.undo_button = icon_button("undo", tr("Отменить (Ctrl+Z)"))
        self.redo_button = icon_button("redo", tr("Вернуть (Ctrl+Y)"))
        self.reset_button = _text_button(tr("Сбросить"), tr("Убрать все разрезы и пометки"))
        self.info_button = InfoButton()

        self.info_label = QLabel()
        self.info_label.setObjectName("editInfo")
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.mode_box = QComboBox()
        self.mode_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode_box.addItem(tr("Без потерь"), True)
        self.mode_box.addItem(tr("Быстро"), False)
        self.mode_box.setToolTip(tr(
            "Без потерь — разрезы точно по кадру, качество и битрейт как в исходнике:\n"
            "видео и звук копируются без перекодирования, заново кодируются только\n"
            "несколько кадров у каждой границы разреза (с почти без потерь качеством).\n\n"
            "Быстро — всё копируется, почти мгновенно, но границы сдвигаются\n"
            "к ближайшим ключевым кадрам (до ~1–2 секунд)."
        ))
        self.tracks_button = TrackButton()  # звуковые дорожки — только если их больше одной
        self.save_button = SaveButton()
        self.save_button.saveRequested.connect(self.saveRequested)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("editInfo")
        self.cancel_button = _text_button(tr("Отмена"), tr("Остановить сохранение"))

        for button, signal in (
            (self.split_button, self.splitClicked),
            (self.delete_button, self.deleteClicked),
            (self.undo_button, self.undoClicked),
            (self.redo_button, self.redoClicked),
            (self.reset_button, self.resetClicked),
            (self.cancel_button, self.cancelExportClicked),
        ):
            button.clicked.connect(signal)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(self.split_button)
        layout.addWidget(self.delete_button)
        layout.addWidget(_separator())
        for widget in (self.undo_button, self.redo_button, self.reset_button):
            layout.addWidget(widget)
        layout.addSpacing(4)
        layout.addWidget(self.info_button)
        layout.addSpacing(6)
        layout.addWidget(self.info_label, 1)  # занимает всё свободное место по центру
        layout.addSpacing(6)
        for widget in (self.tracks_button, self.mode_box, self.save_button, self.progress_label, self.progress,
                       self.cancel_button):
            layout.addWidget(widget)

        self.set_exporting(False)

    def set_tips_colors(self, background: str, border: str):
        self.info_button.popup.set_colors(background, border)

    def set_delete_mode(self, restore: bool, several: bool = False):
        """Кнопка «Удалить кусок» над уже удалённым (выделенным или под курсором) — «Вернуть кусок»:
        Ctrl+X / кнопка в этом случае возвращает его."""
        text = _delete_text(restore, several)
        if self.delete_button.text() == text:
            return
        # Ширина — по самой длинной надписи: при смене текста соседние кнопки не прыгают.
        button = self.delete_button
        button.ensurePolished()
        metrics = button.fontMetrics()
        padding = button.sizeHint().width() - metrics.horizontalAdvance(button.text())
        variants = [_delete_text(r, s) for r in (False, True) for s in (False, True)]
        button.setMinimumWidth(padding + max(metrics.horizontalAdvance(v) for v in variants))
        button.setText(text)

    def update_state(self, *, can_split: bool, can_delete: bool, can_undo: bool, can_redo: bool,
                     has_changes: bool, can_save: bool, removed_count: int):
        self.split_button.setEnabled(can_split)
        self.delete_button.setEnabled(can_delete)
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)
        self.reset_button.setEnabled(has_changes)
        self.save_button.setEnabled(can_save)
        self.info_label.setText(_removed_text(removed_count))

    @property
    def lossless(self) -> bool:
        return bool(self.mode_box.currentData())

    def set_lossless(self, lossless: bool):
        self.mode_box.setCurrentIndex(self.mode_box.findData(lossless))

    def set_exporting(self, exporting: bool):
        for widget in (self.mode_box, self.save_button):
            widget.setVisible(not exporting)
        self.tracks_button.setVisible(not exporting and len(self.tracks_button._tracks) > 1)
        for widget in (self.progress, self.progress_label, self.cancel_button):
            widget.setVisible(exporting)
        if exporting:
            # Пока идёт сохранение, правки запрещены. После него окно снова
            # включает нужные кнопки через update_state().
            for widget in (self.split_button, self.delete_button, self.undo_button,
                           self.redo_button, self.reset_button):
                widget.setEnabled(False)
            self.set_progress(0.0)
            self.set_status(tr("Сохранение…"))

    def set_progress(self, fraction: float):
        self.progress.setValue(int(fraction * 1000))
        self.progress.setToolTip(f"{fraction * 100:.0f}%")

    def set_status(self, text: str):
        self.progress_label.setText(text)

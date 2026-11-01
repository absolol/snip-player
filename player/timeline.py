"""Таймлайн: скруглённая полоса с курсором воспроизведения.

В обычном просмотре — тонкая полоса (удаляемые куски видны штриховкой).
В редакторе — высокая полоса из кусков: маркеры разреза, длительности, выделение.
В редакторе таймлайн можно увеличивать колесом мыши (вокруг точки под курсором) и прокручивать
Shift + колесом; под лентой тогда видна полоса-обзор всего видео, её можно тянуть.
"""

import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from .i18n import tr
from .utils import format_time
from .waveform import BIN_MS

_VIEW_BAR, _EDIT_BAR = 17, 34          # высота полосы в просмотре и в редакторе
_VIEW_HEIGHT, _EDIT_HEIGHT = 34, 88    # высота виджета (с местом под маркеры, курсор и волну в редакторе)
_WAVE_GAP, _WAVE_H = 4, 26             # звуковая волна под лентой редактора (макет `концепты/звуковая_волна.png`, A)
_WAVE_STEP = 3                         # столбик волны — 2 px и 1 px промежуток
_MAX_LEAD_MS = 60                      # курсор не убегает вперёд последнего времени плеера дальше этого
_MARKER_GRAB = 7                       # насколько близко к маркеру нужно нажать, чтобы его тянуть
_PLAYHEAD_GRAB = 6                     # нажатие ближе этого к белому курсору «берёт» его, а не перематывает
_ZOOM_STEP = 1.25                      # во сколько раз меняется масштаб за один щелчок колеса
_MIN_VISIBLE_MS = 500                  # максимальное увеличение: на ленте не меньше полсекунды
_OVERVIEW_Y, _OVERVIEW_H = 82, 4       # полоса-обзор под волной (видна, когда таймлайн увеличен)

# Автопрокрутка: если тянуть курсор или маркер к краю увеличенной ленты (или дальше, хоть за окно),
# лента едет сама. Скорость — в «ширинах экрана» в секунду: у самого края медленно,
# чем дальше мышь за краем — тем быстрее.
_AUTOSCROLL_ZONE = 14        # пикселей у края, где прокрутка уже начинается
_AUTOSCROLL_MIN = 0.25
_AUTOSCROLL_PER_PX = 0.015
_AUTOSCROLL_MAX = 4.0
_AUTOSCROLL_TICK_MS = 30


class TimeBubble(QLabel):
    """Плашка со временем над таймлайном.

    Своя, а не системная подсказка Windows: та при каждом показе заново проигрывает
    анимацию появления, и при быстром перетаскивании видна пустая мигающая рамка.
    Отдельное окно без рамки — чтобы ложиться поверх видео."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setObjectName("timeBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._background, self._border = QColor("#2c2e36"), QColor("#363842")
        self.hide()

    def set_colors(self, background: QColor, border: QColor):
        self._background, self._border = QColor(background), QColor(border)
        self.update()

    def show_time(self, ms: int, anchor_global: QPoint):
        """anchor_global — точка, над которой встать (середина низа плашки)."""
        text = format_time(ms)
        if text != self.text():
            self.setText(text)
            self.adjustSize()
        self.move(anchor_global.x() - self.width() // 2, anchor_global.y() - self.height() - 6)
        if not self.isVisible():
            self.show()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._background)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        p.end()
        super().paintEvent(event)


class Timeline(QWidget):
    seekRequested = Signal(int)               # точная перемотка (щелчок отпущен)
    scrubRequested = Signal(int)              # быстрая перемотка, пока курсор тянут
    segmentClicked = Signal(int, bool)        # номер куска, с Ctrl ли
    markerMoved = Signal(int, int)            # номер маркера, новое время
    markerRemoveRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._duration = 0
        self._position = 0
        self._markers: list[int] = []
        self._removed: list[bool] = [False]
        self._selected: set[int] = set()
        self._edit_mode = False
        # Плавный переход тонкой полосы просмотра в ленту редактора: 0 — просмотр, 1 — редактор.
        # Ведёт его анимация панели (SlideHolder.grow_to → set_edit_progress) — один таймер на всё,
        # иначе кадры шкалы и панели не совпадали и панель дёргалась. Пока идёт закрытие, _edit_mode ещё
        # True (маркеры и куски видны до конца); в конце панель вызывает set_edit_mode(False).
        self._edit_t = 0.0

        self._seeking = False
        self._grab_dx = 0.0           # смещение мыши от курсора, когда курсор «взяли»
        self._moved = False           # курсор действительно перемещали (иначе перематывать не нужно)
        self._dragged_marker = None   # номер маркера, который тянут
        self._drag_ms = 0
        self._hovered = False

        # Видимая часть видео (в редакторе её можно увеличивать). None — всё видео.
        self._view_start = 0
        self._view_len = None
        self._panning = False   # тянут полосу-обзор
        self._bubble = TimeBubble(self)

        # Плавное движение курсора при воспроизведении: плеер сообщает время ~20 раз в секунду,
        # а между этими сообщениями таймлайн сам досчитывает положение и перерисовывается
        # с частотой экрана.
        self._playing = False
        self._rate = 1.0
        self._anchor_ms = 0.0
        self._anchor_t = time.monotonic()
        # Последнее время от плеера и когда оно пришло; последнее нарисованное место курсора.
        # Пока окно тащат, Windows притормаживает видео: время плеера на миг замирает, курсор по досчёту
        # убегал вперёд, а поправки тянули его назад — он ездил туда-сюда (запись 30.10 21-41).
        # Теперь он не уходит вперёд дальше _MAX_LEAD_MS и не едет назад от мелких поправок.
        self._real_ms = 0.0
        self._real_t = self._anchor_t
        self._last_shown = None
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self._on_frame)

        # Куда только что перемотали мышью. Плеер ещё несколько десятков миллисекунд сообщает
        # старое время, пока выполняет перемотку, — такие сообщения не принимаем, иначе курсор
        # на мгновение мелькнёт в старом месте.
        self._seek_target = None
        self._seek_target_t = 0.0
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(_AUTOSCROLL_TICK_MS)
        self._autoscroll.timeout.connect(self._autoscroll_tick)

        self._colors = {name: QColor("#888") for name in ("track", "fill", "handle", "cut", "text", "label_bg")}
        # Звуковая волна (waveform.py): пики по BIN_MS, None — ещё считается, b"" — звука нет.
        self._peaks: bytes | None = None
        self._peaks_top = 1
        self._wave_cache = None  # (ключ, {"dim" / "played" / "cut": картинка дорожки})
        self.set_edit_mode(False)

    # --- Данные -----------------------------------------------------------

    def set_colors(self, track: str, fill: str, handle: str, cut: str, text: str, label_bg: str):
        self._colors = {"track": QColor(track), "fill": QColor(fill), "handle": QColor(handle),
                        "cut": QColor(cut), "text": QColor(text), "label_bg": QColor(label_bg)}
        self._wave_cache = None
        self._bubble.set_colors(self._colors["label_bg"], self._colors["track"])
        self.update()

    def drag_time(self):
        """Время, которое показывать в счётчике, пока курсор тянут или плеер догоняет перемотку; иначе None."""
        if self._seeking or self._seek_target is not None:
            return int(self._shown_ms())
        return None

    def _show_bubble(self, x: float, ms: int):
        """Плашка времени над точкой x таймлайна (над верхом ленты)."""
        if not self._duration:
            return
        x = min(max(x, self._bar_rect().left()), self._bar_rect().right())
        self._bubble.show_time(ms, self.mapToGlobal(QPoint(int(x), int(self._bar_rect().top()) - 6)))

    def hideEvent(self, event):
        self._bubble.hide()
        super().hideEvent(event)

    def set_duration(self, ms: int):
        if ms != self._duration:
            self._duration = ms
            self.reset_zoom()
            self.update()

    def set_position(self, ms: int):
        if self._seeking:
            return
        now = time.monotonic()
        if self._seek_target is not None:
            target = self._seek_target
            arrived = target - 300 <= ms <= target + 400 * max(self._rate, 1.0)
            if not arrived and now - self._seek_target_t < 1.5:
                return  # плеер ещё сообщает время до перемотки
            self._seek_target = None
            # Плеер у цели: дальше курсор едет от настоящего времени видео. Если видео встало
            # чуть раньше точки щелчка (ближайший кадр), курсор назад не откатываем.
            start = float(ms) if (ms >= target or target - ms > 60) else float(target)
            self._anchor_ms, self._anchor_t = start, now
            self._real_ms, self._real_t, self._last_shown = start, now, None
            if ms != self._position:
                self._position = ms
                self._follow(int(start))
            self.update()
            return
        if self._playing:
            predicted = self._shown_ms()
            self._real_ms, self._real_t = float(ms), now
            if abs(ms - predicted) > 300 * max(self._rate, 1.0):
                self._anchor_ms = float(ms)  # перемотка или пропуск куска — сразу на новое место
                self._last_shown = None
            else:
                # Небольшое расхождение поправляем мягко, чтобы курсор не дёргался.
                self._anchor_ms = predicted + (ms - predicted) * 0.25
            self._anchor_t = now
        else:
            self._anchor_ms, self._anchor_t = float(ms), now
        if ms != self._position:
            self._position = ms
            self._follow(int(self._shown_ms()))
            self.update()

    def set_playback(self, playing: bool, rate: float):
        """Идёт ли воспроизведение и с какой скоростью — для плавного движения курсора."""
        if playing == self._playing and rate == self._rate:
            return
        self._anchor_ms, self._anchor_t = self._shown_ms(), time.monotonic()
        self._real_ms, self._real_t = self._anchor_ms, self._anchor_t
        self._last_shown = None
        self._playing, self._rate = playing, rate
        if playing:
            self._frame_timer.start()
        else:
            self._frame_timer.stop()
            self._anchor_ms = float(self._position)
            self.update()

    def _shown_ms(self) -> float:
        """Где сейчас рисовать курсор."""
        if self._seeking or not self._playing:
            return float(self._position)
        if self._seek_target is not None:
            # После перемотки мышью курсор ждёт в точке щелчка, пока плеер не начнёт играть
            # оттуда (это ~0,1 с), — иначе он убежал бы вперёд и потом откатился назад.
            return float(self._seek_target)
        now = time.monotonic()
        rate = self._rate
        shown = self._anchor_ms + (now - self._anchor_t) * 1000 * rate
        # Вперёд — не дальше последнего времени плеера (с учётом прошедшего с тех пор) + небольшой запас.
        shown = min(shown, self._real_ms + (now - self._real_t) * 1000 * rate + _MAX_LEAD_MS)
        # Назад — только при настоящей перемотке (большой скачок); мелкие поправки курсор пережидает на месте.
        last = self._last_shown
        if last is not None and last - 300 * max(rate, 1.0) < shown < last:
            shown = last
        shown = min(max(shown, 0.0), float(self._duration))
        self._last_shown = shown
        return shown

    def _on_frame(self):
        if self.isVisible() and self._duration:
            self._follow(int(self._shown_ms()))
            self.update()

    def set_waveform(self, peaks: bytes | None):
        """Пики громкости (waveform.py) для дорожки волны в редакторе; None — ещё считаются, b"" — звука нет."""
        self._peaks = peaks
        self._peaks_top = max(peaks) if peaks else 1
        self._wave_cache = None
        self.update()

    def set_segments(self, markers, removed_flags):
        self._markers, self._removed = list(markers), list(removed_flags)
        self.update()

    def set_selection(self, indices):
        self._selected = set(indices)
        self.update()

    def set_edit_mode(self, enabled: bool, keep_zoom: bool = False):
        """Сразу, без анимации (плавно — begin_morph + set_edit_progress)."""
        self._edit_mode = enabled
        self._edit_t = 1.0 if enabled else 0.0
        if not enabled and not keep_zoom:
            self.reset_zoom()  # в обычном просмотре всегда видно всё видео
        self.setFixedHeight(_EDIT_HEIGHT if enabled else _VIEW_HEIGHT)
        self.update()

    def begin_morph(self):
        """Начать плавный переход: лента редактора видна (маркеры, куски), толщину задаёт set_edit_progress."""
        self._edit_mode = True

    def set_edit_progress(self, t: float):
        """Толщина между просмотром (0) и редактором (1) — кадр анимации панели."""
        self._edit_t = t = min(max(t, 0.0), 1.0)
        self.setFixedHeight(round(_VIEW_HEIGHT + (_EDIT_HEIGHT - _VIEW_HEIGHT) * t))
        self.update()

    # --- Масштаб ----------------------------------------------------------

    def reset_zoom(self):
        self._view_start, self._view_len = 0, None
        self.update()

    @property
    def zoomed(self) -> bool:
        return self._view_len is not None and self._view_len < self._duration

    def _visible(self) -> tuple[float, float]:
        """Видимый промежуток (начало, длина) в миллисекундах."""
        if not self.zoomed:
            return 0.0, float(max(self._duration, 1))
        return float(self._view_start), float(self._view_len)

    def _set_view(self, start: float, length: float):
        length = min(max(length, min(_MIN_VISIBLE_MS, self._duration)), self._duration)
        if length >= self._duration:
            self.reset_zoom()
            return
        self._view_len = length
        self._view_start = min(max(start, 0.0), self._duration - length)
        self.update()

    def zoom_at(self, x: float, steps: float):
        """Увеличить (steps > 0) или уменьшить вокруг точки x, чтобы время под курсором осталось на месте."""
        if not self._duration:
            return
        start, length = self._visible()
        anchor = self._x_to_ms(x)
        ratio = (anchor - start) / length if length else 0.0
        new_length = length / (_ZOOM_STEP ** steps)
        self._set_view(anchor - ratio * new_length, new_length)

    def pan(self, fraction: float):
        """Прокрутка на долю видимой ширины (отрицательная — влево)."""
        if self.zoomed:
            start, length = self._visible()
            self._set_view(start + fraction * length, length)

    def _follow(self, ms: int):
        """Во время воспроизведения увеличенная лента сама едет за курсором."""
        if not self.zoomed or self._dragged_marker is not None or self._panning:
            return
        start, length = self._visible()
        if ms < start or ms > start + length:
            self._set_view(ms - 0.1 * length, length)

    # --- Геометрия --------------------------------------------------------

    _MARGIN = 8

    def _width(self) -> float:
        return max(self.width() - 2 * self._MARGIN, 1)

    def _x_to_ms(self, x: float) -> int:
        start, length = self._visible()
        ratio = (x - self._MARGIN) / self._width()
        return int(max(0.0, min(start + ratio * length, self._duration)))

    def _ms_to_x(self, ms: float) -> float:
        if not self._duration:
            return self._MARGIN
        start, length = self._visible()
        return self._MARGIN + (ms - start) / length * self._width()

    def _overview_x(self, ms: float) -> float:
        """Координата на полосе-обзоре (там всегда всё видео целиком)."""
        return self._MARGIN + (ms / self._duration if self._duration else 0.0) * self._width()

    def _bar_rect(self) -> QRectF:
        # Между просмотром и редактором (t от 0 до 1) — промежуточная полоса: так она плавно утолщается.
        t = self._edit_t
        view_top = (_VIEW_HEIGHT - _VIEW_BAR) / 2
        return QRectF(self._MARGIN, view_top + (14 - view_top) * t, self._width(), _VIEW_BAR + (_EDIT_BAR - _VIEW_BAR) * t)

    def _markers_now(self):
        """Маркеры с учётом того, который сейчас тянут."""
        markers = list(self._markers)
        if self._dragged_marker is not None:
            markers[self._dragged_marker] = self._drag_ms
        return markers

    def _marker_near(self, x: float):
        if not self._edit_mode or not self._duration:
            return None
        best = None
        for i, m in enumerate(self._markers):
            distance = abs(self._ms_to_x(m) - x)
            if distance <= _MARKER_GRAB and (best is None or distance < best[1]):
                best = (i, distance)
        return best[0] if best else None

    def _segment_index(self, ms: int) -> int:
        return sum(1 for m in self._markers_now() if m <= ms)

    # --- Рисование --------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._colors
        bar = self._bar_rect()
        shown = self._shown_ms()
        t = self._edit_t
        radius = 5 + t
        markers = self._markers_now()
        bounds = [0, *markers, self._duration]
        flags = list(self._removed)
        if not self._edit_mode:
            # В просмотре маркеров не видно: подряд идущие куски с одинаковым состоянием — одна полоса.
            merged_bounds, merged_flags = [0], []
            for i, flag in enumerate(flags[:len(bounds) - 1]):
                if merged_flags and merged_flags[-1] == flag:
                    merged_bounds[-1] = bounds[i + 1]
                else:
                    merged_flags.append(flag)
                    merged_bounds.append(bounds[i + 1])
            bounds, flags = merged_bounds, merged_flags
        edges = len(bounds) - 2

        if not self._duration:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["track"])
            p.drawRoundedRect(bar, radius, radius)
            return

        gap = 2 * t  # в редакторе куски разделены зазором у маркеров
        p.save()
        p.setClipRect(QRectF(bar.left() - 1, 0, bar.width() + 2, self.height()))
        for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
            x1 = self._ms_to_x(a) + (gap if i else 0)
            x2 = self._ms_to_x(b) - (gap if i < edges else 0)
            if x2 <= x1:
                continue
            rect = QRectF(x1, bar.top(), x2 - x1, bar.height())
            removed = i < len(flags) and flags[i]
            p.setPen(Qt.PenStyle.NoPen)
            if removed:
                fill = QColor(c["cut"])
                fill.setAlpha(60)
                p.setBrush(fill)
                p.drawRoundedRect(rect, radius, radius)
                p.setBrush(QBrush(c["cut"], Qt.BrushStyle.BDiagPattern))
                p.drawRoundedRect(rect, radius, radius)
            else:
                p.setBrush(c["track"])
                p.drawRoundedRect(rect, radius, radius)
                # просмотренная часть — тонкая полоска внизу куска
                if shown > a:
                    stripe = 3 + t
                    played = QRectF(x1, rect.bottom() - stripe, min(self._ms_to_x(shown), x2) - x1, stripe)
                    color = QColor(c["fill"])
                    color.setAlpha(200)
                    p.setBrush(color)
                    p.drawRoundedRect(played, stripe / 2, stripe / 2)
                if self._edit_mode and rect.width() > 40 and t > 0.5:
                    text_color = QColor(c["text"])
                    text_color.setAlphaF(min(1.0, (t - 0.5) * 2))  # подписи проявляются во второй половине
                    p.setPen(text_color)
                    p.setFont(QFont("Segoe UI", 8))
                    p.drawText(rect.adjusted(0, -3, 0, -3), Qt.AlignmentFlag.AlignCenter, format_time(b - a))
            if self._edit_mode and i in self._selected:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(c["fill"], 2))
                p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
        p.restore()

        if self._edit_mode:
            p.save()
            p.setOpacity(t)
            for i, m in enumerate(markers):
                mx = self._ms_to_x(m)
                if not bar.left() - 8 <= mx <= bar.right() + 8:
                    continue  # маркер за пределами увеличенной ленты
                width = 3 if i == self._dragged_marker else 2
                p.setPen(QPen(c["fill"], width))
                p.drawLine(QPointF(mx, 6), QPointF(mx, self._wave_rect(bar).bottom()))  # сквозь волну
                tri = QPainterPath()
                tri.moveTo(mx - 6, 0)
                tri.lineTo(mx + 6, 0)
                tri.lineTo(mx, 8)
                tri.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c["fill"])
                p.drawPath(tri)
            p.restore()

        if self._edit_mode:
            self._paint_wave(p, bar, shown, bounds, flags)
        if self._edit_mode and self.zoomed:
            self._paint_overview(p)

        # курсор воспроизведения
        px = self._ms_to_x(shown)
        if not bar.left() - 1 <= px <= bar.right() + 1:
            return  # курсор за пределами увеличенной ленты
        dot = 4 + t
        p.setPen(QPen(c["handle"], 2))
        p.drawLine(QPointF(px, bar.top() - 2), QPointF(px, bar.bottom() + 2))
        if self._edit_mode and self._edit_t > 0:
            wave = self._wave_rect(bar)
            p.setOpacity(self._edit_t)
            p.drawLine(QPointF(px, wave.top()), QPointF(px, wave.bottom()))
            p.setOpacity(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["handle"])
        p.drawEllipse(QPointF(px, bar.top() - dot + 2), dot, dot)

    def _wave_rect(self, bar: QRectF) -> QRectF:
        """Дорожка волны — под лентой; при открытии редактора въезжает вместе с ней."""
        return QRectF(bar.left(), bar.bottom() + _WAVE_GAP, bar.width(), _WAVE_H)

    def _wave_images(self, rect: QRectF) -> dict | None:
        """Столбики волны видимого участка — три картинки (обычные, проигранные, удаляемые). Пересчитываются
        только при смене участка, размера, цветов или данных — не на каждом кадре воспроизведения."""
        if not self._peaks:
            return None
        start, length = self._visible()
        ratio = self.devicePixelRatioF()
        key = (start, length, int(rect.width()), ratio)
        if self._wave_cache and self._wave_cache[0] == key:
            return self._wave_cache[1]
        peaks, top = self._peaks, self._peaks_top
        width, height = int(rect.width()), int(rect.height())
        mid = height / 2
        columns = []
        x = 1.0
        while x < width - 1:
            a = int((start + (x / width) * length) / BIN_MS)
            b = max(int((start + ((x + _WAVE_STEP) / width) * length) / BIN_MS), a + 1)
            chunk = peaks[a:b]
            if chunk:
                level = (max(chunk) / top) ** 0.7  # тихое — чуть крупнее, чтобы не сливалось с нулём
                columns.append((x, max(level * (mid - 2), 0.7)))
            x += _WAVE_STEP
        c = self._colors
        cut = QColor(c["cut"])
        cut.setAlpha(170)
        images = {}
        for name, color in (("dim", self._dim_color()),
                            ("played", c["fill"]), ("cut", cut)):
            image = QPixmap(round(width * ratio), round(height * ratio))
            image.setDevicePixelRatio(ratio)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            for cx, h in columns:
                painter.drawRoundedRect(QRectF(cx, mid - h, 2, 2 * h), 1, 1)
            painter.end()
            images[name] = image
        self._wave_cache = (key, images)
        return images

    def _dim_color(self) -> QColor:
        """Цвет непроигранной волны — между текстом и фоном ленты."""
        a, b = self._colors["text"], self._colors["track"]
        return QColor(round(a.red() * 0.55 + b.red() * 0.45), round(a.green() * 0.55 + b.green() * 0.45),
                      round(a.blue() * 0.55 + b.blue() * 0.45))

    def _paint_wave(self, p: QPainter, bar: QRectF, shown: float, bounds, flags):
        """Дорожка волны: проигранное — цветом интерфейса, удаляемые куски — красным с подложкой."""
        c = self._colors
        rect = self._wave_rect(bar)
        p.save()
        p.setOpacity(self._edit_t)
        back = QColor(c["track"])
        back.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(back)
        p.drawRoundedRect(rect, 6, 6)
        if self._peaks == b"":
            text = QColor(c["text"])
            text.setAlpha(110)
            p.setPen(text)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("Нет звука"))
        images = self._wave_images(rect)
        if images is None:
            p.restore()
            return
        removed = QPainterPath()
        for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
            if i < len(flags) and flags[i]:
                removed.addRect(QRectF(self._ms_to_x(a), rect.top(), self._ms_to_x(b) - self._ms_to_x(a), rect.height()))
        lane = QPainterPath()
        lane.addRoundedRect(rect, 6, 6)
        played = QPainterPath()
        played.addRect(QRectF(rect.left(), rect.top(), self._ms_to_x(shown) - rect.left(), rect.height()))
        p.setClipPath(lane.subtracted(removed).subtracted(played))
        p.drawPixmap(rect.topLeft(), images["dim"])
        p.setClipPath(lane.intersected(played).subtracted(removed))
        p.drawPixmap(rect.topLeft(), images["played"])
        if not removed.isEmpty():
            p.setClipPath(lane.intersected(removed))
            tint = QColor(c["cut"])
            tint.setAlpha(35)
            p.fillRect(rect, tint)
            p.drawPixmap(rect.topLeft(), images["cut"])
        p.restore()

    def _paint_overview(self, p: QPainter):
        """Тонкая полоса со всем видео: удаляемые части и рамка видимого сейчас участка."""
        c = self._colors
        track = QRectF(self._MARGIN, _OVERVIEW_Y, self._width(), _OVERVIEW_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["track"])
        p.drawRoundedRect(track, 2, 2)
        # Видимый участок — той же толщины, что и остальная полоса.
        start, length = self._visible()
        thumb = QRectF(self._overview_x(start), track.top(),
                       max(self._overview_x(start + length) - self._overview_x(start), 6), _OVERVIEW_H)
        p.setBrush(c["fill"])
        p.drawRoundedRect(thumb, 2, 2)
        # Удаляемые части — поверх: где видимый участок заходит на них, полоса красная.
        bounds = [0, *self._markers, self._duration]
        p.setBrush(c["cut"])
        for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
            if i < len(self._removed) and self._removed[i]:
                p.drawRect(QRectF(self._overview_x(a), track.top(), self._overview_x(b) - self._overview_x(a), _OVERVIEW_H))

    def _dragging(self) -> bool:
        return self._seeking or self._dragged_marker is not None

    def _clamp_to_bar(self, x: float) -> float:
        """На увеличенной ленте курсор и маркер при перетаскивании не уходят за её края —
        вместо этого едет сама лента (см. _autoscroll_tick)."""
        if not (self._edit_mode and self.zoomed):
            return x
        bar = self._bar_rect()
        return min(max(x, bar.left()), bar.right())

    def _autoscroll_tick(self):
        if not (self._edit_mode and self.zoomed and self._dragging()):
            return
        x = self.mapFromGlobal(QCursor.pos()).x()  # мышь может быть где угодно, даже за окном
        bar = self._bar_rect()
        if x < bar.left() + _AUTOSCROLL_ZONE:
            direction, distance = -1, bar.left() + _AUTOSCROLL_ZONE - x
        elif x > bar.right() - _AUTOSCROLL_ZONE:
            direction, distance = 1, x - (bar.right() - _AUTOSCROLL_ZONE)
        else:
            return
        speed = min(_AUTOSCROLL_MIN + distance * _AUTOSCROLL_PER_PX, _AUTOSCROLL_MAX)
        start, length = self._visible()
        self._set_view(start + direction * speed * length * _AUTOSCROLL_TICK_MS / 1000, length)
        edge_x = self._clamp_to_bar(x)
        if self._dragged_marker is not None:
            self._drag_ms = self._x_to_ms(edge_x)
            self._show_bubble(self._ms_to_x(self._drag_ms), self._drag_ms)
            self.update()
        else:
            self._seek_to(edge_x)

    def _on_overview(self, y: float) -> bool:
        return self._edit_mode and self.zoomed and y >= _OVERVIEW_Y - 3

    def _pan_overview_to(self, x: float):
        _, length = self._visible()
        center = (x - self._MARGIN) / self._width() * self._duration
        self._set_view(center - length / 2, length)

    def wheelEvent(self, event):
        if not self._edit_mode or not self._duration:
            event.ignore()
            return
        delta = event.angleDelta()
        horizontal = abs(delta.x()) > abs(delta.y())
        if horizontal or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            amount = (delta.x() if horizontal else delta.y()) / 120
            self.pan(-amount * 0.15)
        else:
            self.zoom_at(event.position().x(), delta.y() / 120)
        event.accept()

    # --- Мышь -------------------------------------------------------------

    def mousePressEvent(self, event):
        if not self._duration:
            return
        x = event.position().x()
        marker = self._marker_near(x)
        if event.button() == Qt.MouseButton.RightButton:
            if marker is not None:
                menu = QMenu(self)
                menu.addAction(tr("Убрать разрез"), lambda m=marker: self.markerRemoveRequested.emit(m))
                menu.exec(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._on_overview(event.position().y()):
            self._panning = True
            self._pan_overview_to(x)
            return
        if marker is not None:
            self._dragged_marker = marker
            self._drag_ms = self._markers[marker]
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._autoscroll.start()
            self._show_bubble(self._ms_to_x(self._drag_ms), self._drag_ms)
            self.update()
            return
        ms = self._x_to_ms(x)
        if self._edit_mode:
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.segmentClicked.emit(self._segment_index(ms), ctrl)
            if ctrl:
                return  # Ctrl+ЛКМ только выделяет, курсор не двигаем
        self._seeking = True
        self._autoscroll.start()
        playhead_x = self._ms_to_x(self._shown_ms())
        if abs(x - playhead_x) <= _PLAYHEAD_GRAB:
            # Нажали на сам курсор — «взяли» его, а не перемотали: без движения мыши кадр
            # не меняется (иначе пиксель под мышью округлился бы в соседний кадр), а при
            # перетаскивании курсор едет вслед за мышью без начального скачка.
            self._grab_dx = playhead_x - x
            self._moved = False
            self._show_bubble(playhead_x, int(self._shown_ms()))
        else:
            self._grab_dx = 0.0
            self._seek_to(x)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._panning:
            self._pan_overview_to(x)
            return
        if self._dragged_marker is not None:
            self._drag_ms = self._x_to_ms(self._clamp_to_bar(x))
            self.update()
        elif self._seeking:
            self._seek_to(self._clamp_to_bar(x + self._grab_dx))
        else:
            near = self._marker_near(x) is not None
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.PointingHandCursor)
        if self._dragged_marker is not None:
            self._show_bubble(self._ms_to_x(self._drag_ms), self._drag_ms)
        elif not self._seeking:  # при перетаскивании курсора плашку двигает _seek_to
            self._show_bubble(x, self._x_to_ms(x))

    def mouseReleaseEvent(self, event):
        self._panning = False
        self._autoscroll.stop()
        if self._dragged_marker is not None:
            index, ms = self._dragged_marker, self._drag_ms
            self._dragged_marker = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.markerMoved.emit(index, ms)
            self.update()
        if self._seeking:
            self._seeking = False
            # Перематывать ещё раз не нужно: перемотка при нажатии и перетаскивании уже точная
            # и выполняется последней. Повторная перемотка в ту же точку заново «отматывала»
            # видео, которое уже начало играть оттуда.
            self.update()
        if not self.rect().contains(event.position().toPoint()):
            self._bubble.hide()  # отпустили за пределами таймлайна

    def enterEvent(self, event):
        self._hovered = True

    def leaveEvent(self, event):
        self._hovered = False
        if not self._dragging():  # пока тянут, плашка остаётся, даже если мышь ушла
            self._bubble.hide()

    def _seek_to(self, x: float):
        self._moved = True
        self._position = self._x_to_ms(x)
        # Сразу новая точка отсчёта для плавного движения — не досчитывать от старого места.
        now = time.monotonic()
        self._anchor_ms, self._anchor_t = float(self._position), now
        self._real_ms, self._real_t, self._last_shown = float(self._position), now, None  # перемотка мышью — назад можно
        self._seek_target, self._seek_target_t = self._position, now
        self._show_bubble(self._ms_to_x(self._position), self._position)
        self.repaint()  # сразу, не дожидаясь следующего кадра — чтобы полоса не отставала от мыши
        self.scrubRequested.emit(self._position)

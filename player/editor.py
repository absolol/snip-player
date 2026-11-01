"""Модель обрезки: маркеры разреза делят видео на куски, каждый кусок можно пометить на удаление.

Ничего не знает ни об интерфейсе, ни о FFmpeg — только о времени в миллисекундах.
Состояние — это маркеры (точки разреза) и признак «удалить» для каждого куска между ними;
любое изменение можно отменить и вернуть.
"""

import bisect

MIN_PIECE_MS = 100  # куски короче этого не имеют смысла: маркеры ближе друг к другу не ставятся


class CutList:
    def __init__(self):
        self.reset()

    def reset(self):
        """Новый файл: всё с чистого листа, без истории."""
        self._markers: list[int] = []
        self._removed: list[bool] = [False]  # по одному признаку на кусок: кусков = маркеров + 1
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []

    # --- Состояние --------------------------------------------------------

    @property
    def markers(self) -> list[int]:
        return list(self._markers)

    @property
    def removed_flags(self) -> list[bool]:
        return list(self._removed)

    @property
    def has_cuts(self) -> bool:
        """Есть ли что удалять."""
        return any(self._removed)

    @property
    def has_changes(self) -> bool:
        return bool(self._markers) or self.has_cuts

    @property
    def removed_count(self) -> int:
        return sum(self._removed)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def segments(self, length: int) -> list[tuple[int, int, bool]]:
        """Куски видео: (начало, конец, удалить ли)."""
        bounds = [0, *self._markers, length]
        return [(a, b, flag) for a, b, flag in zip(bounds, bounds[1:], self._removed)]

    def segment_at(self, ms: int) -> int:
        """Номер куска, в который попадает момент ms."""
        return bisect.bisect_right(self._markers, ms)

    def removed_ranges(self, length: int) -> list[tuple[int, int]]:
        """Удаляемые промежутки (соседние удаляемые куски склеены)."""
        ranges = []
        for a, b, flag in self.segments(length):
            if not flag:
                continue
            if ranges and ranges[-1][1] == a:
                ranges[-1] = (ranges[-1][0], b)
            else:
                ranges.append((a, b))
        return ranges

    def range_at(self, ms: int, length: int):
        """Удаляемый промежуток, в который попадает ms, или None."""
        for start, end in self.removed_ranges(length):
            if start <= ms < end:
                return start, end
        return None

    def kept(self, length: int) -> list[tuple[int, int]]:
        """Оставшиеся куски видео (соседние склеены) — именно они попадут в сохранённый файл."""
        pieces = []
        for a, b, flag in self.segments(length):
            if flag or b - a < 1:
                continue
            if pieces and pieces[-1][1] == a:
                pieces[-1] = (pieces[-1][0], b)
            else:
                pieces.append((a, b))
        return pieces

    def kept_duration(self, length: int) -> int:
        return sum(end - start for start, end in self.kept(length))

    def map_to_result(self, ms: int, length: int) -> int:
        """Где в обрезанном видео окажется момент ms исходного (если он вырезан — начало следующего куска)."""
        result = 0
        for start, end in self.kept(length):
            if ms < start:
                return result
            if ms < end:
                return result + (ms - start)
            result += end - start
        return 0  # после последнего куска — начинаем сначала

    # --- Изменения --------------------------------------------------------

    def split(self, ms: int, length: int) -> bool:
        """Ставит маркер разреза в ms. Обе половины куска сохраняют его признак «удалить»."""
        ms = int(ms)
        if ms < MIN_PIECE_MS or ms > length - MIN_PIECE_MS:
            return False
        i = bisect.bisect_left(self._markers, ms)
        neighbours = self._markers[max(i - 1, 0):i + 1]
        if any(abs(ms - m) < MIN_PIECE_MS for m in neighbours):
            return False
        self._remember()
        self._markers.insert(i, ms)
        self._removed.insert(i, self._removed[i])
        return True

    def remove_marker(self, index: int) -> bool:
        """Убирает разрез: два соседних куска склеиваются. Удаляемым склеенный кусок
        остаётся, только если удаляемыми были оба."""
        if not 0 <= index < len(self._markers):
            return False
        self._remember()
        merged = self._removed[index] and self._removed[index + 1]
        del self._markers[index]
        self._removed[index:index + 2] = [merged]
        return True

    def move_marker(self, index: int, ms: int, length: int) -> bool:
        """Двигает маркер, не дальше соседних (с зазором MIN_PIECE_MS)."""
        if not 0 <= index < len(self._markers):
            return False
        low = (self._markers[index - 1] if index > 0 else 0) + MIN_PIECE_MS
        high = (self._markers[index + 1] if index + 1 < len(self._markers) else length) - MIN_PIECE_MS
        ms = int(min(max(ms, low), high))
        if ms == self._markers[index]:
            return False
        self._remember()
        self._markers[index] = ms
        return True

    def toggle(self, indices) -> bool:
        """Помечает куски на удаление; если все они уже помечены — возвращает их."""
        indices = [i for i in set(indices) if 0 <= i < len(self._removed)]
        if not indices:
            return False
        value = not all(self._removed[i] for i in indices)
        self._remember()
        for i in indices:
            self._removed[i] = value
        return True

    def clear(self) -> bool:
        """Убирает все разрезы и пометки (можно отменить)."""
        if not self.has_changes:
            return False
        self._remember()
        self._markers, self._removed = [], [False]
        return True

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._markers, self._removed = map(list, self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._markers, self._removed = map(list, self._redo.pop())
        return True

    def _snapshot(self):
        return tuple(self._markers), tuple(self._removed)

    def _remember(self):
        self._undo.append(self._snapshot())
        self._redo.clear()

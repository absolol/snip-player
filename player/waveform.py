"""Звуковая волна для редактора (макет `концепты/звуковая_волна.png`, вариант A — дорожка под шкалой).

FFmpeg в фоновом потоке отдаёт звук одной дорожки моно 8 кГц, по байту на отсчёт (u8); из каждых 16 отсчётов
(2 мс) берётся пик. Итог — bytes, один байт (0…255) на 2 мс: для часа видео 1,8 МБ. Готовые волны
запоминаются (несколько последних файлов и дорожек), повторное открытие редактора — мгновенно.
"""

import subprocess
import threading
from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, Signal

from .paths import tool

BIN_MS = 2
_RATE = 8000
_BIN = _RATE * BIN_MS // 1000          # отсчётов на один пик
_CHUNK = _BIN * 8192                   # читаем по ~16 с звука за раз
_ABS = bytes(min(abs(i - 128) * 2, 255) for i in range(256))  # u8 → громкость 0…255
_CACHE_SIZE = 6
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def compute_peaks(path: str, track: int, cancelled=lambda: False) -> bytes:
    """Пики громкости дорожки track (номер с 0). Нет звука / ошибка — b""."""
    ffmpeg = tool("ffmpeg")
    if not ffmpeg:
        return b""
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-nostdin", "-i", path, "-map", f"0:a:{track}", "-vn", "-sn",
                             "-dn", "-ac", "1", "-ar", str(_RATE), "-f", "u8", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    peaks = bytearray()
    rest = b""
    try:
        while True:
            if cancelled():
                proc.kill()
                return b""
            data = proc.stdout.read(_CHUNK)
            if not data:
                break
            data = (rest + data).translate(_ABS)
            whole = len(data) - len(data) % _BIN
            peaks += bytes(map(max, (data[i:i + _BIN] for i in range(0, whole, _BIN))))
            rest = data[whole:]
        if rest:
            peaks.append(max(rest))
    finally:
        proc.stdout.close()
        proc.wait()
    return bytes(peaks)


class WaveformLoader(QObject):
    """load(путь, дорожка) → сигнал ready(путь, дорожка); данные — get(путь, дорожка)."""

    ready = Signal(str, int)
    _done = Signal(str, int, bytes)  # из фонового потока — в главный (очередью)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._done.connect(self._store)
        self._cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        self._generation = 0
        self._lock = threading.Lock()

    def get(self, path: str, track: int) -> bytes | None:
        """Готовая волна (b"" — звука нет) или None — ещё не посчитана."""
        return self._cache.get((path, track))

    def load(self, path: str, track: int):
        if (path, track) in self._cache:
            QTimer.singleShot(0, lambda: self.ready.emit(path, track))
            return
        with self._lock:
            self._generation += 1
            generation = self._generation
        threading.Thread(target=self._work, args=(path, track, generation), daemon=True).start()

    def cancel(self):
        with self._lock:
            self._generation += 1

    def _work(self, path: str, track: int, generation: int):
        try:
            peaks = compute_peaks(path, track, lambda: self._generation != generation)
        except OSError:
            peaks = b""
        if self._generation != generation:
            return  # открыли другой файл или дорожку — этот результат уже не нужен
        self._done.emit(path, track, peaks)

    def _store(self, path: str, track: int, peaks: bytes):
        self._cache[(path, track)] = peaks
        self._cache.move_to_end((path, track))
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        self.ready.emit(path, track)

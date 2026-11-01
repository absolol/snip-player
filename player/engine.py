"""Обёртка над libmpv: остальной код работает только с этим классом, а не с API mpv напрямую.

mpv меняет скорость на лету без перезапуска звука, поэтому ускорение мышью идёт плавно.
Библиотека libmpv-2.dll лежит в папке lib/ проекта.
"""

import os
import threading

from .paths import LIB_DIR

os.environ["PATH"] = str(LIB_DIR) + os.pathsep + os.environ.get("PATH", "")

import mpv  # noqa: E402 — импорт после того, как папка с libmpv добавлена в PATH

_END_FILE_ERROR = 4  # mpv_end_file_reason: MPV_END_FILE_REASON_ERROR
_MPV_HRSEEK_SLACK_MS = 6  # mpv принимает кадр, начинающийся до ~5 мс раньше цели точной перемотки


class MpvEngine:
    def __init__(self):
        self._mpv = None
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._error = False
        self.path = None
        self._scrub_lock = threading.Lock()
        self._scrub_busy = False
        self._scrub_next = None
        # Последние значения свойств mpv. mpv присылает их сам (подписка), поэтому интерфейс
        # читает их мгновенно: прямой запрос к mpv ждёт, пока тот освободится от декодирования,
        # и при перетаскивании курсора это заметно тормозило.
        self._props = {}
        self._reset_props()

    # --- Файл -------------------------------------------------------------

    def attach(self, win_id: int):
        """Создаёт mpv, который рисует видео в окне win_id."""
        self._mpv = mpv.MPV(
            wid=str(win_id),
            keep_open="yes",            # в конце файла остаться на последнем кадре
            idle="yes",
            hwdec="auto-safe",          # аппаратное декодирование, где оно надёжно
            osd_level=0,                # без надписей mpv поверх видео
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,    # клавиатуру и мышь обрабатывает наше окно
            input_cursor=False,
            cursor_autohide="no",
            load_scripts=False,
            volume=self._volume,
            mute=self._muted,
        )

        @self._mpv.event_callback("end-file")
        def _on_end_file(event):
            if event.data.reason == _END_FILE_ERROR:
                self._error = True

        for name in self._props:
            self._mpv.observe_property(name, self._on_property)

    _WATCHED = ("time-pos", "duration", "pause", "eof-reached")

    def _reset_props(self):
        self._props = {"time-pos": None, "duration": None, "pause": False, "eof-reached": False,
                       "container-fps": None}

    def _on_property(self, name, value):
        # Вызывается из потока событий mpv; запись в словарь безопасна.
        self._props[name] = value

    def _set_pause(self, paused: bool):
        self._mpv.pause = paused
        self._props["pause"] = paused  # сразу, не дожидаясь подтверждения от mpv

    def open(self, path: str, start_ms: int = 0):
        self.path = path
        self._error = False
        self._reset_props()
        if start_ms > 0:
            self._mpv.loadfile(path, start=f"{start_ms / 1000:.3f}")
        else:
            self._mpv.loadfile(path)
        self._set_pause(False)

    def close_file(self):
        """Закрывает текущий файл (например, чтобы его можно было заменить или удалить)."""
        if self._mpv and self.has_media:
            self._mpv.command("stop")
        self.path = None
        self._reset_props()

    @property
    def has_media(self) -> bool:
        return self.path is not None

    # --- Состояние --------------------------------------------------------

    def is_playing(self) -> bool:
        return self.has_media and not self._error and not self._props["pause"] and not self.is_ended()

    def is_ended(self) -> bool:
        # Читаем напрямую: при перемотке в самый конец на паузе mpv не всегда присылает это
        # свойство по подписке. Спрашивают его редко (таймер окна, кнопки), не при перетаскивании.
        if not (self._mpv and self.has_media):
            return False
        try:
            return bool(self._mpv.eof_reached)
        except Exception:  # noqa: BLE001
            return bool(self._props["eof-reached"])

    def is_error(self) -> bool:
        return self._error

    def _has_track(self, kind: str) -> bool:
        tracks = (self._mpv.track_list or []) if self.has_media else []
        return any(t.get("type") == kind and not t.get("albumart") for t in tracks)

    def has_video(self) -> bool:
        return self._has_track("video")

    def length(self) -> int:
        """Длительность в миллисекундах (0, если ещё неизвестна)."""
        duration = self._props["duration"] if self.has_media else None
        return int(duration * 1000) if duration else 0

    def time(self) -> int:
        """Текущая позиция в миллисекундах."""
        position = self._props["time-pos"] if self.has_media else None
        return int(position * 1000) if position else 0

    # --- Управление -------------------------------------------------------

    def play(self):
        if not self.has_media:
            return
        if self.is_ended():
            self._mpv.seek(0, "absolute", "exact")
        self._set_pause(False)

    def pause(self):
        if self.has_media:
            self._set_pause(True)

    def toggle(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self):
        """Пауза и возврат в начало (файл остаётся открытым)."""
        if self.has_media:
            self._set_pause(True)
            self._mpv.seek(0, "absolute", "exact")

    def seek(self, ms: int):
        if not self.has_media:
            return
        # До самого конца можно: mpv (keep_open) просто встанет на последний кадр.
        length = self.length()
        if length:
            ms = min(ms, length)
        was_ended = self.is_ended()
        self._queue_seek(self._nearest_frame_target(ms), "exact")
        if was_ended:
            self._set_pause(False)

    def scrub(self, ms: int):
        """Перемотка, пока курсор таймлайна тянут мышью: тоже точная, на ближайший кадр
        (раньше здесь была перемотка по ключевым кадрам — на мгновение мелькал кадр на
        секунду-две раньше). Тормозить не будет: перемотки идут без ожидания и не копятся."""
        if not self.has_media:
            return
        was_ended = bool(self._props["eof-reached"])  # из подписки: не ждём mpv на каждом движении мыши
        self._queue_seek(self._nearest_frame_target(min(ms, self.length() or ms)), "exact")
        if was_ended:
            self._set_pause(False)  # видео доиграло — перемотка мышью запускает его снова, как раньше

    def _nearest_frame_target(self, ms: float) -> int:
        """При точной перемотке mpv показывает первый кадр, начинающийся не раньше чем за 5 мс
        до указанного времени. Поэтому целимся раньше на полкадра минус этот допуск — тогда
        получится ближайший кадр, а не следующий и не предыдущий."""
        fps = self._props.get("container-fps")
        if fps and fps > 0:
            ms -= max(500 / fps - _MPV_HRSEEK_SLACK_MS, 0)
        return int(max(ms, 0))

    def _queue_seek(self, ms: int, precision: str):
        """Все перемотки идут в mpv по одной и без ожидания (асинхронно).

        Следующая отправляется только после того, как mpv принял предыдущую, а из ожидающих
        хранится лишь самая свежая. Так при быстром перетаскивании не копится очередь, и
        перемотка при отпускании гарантированно выполняется последней — иначе mpv мог выполнить
        запоздавшую перемотку после неё."""
        with self._scrub_lock:
            if self._scrub_busy:
                self._scrub_next = (ms, precision)
                return
            self._scrub_busy = True
        self._send_seek(ms, precision)

    def _send_seek(self, ms: int, precision: str):
        def done(error, result):
            with self._scrub_lock:
                following, self._scrub_next = self._scrub_next, None
                if following is None:
                    self._scrub_busy = False
                    return
            self._send_seek(*following)

        try:
            self._mpv.command_async("seek", ms / 1000, f"absolute+{precision}", callback=done)
        except Exception:  # noqa: BLE001 — mpv закрывается или файл не открыт
            with self._scrub_lock:
                self._scrub_busy, self._scrub_next = False, None

    def seek_by(self, delta_ms: int):
        self.seek(self.time() + delta_ms)

    def next_frame(self):
        if self.has_media:
            self._mpv.frame_step()

    def prev_frame(self):
        if self.has_media:
            self._mpv.command("frame-back-step")

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, rate: float):
        self._rate = rate
        if self._mpv:
            self._mpv.speed = rate

    def set_loop(self, loop: bool):
        """Повтор: дойдя до конца, видео начинается заново (действует и на следующие файлы)."""
        if self._mpv:
            self._mpv["loop-file"] = "inf" if loop else "no"

    def screenshot(self, path: str, on_done):
        """Сохраняет текущий кадр в path (формат — по расширению) в полном размере видео, без надписей.
        Без ожидания: on_done(ok) вызывается из потока mpv, когда файл записан."""
        if not self.has_media:
            on_done(False)
            return
        try:
            self._mpv.command_async("screenshot-to-file", path, "video",
                                    callback=lambda error, result: on_done(error is None))
        except Exception:  # noqa: BLE001
            on_done(False)

    # --- Звук -------------------------------------------------------------

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def muted(self) -> bool:
        return self._muted

    def set_volume(self, value: int):
        self._volume = int(max(0, min(value, 100)))
        if self._mpv:
            self._mpv.volume = self._volume

    def set_muted(self, muted: bool):
        self._muted = muted
        if self._mpv:
            self._mpv.mute = muted

    def audio_track(self) -> int | None:
        """Какая звуковая дорожка звучит (номер с 0, по порядку в файле) — None, если звук выключен."""
        if not (self._mpv and self.has_media):
            return None
        try:
            aid = self._mpv.aid
        except Exception:  # noqa: BLE001
            return None
        return aid - 1 if isinstance(aid, int) and aid > 0 else None

    def set_audio_track(self, index: int):
        """Слушать дорожку index (с 0): у mpv дорожки звука нумеруются с 1 в том же порядке, что у FFmpeg."""
        if self._mpv and self.has_media:
            self._mpv.aid = index + 1

    # --- Служебное --------------------------------------------------------

    def tick(self):
        """Вызывается по таймеру окна. mpv применяет всё сразу, поэтому делать здесь нечего."""

    def release(self):
        if self._mpv:
            self._mpv.terminate()
            self._mpv = None

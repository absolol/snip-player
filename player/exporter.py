"""Сохранение обрезанного видео через FFmpeg — в фоне, с прогрессом и отменой.

Режимы:

«Без потерь» (умная обрезка). Видео между ключевыми кадрами копируется байт в байт, без
перекодирования, — качество и битрейт остаются как в исходнике. Перекодируются только
кадры у границ разреза (от точки разреза до ближайшего ключевого кадра, обычно доли
секунды) — с почти без потерь высоким качеством. Звук копируется без изменений.
Результат проверяется (число кадров и декодирование у стыков). Если кодек не H.264/H.265
или проверка не прошла, видео перекодируется целиком с очень высоким качеством,
а звук всё равно копируется.

«Быстро». Всё копируется, разрезы — по ключевым кадрам (границы могут сдвинуться).

Ускорение:
- перекодирование идёт на видеокарте (NVIDIA NVENC, Intel Quick Sync, AMD AMF), если она
  умеет нужный кодек и формат кадра; иначе — на процессоре (encoder="cpu" — всегда процессор);
- независимые части (кусочки у стыков, копирование, звук, проверка стыков) делаются параллельно;
- временные файлы лежат рядом с итоговым, поэтому готовый файл не копируется между дисками.
"""

import bisect
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from PySide6.QtCore import QObject, Signal

from .i18n import num, tr
from .paths import tool

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_FASTSTART_SUFFIXES = {".mp4", ".m4v", ".mov"}
_PIX_FMTS = {"yuv420p", "yuvj420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le"}

# Кодирование на процессоре. CRF 12 / 14 — визуально без потерь; preset fast в 3–4 раза
# быстрее slow при той же картинке (файл чуть больше).
_CPU_ENCODERS = {
    "h264": ("libx264", ["-crf", "12", "-preset", "fast"]),
    "hevc": ("libx265", ["-crf", "14", "-preset", "fast", "-x265-params", "log-level=error:open-gop=0"]),
}

# Кодирование на видеокарте: (кодировщик, параметры почти без потерь, формат кадра для 8 / 10 бит).
_GPU_ENCODERS = {
    "h264": [
        ("h264_nvenc", ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0"], "yuv420p", None),
        ("h264_qsv", ["-preset", "slower", "-global_quality", "18"], "nv12", None),
        ("h264_amf", ["-quality", "quality", "-rc", "cqp", "-qp_i", "16", "-qp_p", "18", "-qp_b", "20"], "nv12", None),
    ],
    "hevc": [
        ("hevc_nvenc", ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0"], "yuv420p", "p010le"),
        ("hevc_qsv", ["-preset", "slower", "-global_quality", "20"], "nv12", "p010le"),
        ("hevc_amf", ["-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20", "-qp_b", "22"], "nv12", "p010le"),
    ],
}
_GPU_NAMES = {"nvenc": tr("видеокарта NVIDIA (NVENC)"), "qsv": tr("видеокарта Intel (Quick Sync)"),
              "amf": tr("видеокарта AMD (AMF)")}
CANCELLED = tr("Сохранение отменено.")  # main_window сравнивает с ним: об отмене не сообщаем ошибкой

_gpu_cache: dict[str, bool] = {}
_gpu_lock = threading.Lock()


def _gpu_encoder_works(name: str) -> bool:
    """Пробует закодировать пару кадров. Результат запоминается до закрытия плеера."""
    with _gpu_lock:
        if name not in _gpu_cache:
            result = subprocess.run(
                [tool("ffmpeg"), "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                 "-frames:v", "2", "-c:v", name, "-f", "null", "-"],
                capture_output=True, creationflags=_NO_WINDOW,
            )
            _gpu_cache[name] = result.returncode == 0
        return _gpu_cache[name]


class ExportError(Exception):
    pass


class ExportCancelled(Exception):
    pass


class Exporter(QObject):
    progress = Signal(float)            # от 0 до 1
    status = Signal(str)                # что сейчас происходит
    finished = Signal(bool, str, str)   # успех; путь к файлу или текст ошибки; пояснение

    ENCODER_CHOICES = ("auto", "cpu")   # auto — видеокарта, если подходит; позже выбор появится в настройках

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._span, self._prefix = (0.0, 1.0), ""  # часть полосы прогресса и приставка надписи (start_many)
        self._cancel = threading.Event()
        self._procs: set = set()
        self._procs_lock = threading.Lock()
        # Заранее, в фоне, узнаём, какие кодировщики видеокарты работают, —
        # чтобы первое сохранение не тратило на это время.
        threading.Thread(target=self._warm_up_gpu, daemon=True).start()

    @staticmethod
    def _warm_up_gpu():
        if not tool("ffmpeg"):
            return
        for options in _GPU_ENCODERS.values():
            for name, *_ in options:
                if _gpu_encoder_works(name):
                    break  # для этого кодека подходящий уже найден

    @property
    def running(self) -> bool:
        return self._busy

    def start(self, src: str, dst: str, segments, lossless: bool, encoder: str = "auto",
              audio_tracks: list[int] | None = None):
        """segments — оставляемые куски [(начало_мс, конец_мс), ...]; audio_tracks — какие звуковые дорожки
        сохранить (номера с 0, по порядку в файле), None — все, [] — без звука."""
        self.start_many(src, [(dst, segments)], lossless, encoder, audio_tracks)

    def start_many(self, src: str, outputs, lossless: bool, encoder: str = "auto",
                   audio_tracks: list[int] | None = None):
        """outputs — [(путь, куски_мс)]: несколько файлов по очереди («Сохранить куски отдельно»), полоса
        прогресса общая. finished(ok, пути через перевод строки, пояснение последнего)."""
        if not (tool("ffmpeg") and tool("ffprobe")):
            self.finished.emit(False, tr("FFmpeg не найден. Установите его и перезапустите плеер."), "")
            return
        self._busy = True
        self._cancel.clear()
        jobs = [(dst, [(start / 1000, end / 1000) for start, end in segments]) for dst, segments in outputs]
        threading.Thread(target=self._run, args=(src, jobs, lossless, encoder, audio_tracks), daemon=True).start()

    def cancel(self):
        self._cancel.set()
        with self._procs_lock:
            for proc in list(self._procs):
                if proc.poll() is None:
                    proc.kill()

    def _run(self, src, jobs, lossless, encoder, audio_tracks=None):
        ok, message, note = False, "", ""
        done = []
        try:
            for n, (dst, segments) in enumerate(jobs):
                # Несколько файлов: у каждого своя часть общей полосы и «Кусок 2 из 3: …» в надписи.
                self._span = (n / len(jobs), 1 / len(jobs))
                self._prefix = tr("Кусок {n} из {total}: ", n=n + 1, total=len(jobs)) if len(jobs) > 1 else ""
                note = self._save_one(src, dst, segments, lossless, encoder, audio_tracks)
                done.append(dst)
            ok, message = True, "\n".join(done)
        except ExportCancelled:
            message = CANCELLED
        except ExportError as error:
            message = str(error)
        except Exception as error:  # noqa: BLE001 — любую ошибку показываем пользователю
            message = tr("Непредвиденная ошибка: {error}", error=error)
        if not ok and done and message != CANCELLED:
            message += "\n\n" + tr("Уже сохранены:") + "\n" + "\n".join(Path(d).name for d in done)
        self._span, self._prefix = (0.0, 1.0), ""
        self._busy = False
        self.finished.emit(ok, message, note)

    def _save_one(self, src, dst, segments, lossless, encoder, audio_tracks) -> str:
        """Один файл. Возвращает пояснение («Без потерь: …»)."""
        # Временная папка — рядом с итоговым файлом: тогда в конце файл просто
        # переименовывается, а не копируется целиком с диска на диск.
        try:
            tmp_root = tempfile.TemporaryDirectory(prefix=".player_cut_", dir=Path(dst).parent)
        except OSError:
            tmp_root = tempfile.TemporaryDirectory(prefix="player_cut_")
        with tmp_root as tmp:
            job = _Job(self, src, dst, segments, Path(tmp), encoder, audio_tracks)
            note = job.run(lossless)
            # Готовый файл переносится на место только в самом конце: при ошибке
            # или отмене файл, который выбрал пользователь, не трогается.
            Path(dst).unlink(missing_ok=True)
            shutil.move(str(job.out), dst)
        return note

    def _report(self, fraction: float):
        start, size = self._span
        self.progress.emit(start + size * max(0.0, min(fraction, 1.0)))

    def _say(self, text: str):
        self.status.emit(self._prefix + text)


class _Progress:
    """Общая полоса прогресса для нескольких параллельных задач."""

    def __init__(self, job, start: float, end: float, weights: dict):
        self.job, self.start, self.end = job, start, end
        self.weights = weights
        self.total = sum(weights.values()) or 1.0
        self.done = {key: 0.0 for key in weights}
        self.lock = threading.Lock()

    def update(self, key, fraction: float):
        with self.lock:
            self.done[key] = max(self.done[key], min(max(fraction, 0.0), 1.0))
            value = sum(self.weights[k] * f for k, f in self.done.items()) / self.total
        self.job.report(self.start + (self.end - self.start) * value)


class _Job:
    """Одно сохранение. Работает в фоновых потоках."""

    def __init__(self, owner: Exporter, src: str, dst: str, segments, tmp: Path, encoder: str,
                 audio_tracks: list[int] | None = None):
        self.owner = owner
        self.audio_tracks = audio_tracks
        self.src = src
        self.segments = segments
        self.tmp = tmp
        self.encoder_pref = encoder
        self.suffix = Path(dst).suffix.lower()
        self.out = tmp / f"result{self.suffix}"
        self._log_ids = itertools.count()
        self.used_gpu = set()
        self.used_cpu = False

    # --- Запуск FFmpeg ----------------------------------------------------

    def report(self, fraction: float):
        self.owner._report(fraction)

    def say(self, text: str):
        self.owner._say(text)

    def check_cancel(self):
        if self.owner._cancel.is_set():
            raise ExportCancelled

    def ffmpeg(self, args, on_progress=None, length=0.0) -> str:
        """Запускает ffmpeg. on_progress(доля) вызывается по ходу, length — длительность результата в секундах."""
        self.check_cancel()
        cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats", *args]
        log_path = self.tmp / f"ffmpeg_{next(self._log_ids)}.log"
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True,
                                    encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
            with self.owner._procs_lock:
                self.owner._procs.add(proc)
            try:
                for line in proc.stdout:
                    if self.owner._cancel.is_set():
                        proc.kill()
                        break
                    key, _, value = line.strip().partition("=")
                    if on_progress and key == "out_time_us" and length > 0 and value.lstrip("-").isdigit():
                        on_progress(int(value) / 1_000_000 / length)
                proc.wait()
            finally:
                with self.owner._procs_lock:
                    self.owner._procs.discard(proc)
        self.check_cancel()
        errors = log_path.read_text(encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            tail = "\n".join(line for line in errors.splitlines() if line.strip())[-1500:]
            raise ExportError(tr("FFmpeg завершился с ошибкой (код {code}).", code=proc.returncode) + f"\n\n{tail}")
        if on_progress:
            on_progress(1.0)
        return errors

    def ffprobe(self, args) -> str:
        self.check_cancel()
        result = subprocess.run([tool("ffprobe"), "-v", "error", *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        if result.returncode != 0:
            raise ExportError(tr("Не удалось прочитать видео.") + f"\n\n{result.stderr[-1500:]}")
        return result.stdout

    def parallel(self, tasks, workers: int):
        """Выполняет задачи (функции без аргументов) параллельно. Первая ошибка останавливает остальные."""
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(task) for task in tasks]
            results, failure = [], None
            for future in futures:
                try:
                    results.append(future.result())
                except BaseException as error:  # noqa: BLE001
                    if failure is None:
                        failure = error
                        if not isinstance(error, ExportCancelled):
                            # остановить ещё идущие задачи, но не считать это отменой пользователя
                            with self.owner._procs_lock:
                                for proc in list(self.owner._procs):
                                    if proc.poll() is None:
                                        proc.kill()
            if failure:
                raise failure
            return results

    # --- Выбор кодировщика ------------------------------------------------

    def video_encoders(self, codec: str):
        """Список вариантов кодирования по порядку предпочтения: [(аргументы ffmpeg, кто кодирует), ...]."""
        options = []
        ten_bit = "10" in self.pix_fmt
        chroma_420 = self.pix_fmt in ("yuv420p", "yuvj420p", "yuv420p10le")
        if self.encoder_pref != "cpu" and chroma_420:
            for name, params, pix8, pix10 in _GPU_ENCODERS.get(codec, []):
                pix = pix10 if ten_bit else pix8
                if pix and _gpu_encoder_works(name):
                    options.append((["-c:v", name, *params, "-pix_fmt", pix], name.split("_")[1]))
                    break
        cpu_name, cpu_params = _CPU_ENCODERS.get(codec, _CPU_ENCODERS["h264"])
        options.append((["-c:v", cpu_name, *cpu_params, "-pix_fmt", self.pix_fmt], "cpu"))
        return options

    def encode(self, codec: str, build_args, on_progress=None, length=0.0):
        """Кодирует: сначала на видеокарте, при её ошибке — на процессоре.
        build_args(аргументы_кодировщика) возвращает полную команду ffmpeg."""
        options = self.video_encoders(codec)
        for i, (encoder_args, who) in enumerate(options):
            try:
                self.ffmpeg(build_args(encoder_args), on_progress, length)
                if who == "cpu":
                    self.used_cpu = True
                else:
                    self.used_gpu.add(who)
                return
            except ExportError:
                if i == len(options) - 1:
                    raise

    def encoder_note(self) -> str:
        parts = [_GPU_NAMES[g] for g in sorted(self.used_gpu)]
        if self.used_cpu:
            parts.append(tr("процессор"))
        return " " + tr("Кодирование: {who}.", who=", ".join(parts)) if parts else ""

    def workers(self) -> int:
        # Видеокарта держит несколько потоков кодирования (а копирование и звук её не занимают);
        # на процессоре каждый ffmpeg и так многопоточный, поэтому одновременно их меньше.
        cores = os.cpu_count() or 4
        return 6 if self.encoder_pref != "cpu" else max(2, min(4, cores // 4))

    # --- Сценарий ---------------------------------------------------------

    def run(self, lossless: bool) -> str:
        self.say(tr("Анализ видео…"))
        self.probe()
        if not lossless:
            if self.video and self.keyframes:
                shift = self.fast_cut()
                return tr("Быстрый режим: всё скопировано без перекодирования, границы разрезов сдвинуты "
                          "к ближайшим ключевым кадрам (максимум на {n} с).", n=num(shift, 1))
            self.fast_copy()
            return tr("Быстрый режим: скопировано без перекодирования.")
        if not self.video:
            if not self.audio:
                raise ExportError(tr("Нечего сохранять: в файле нет видео, а звук не выбран."))
            self.extract_audio_parallel()
            self.mux(video_list=None, span=(0.6, 1.0))
            return tr("Звук сохранён без перекодирования.")

        codec = self.video.get("codec_name", "")
        if codec in _CPU_ENCODERS:
            try:
                reencoded = self.smart_cut()
                return (tr("Без потерь: видео и звук скопированы без перекодирования, "
                           "заново закодированы только кадры у границ разрезов ({n} шт.).", n=reencoded)
                        + self.encoder_note())
            except ExportError as error:
                reason = tr("умная обрезка не прошла проверку ({error})", error=str(error).splitlines()[0])
        else:
            reason = tr("для кодека {codec} умная обрезка недоступна", codec=codec or tr("этого видео"))

        self.say(tr("Перекодирование с максимальным качеством…"))
        self.report(0.0)
        if self.audio:
            # Заново: если умная обрезка сорвалась, её звуковые задачи могли быть прерваны.
            self.extract_audio_parallel()
        self.full_reencode()
        self.check_result()
        return (tr("Видео перекодировано с очень высоким качеством, звук скопирован без изменений ({reason}).",
                   reason=reason)
                + self.encoder_note())

    # --- Анализ -----------------------------------------------------------

    def probe(self):
        # Один вызов ffprobe на всё: каждый запуск FFmpeg сам по себе стоит заметного времени.
        info = json.loads(self.ffprobe(["-show_streams", "-show_format",
                                        "-show_entries", "packet=stream_index,pts_time,flags",
                                        "-of", "json", self.src]))
        streams = info.get("streams", [])
        self.video = next((s for s in streams if s.get("codec_type") == "video"
                           and not s.get("disposition", {}).get("attached_pic")), None)
        audio_count = sum(s.get("codec_type") == "audio" for s in streams)
        if self.audio_tracks is not None:
            self.audio_tracks = [i for i in self.audio_tracks if 0 <= i < audio_count]
        # Звук в итоге: все дорожки или выбранные (кнопка «Звук: 2 из 3»); ни одной — видео без звука.
        self.audio = bool(audio_count) and self.audio_tracks != []
        self.amap = ["-map", "0:a"] if self.audio_tracks is None else \
            [arg for i in self.audio_tracks for arg in ("-map", f"0:a:{i}")]
        # Названия дорожек («Игра», «Микрофон»…) при склейке кусков теряются (в MP4 — всегда) — пишем их заново.
        names = []
        for stream in (s for s in streams if s.get("codec_type") == "audio"):
            tags = {k.lower(): v for k, v in stream.get("tags", {}).items()}
            names.append(tags.get("title") or tags.get("name") or "")  # name — так MP4 хранит title
        kept = range(audio_count) if self.audio_tracks is None else self.audio_tracks
        self.audio_names = [arg for k, i in enumerate(kept) if names[i]
                            for arg in (f"-metadata:s:a:{k}", f"title={names[i]}")]
        fmt = info.get("format", {})
        self.duration = float(fmt.get("duration") or 0)
        self.start_time = float(fmt.get("start_time") or 0)
        if self.duration <= 0:
            raise ExportError(tr("Не удалось определить длительность видео."))
        if not self.video:
            return

        self.vmap = f"0:{self.video['index']}"
        pix = self.video.get("pix_fmt", "")
        self.pix_fmt = pix if pix in _PIX_FMTS else "yuv420p"

        # Все кадры видео: время показа и признак ключевого кадра.
        self.frames, self.keyframes = [], []
        for packet in info.get("packets", []):
            if packet.get("stream_index") != self.video["index"]:
                continue
            try:
                t = float(packet["pts_time"]) - self.start_time  # FFmpeg и mpv считают время от начала файла
            except (KeyError, ValueError):
                continue
            self.frames.append(t)
            if "K" in packet.get("flags", ""):
                self.keyframes.append(t)
        self.frames.sort()
        self.keyframes.sort()
        steps = [b - a for a, b in zip(self.frames, self.frames[1:]) if b > a]
        self.frame_dur = median(steps) if steps else 1 / 30
        self.tol = self.frame_dur / 2

    def frames_in(self, a: float, b: float) -> int:
        """Сколько кадров показывается в промежутке [a, b)."""
        return bisect.bisect_left(self.frames, b - self.tol) - bisect.bisect_left(self.frames, a - self.tol)

    # --- Звук -------------------------------------------------------------

    def audio_tasks(self, progress: _Progress = None):
        """Задачи: вырезать звук каждого оставляемого куска без перекодирования.

        Первый -ss (перед -i) — быстрый переход немного раньше точки разреза: при копировании
        FFmpeg попадает на ключевой кадр и может начать слишком рано. Второй -ss (после -i)
        отбрасывает всё до точки разреза. Точность — один звуковой пакет (~20 мс)."""
        self.audio_pieces = []
        tasks = []
        for i, (s, e) in enumerate(self.segments):
            path = self.tmp / f"audio_{i:04d}.mka"
            self.audio_pieces.append((path, e - s))
            coarse = max(s - 15.0, 0.0)
            args = ["-ss", f"{coarse:.6f}", "-i", self.src, "-ss", f"{s - coarse:.6f}", "-t", f"{e - s:.6f}",
                    *self.amap, "-vn", "-sn", "-dn", "-c", "copy", str(path)]
            key = ("audio", i)
            on_progress = (lambda f, k=key: progress.update(k, f)) if progress and key in progress.weights else None
            tasks.append(lambda a=args, cb=on_progress, d=e - s: self.ffmpeg(a, cb, d))
        return tasks

    def extract_audio_parallel(self):
        self.parallel(self.audio_tasks(), workers=4)

    # --- Умная обрезка ----------------------------------------------------

    def plan(self, s: float, e: float):
        """Делит оставляемый кусок на части: перекодировать (enc) или скопировать (copy)."""
        tol, keys = self.tol, self.keyframes
        k1 = keys[bisect.bisect_left(keys, s - tol)] if bisect.bisect_left(keys, s - tol) < len(keys) else None
        if k1 is None:
            return [("enc", s, e)]
        if e >= self.duration - tol:
            copy_to, tail = e, None  # до конца файла можно копировать без перекодирования
        else:
            i = bisect.bisect_right(keys, e + tol) - 1
            if i < 0:
                return [("enc", s, e)]
            copy_to = keys[i]
            tail = ("enc", copy_to, e) if e - copy_to > tol else None
        if k1 >= copy_to - tol:
            return [("enc", s, e)]  # внутри куска нет ни одного целого отрезка между ключевыми кадрами
        parts = []
        if k1 - s > tol:
            parts.append(("enc", s, k1))
        parts.append(("copy", k1, copy_to))
        if tail:
            parts.append(tail)
        return parts

    def snap_segments(self):
        """Быстрый режим: границы кусков — к ближайшим ключевым кадрам, чтобы видео можно было
        скопировать, а звук резался ровно там же (иначе звук расходится с картинкой)."""
        keys, tol = self.keyframes, self.tol

        def nearest(t):
            i = bisect.bisect_left(keys, t)
            near = [k for k in keys[max(i - 1, 0):i + 1]]
            return min(near, key=lambda k: abs(k - t))

        snapped = []
        for s, e in self.segments:
            a = 0.0 if s <= tol else nearest(s)
            b = self.duration if e >= self.duration - tol else nearest(e)
            if b - a < self.frame_dur:  # кусок короче группы кадров — берём целую группу
                a = keys[max(bisect.bisect_right(keys, s + tol) - 1, 0)]
                i = bisect.bisect_left(keys, e - tol)
                b = keys[i] if i < len(keys) else self.duration
            if snapped and a <= snapped[-1][1] + tol:  # после сдвига куски сошлись — склеиваем
                snapped[-1] = (snapped[-1][0], max(snapped[-1][1], b))
            else:
                snapped.append((a, b))
        shift = max(max(abs(a - s), abs(b - e)) for (s, e), (a, b) in zip(self.segments, snapped)) \
            if len(snapped) == len(self.segments) else 0.0
        return snapped, shift

    def fast_cut(self) -> float:
        snapped, shift = self.snap_segments()
        self.segments = snapped  # звук и проверки — по тем же сдвинутым границам
        parts = [("copy", a, b, self.piece_frames(a, b)) for a, b in snapped]
        self.say(tr("Копирование без перекодирования…"))
        self.build_from_parts([p for p in parts if p[3] > 0])
        return shift

    def piece_frames(self, a: float, b: float) -> int:
        return self.frames_in(a, b) if b < self.duration - self.tol else self.frames_in(a, self.duration + self.frame_dur)

    def smart_cut(self) -> int:
        parts = []
        for kind, a, b in (p for s, e in self.segments for p in self.plan(s, e)):
            n = self.piece_frames(a, b)
            if n > 0:
                parts.append((kind, a, b, n))
        enc_time = sum(b - a for kind, a, b, n in parts if kind == "enc")
        self.say(tr("Кадры у границ разрезов и копирование… (перекодируется {n} с)", n=num(enc_time, 1)))
        self.build_from_parts(parts)
        return sum(n for kind, *_, n in parts if kind == "enc")

    def build_from_parts(self, parts):
        """Кодирует/копирует части видео и звук параллельно, собирает файл и проверяет его."""
        codec = self.video["codec_name"]

        # Вес задачи для полосы прогресса: перекодирование заметно дольше копирования.
        weights = {("video", i): (b - a) * (1.0 if kind == "enc" else 0.05) for i, (kind, a, b, n) in enumerate(parts)}
        if self.audio:
            weights.update({("audio", i): (e - s) * 0.03 for i, (s, e) in enumerate(self.segments)})
        progress = _Progress(self, 0.0, 0.7, weights)

        pieces, tasks = [], []
        for i, (kind, a, b, n) in enumerate(parts):
            path = self.tmp / f"piece_{i:04d}.ts"
            pieces.append((path, b - a))
            on_progress = lambda f, k=("video", i): progress.update(k, f)  # noqa: E731
            if kind == "enc":
                def build(encoder_args, a=a, n=n, path=path):
                    return ["-ss", f"{max(a - self.tol / 2, 0):.6f}", "-i", self.src, "-map", self.vmap,
                            "-frames:v", str(n), *encoder_args, "-fps_mode", "passthrough",
                            "-an", "-sn", "-dn", "-f", "mpegts", str(path)]
                tasks.append(lambda build=build, cb=on_progress, d=b - a: self.encode(codec, build, cb, d))
            else:
                args = ["-ss", f"{a + self.tol / 2:.6f}", "-i", self.src, "-map", self.vmap, "-c", "copy",
                        "-frames:v", str(n), "-an", "-sn", "-dn", "-f", "mpegts", str(path)]
                tasks.append(lambda args=args, cb=on_progress, d=b - a: self.ffmpeg(args, cb, d))
        if self.audio:
            tasks += self.audio_tasks(progress)
        self.parallel(tasks, self.workers())

        video_list = self.tmp / "video.txt"
        video_list.write_text("".join(f"file '{p.as_posix()}'\nduration {d:.6f}\n" for p, d in pieces), encoding="utf-8")
        self.say(tr("Сборка файла…"))
        self.mux(video_list, span=(0.7, 0.8))

        self.say(tr("Проверка результата…"))
        self.verify(sum(n for *_, n in parts), [d for _, d in pieces])

    def verify(self, expected_frames: int, durations):
        # Подсчёт кадров и проверка стыков читают готовый файл независимо — делаем их одновременно.
        # Декодируем по 3 секунды вокруг каждого стыка: там могли бы появиться артефакты.
        # Несколько стыков — в одном процессе FFmpeg (у каждого стыка свой вход), процессы — параллельно.
        out = str(self.out)
        joints, t = [0.0], 0.0
        for d in durations[:-1]:
            t += d
            joints.append(t)
        batches = [joints[i:i + 4] for i in range(0, len(joints), 4)]
        progress = _Progress(self, 0.8, 1.0, {i: 1.0 for i in range(len(batches))})

        def check(i, batch):
            args = []
            for joint in batch:
                args += ["-ss", f"{max(joint - 1.5, 0):.3f}", "-t", "3", "-i", out]
            for k in range(len(batch)):
                args += ["-map", f"{k}:v:0"]
            errors = self.ffmpeg([*args, "-f", "null", "-"])
            progress.update(i, 1.0)
            # Важны только ошибки декодера. Сообщения «пустого» выхода [null @ …] о метках времени
            # на краю проверяемого фрагмента к качеству файла отношения не имеют.
            decoder_errors = [line for line in errors.splitlines()
                              if line.strip() and not line.startswith("[null @") and "Last message repeated" not in line]
            if decoder_errors:
                raise ExportError(tr("ошибка декодирования у стыков около {times} с",
                                       times=", ".join(num(j, 2) for j in batch)))

        tasks = [lambda: self.check_result(expected_frames)]
        tasks += [lambda i=i, b=b: check(i, b) for i, b in enumerate(batches)]
        self.parallel(tasks, workers=5)

    def check_result(self, expected_frames=None):
        """Одним вызовом ffprobe: число кадров видео и длина звука в итоговом файле."""
        info = json.loads(self.ffprobe(["-show_entries", "stream=index,codec_type:packet=stream_index,pts_time,duration_time",
                                        "-of", "json", str(self.out)]))
        kinds = {s["index"]: s.get("codec_type") for s in info.get("streams", [])}
        video_frames, audio_end = 0, 0.0
        audio_index = next((i for i, k in kinds.items() if k == "audio"), None)
        for packet in info.get("packets", []):
            kind = kinds.get(packet.get("stream_index"))
            if kind == "video":
                video_frames += 1
            elif packet.get("stream_index") == audio_index:
                try:
                    audio_end = max(audio_end, float(packet["pts_time"]) + float(packet.get("duration_time") or 0))
                except (KeyError, ValueError):
                    continue
        if expected_frames is not None and video_frames != expected_frames:
            raise ExportError(tr("число кадров не совпало: {got} вместо {expected}", got=video_frames, expected=expected_frames))
        # Звук должен быть той же длины, что и итог (с точностью до пары пакетов).
        expected = sum(e - s for s, e in self.segments)
        if self.audio and abs(audio_end - expected) > 0.1 + 0.05 * len(self.segments):
            raise ExportError(tr("длина звука {audio} с не совпадает с длиной видео {video} с", audio=num(audio_end, 2), video=num(expected, 2)))

    # --- Сборка, быстрый режим, полное перекодирование --------------------

    def audio_list(self) -> Path:
        path = self.tmp / "audio.txt"
        path.write_text("".join(f"file '{p.as_posix()}'\nduration {d:.6f}\n" for p, d in self.audio_pieces),
                        encoding="utf-8")
        return path

    def faststart(self):
        return ["-movflags", "+faststart"] if self.suffix in _FASTSTART_SUFFIXES else []

    def mux(self, video_list, span):
        """Собирает итоговый файл из готового видео (список кусков) и скопированного звука."""
        args, maps, index = [], [], 0
        if video_list:
            args += ["-f", "concat", "-safe", "0", "-i", str(video_list)]
            maps += ["-map", f"{index}:v"]
            index += 1
        if self.audio:
            args += ["-f", "concat", "-safe", "0", "-i", str(self.audio_list())]
            maps += ["-map", f"{index}:a"]
        total = sum(e - s for s, e in self.segments)
        report = lambda f: self.report(span[0] + (span[1] - span[0]) * min(f, 1.0))  # noqa: E731
        names = self.audio_names if self.audio else []
        self.ffmpeg([*args, *maps, "-c", "copy", *names, *self.faststart(), str(self.out)], report, total)

    def fast_copy(self):
        self.say(tr("Копирование без перекодирования…"))
        quoted = self.src.replace("\\", "/").replace("'", "'\\''")
        listing = self.tmp / "fast.txt"
        listing.write_text("".join(f"file '{quoted}'\ninpoint {s:.6f}\noutpoint {e:.6f}\n" for s, e in self.segments),
                           encoding="utf-8")
        total = sum(e - s for s, e in self.segments)
        report = lambda f: self.report(0.1 + 0.9 * min(f, 1.0))  # noqa: E731
        audio = ["-map", "0:a?"] if self.audio_tracks is None else self.amap  # [] — без звука
        self.ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:v:0?", *audio, *self.audio_names,
                     "-c", "copy", "-avoid_negative_ts", "make_zero", *self.faststart(), str(self.out)],
                    report, total)

    def full_reencode(self):
        graph, labels = [], ""
        for i, (s, e) in enumerate(self.segments):
            graph.append(f"[{self.vmap}]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[v{i}]")
            labels += f"[v{i}]"
        graph.append(f"{labels}concat=n={len(self.segments)}:v=1:a=0[v]")

        inputs = ["-i", self.src]
        maps = ["-map", "[v]"]
        if self.audio:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(self.audio_list())]
            maps += ["-map", "1:a", "-c:a", "copy", *self.audio_names]
        total = sum(e - s for s, e in self.segments)
        report = lambda f: self.report(min(f, 1.0))  # noqa: E731

        def build(encoder_args):
            return [*inputs, "-filter_complex", ";".join(graph), *maps, *encoder_args, *self.faststart(), str(self.out)]

        if self.suffix == ".webm":  # в WebM нельзя H.264/H.265 — только VP9 на процессоре
            self.ffmpeg(build(["-c:v", "libvpx-vp9", "-crf", "15", "-b:v", "0", "-row-mt", "1",
                               "-pix_fmt", self.pix_fmt]), report, total)
            self.used_cpu = True
        else:
            self.encode("hevc" if self.video.get("codec_name") == "hevc" else "h264", build, report, total)

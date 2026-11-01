"""Сведения о видеофайле для панели под именем файла: размер, длительность, кодеки, битрейт.

Сведения берутся у ffprobe одним вызовом в фоновом потоке (запуск FFmpeg стоит заметного
времени, интерфейс не должен его ждать) — сразу после открытия файла, чтобы к щелчку
по имени всё уже было готово. Без ffprobe показываются только сведения о самом файле.
"""

import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .i18n import LANG, tr
from .paths import tool

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_VIDEO_CODECS = {
    "h264": "H.264 (AVC)", "hevc": "H.265 (HEVC)", "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
    "mpeg4": "MPEG-4", "mpeg2video": "MPEG-2", "mpeg1video": "MPEG-1", "prores": "ProRes",
    "mjpeg": "Motion JPEG", "wmv3": "WMV 9", "vc1": "VC-1",
}
_AUDIO_CODECS = {
    "aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "ac3": "AC-3 (Dolby Digital)",
    "eac3": "E-AC-3", "dts": "DTS", "flac": "FLAC", "alac": "ALAC", "truehd": "Dolby TrueHD",
    "wmav2": "WMA",
}
_CHANNELS = {1: tr("моно"), 2: tr("стерео"), 6: "5.1", 8: "7.1"}


# --- Форматирование ---------------------------------------------------------

def _number(value: float, digits: int = 1) -> str:
    """1234.5 → '1 234,5' (как принято по-русски), по-английски — '1,234.5'."""
    text = f"{value:,.{digits}f}"
    if LANG == "ru":
        text = text.replace(",", " ").replace(".", ",")
    point = "," if LANG == "ru" else "."
    if digits and text.endswith(point + "0" * digits):
        text = text[: -digits - 1]
    return text


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return tr("{n} ГБ", n=_number(size / 1024 ** 3, 2))
    if size >= 1024 ** 2:
        return tr("{n} МБ", n=_number(size / 1024 ** 2, 1))
    return tr("{n} КБ", n=_number(size / 1024, 0))


def _date(moment: datetime) -> str:
    """Дата изменения: «31.10.2026, 14:05» по-русски, «Oct 31, 2026, 2:05 PM» по-английски."""
    if LANG == "ru":
        return moment.strftime("%d.%m.%Y, %H:%M")
    hour = moment.hour % 12 or 12
    return f"{moment:%b} {moment.day}, {moment.year}, {hour}:{moment:%M} {'AM' if moment.hour < 12 else 'PM'}"


def format_duration(seconds: float) -> str:
    # Как на шкале плеера: 0:38, 1:02:05 (доли секунды отбрасываются: 7,7 с → 0:07).
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_bitrate(bits_per_second) -> str:
    try:
        kbps = float(bits_per_second) / 1000
    except (TypeError, ValueError):
        return ""
    if kbps <= 0:
        return ""
    # Доли отбрасываются, а не округляются — как в свойствах файла Windows (161,65 → 161).
    if kbps >= 10000:
        return tr("{n} Мбит/с", n=_number(int(kbps / 100) / 10, 1))
    return tr("{n} кбит/с", n=_number(int(kbps), 0))


def _fps(stream: dict) -> str:
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(stream.get(key, "")).partition("/")
        try:
            value = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if value > 0:
            return tr("{n} к/с", n=_number(value, 2 if abs(value - round(value)) > 0.005 else 0))
    return ""


def _stream_bitrate(stream: dict):
    # В MKV битрейт дорожки лежит не в bit_rate, а в метке BPS (иногда BPS-eng).
    tags = stream.get("tags", {})
    return stream.get("bit_rate") or tags.get("BPS") or tags.get("BPS-eng")


def _codec(stream: dict, names: dict) -> str:
    name = stream.get("codec_name", "")
    return names.get(name, name.upper() or "—")


# --- Сбор сведений ----------------------------------------------------------

def collect(path: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Группы сведений: [("Файл", [(название, значение), …]), ("Видео", …), ("Звук", …)].
    Пустые значения (ffprobe их не знает) не показываются."""
    return collect_all(path)[0]


def collect_all(path: str) -> tuple[list, list[dict]]:
    """Сведения (как collect) и звуковые дорожки (audio_tracks) — одним вызовом ffprobe."""
    file = Path(path)
    stat = file.stat()
    info = _probe(path)
    fmt = info.get("format", {})
    streams = info.get("streams", [])

    duration = float(fmt.get("duration") or 0)
    file_rows = [
        (tr("Размер"), format_size(stat.st_size)),
        (tr("Длительность"), format_duration(duration) if duration else ""),
        (tr("Формат"), file.suffix.lstrip(".").upper()),
        (tr("Общий битрейт"), format_bitrate(fmt.get("bit_rate"))),
        (tr("Изменён"), _date(datetime.fromtimestamp(stat.st_mtime))),
        (tr("Папка"), str(file.parent)),
    ]
    groups = [(tr("Файл"), file_rows)]
    if not info:
        groups.append((tr("Видео"), [("", tr("Нет сведений: не найден ffprobe"))]))
        return _clean(groups), []

    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video:
        size = f"{video['width']} × {video['height']}" if video.get("width") else ""
        groups.append((tr("Видео"), [
            (tr("Разрешение"), size),
            (tr("Частота кадров"), _fps(video)),
            (tr("Кодек"), _codec(video, _VIDEO_CODECS)),
            (tr("Битрейт"), format_bitrate(_stream_bitrate(video))),
        ]))
    else:
        groups.append((tr("Видео"), [("", tr("нет видеодорожки"))]))

    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if audio_streams:
        audio = audio_streams[0]
        channels = int(audio.get("channels") or 0)
        rate = float(audio.get("sample_rate") or 0)
        rows = [
            (tr("Кодек"), _codec(audio, _AUDIO_CODECS)),
            (tr("Битрейт"), format_bitrate(_stream_bitrate(audio))),
            (tr("Частота"), tr("{n} кГц", n=_number(rate / 1000, 1)) if rate else ""),
            (tr("Каналы"), _CHANNELS.get(channels, tr("{n} кан.", n=channels)) if channels else ""),
        ]
        if len(audio_streams) > 1:
            rows.append((tr("Дорожек"), str(len(audio_streams))))
        groups.append((tr("Звук"), rows))
    else:
        groups.append((tr("Звук"), [("", tr("нет звуковой дорожки"))]))
    return _clean(groups), audio_tracks(streams)


def audio_tracks(streams: list[dict]) -> list[dict]:
    """Звуковые дорожки по порядку (как их нумеруют FFmpeg «0:a:N» и mpv aid=N+1) — для выбора при сохранении:
    {"title": «Дорожка 2 · Микрофон», "info": «AAC · моно · 48 кГц · 96 кбит/с»}."""
    tracks = []
    for n, stream in enumerate((s for s in streams if s.get("codec_type") == "audio"), start=1):
        tags = {k.lower(): v for k, v in stream.get("tags", {}).items()}
        name = tags.get("title") or tags.get("name") or tags.get("handler_name", "")  # name — так MP4 хранит title
        if name.lower() in ("soundhandler", "sound media handler", "audiohandler"):  # имя по умолчанию в MP4
            name = ""
        title = tr("Дорожка {n}", n=n) + (f" · {name}" if name else "")
        channels = int(stream.get("channels") or 0)
        rate = float(stream.get("sample_rate") or 0)
        parts = [_codec(stream, _AUDIO_CODECS),
                 _CHANNELS.get(channels, tr("{n} кан.", n=channels)) if channels else "",
                 tr("{n} кГц", n=_number(rate / 1000, 1)) if rate else "",
                 format_bitrate(_stream_bitrate(stream))]
        tracks.append({"title": title, "info": " · ".join(p for p in parts if p)})
    return tracks


def _clean(groups):
    return [(title, [(k, v) for k, v in rows if v]) for title, rows in groups]


def _probe(path: str) -> dict:
    if not tool("ffprobe"):
        return {}
    try:
        result = subprocess.run([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=_NO_WINDOW, timeout=30)
        return json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}


def as_text(name: str, groups) -> str:
    """Сведения обычным текстом — для кнопки «Копировать»."""
    lines = [name]
    for title, rows in groups:
        lines.append("")
        lines.append(f"{title}:")
        lines.extend(f"  {k}: {v}" if k else f"  {v}" for k, v in rows)
    return "\n".join(lines)


class MediaInfoLoader(QObject):
    """Собирает сведения в фоновом потоке и запоминает их для текущего файла."""

    ready = Signal(str)  # путь файла, для которого сведения готовы

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        self.groups = None  # None — ещё собираются
        self.tracks: list[dict] = []  # звуковые дорожки (audio_tracks)
        self.ready.connect(self._on_ready)
        self._results = {}

    def load(self, path: str):
        self.path, self.groups, self.tracks = path, None, []
        threading.Thread(target=self._work, args=(path,), daemon=True).start()

    def _work(self, path: str):
        try:
            result = collect_all(path)
        except OSError as error:
            result = [(tr("Файл"), [("", tr("Не удалось прочитать файл: {error}", error=error))])], []
        self._results[path] = result
        self.ready.emit(path)  # сигнал из потока доходит в главный поток очередью

    def _on_ready(self, path: str):
        if path == self.path:
            self.groups, self.tracks = self._results.pop(path)
        else:
            self._results.pop(path, None)

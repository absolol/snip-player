"""Настройки пользователя (окно «Настройки»): значения по умолчанию, чтение и запись в settings.ini.

Все ключи — в DEFAULTS; тип значения задаёт значение по умолчанию (QSettings в .ini хранит строки).
Сигнал changed(ключ) — окно настроек меняет значение, плеер сразу применяет.
"""

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor

from .paths import DATA_DIR

SETTINGS_PATH = DATA_DIR / "settings.ini"  # рядом с программой или в %APPDATA% (paths.py)

DEFAULTS = {
    # Воспроизведение
    "resume": False,             # продолжать с места, где остановились (по умолчанию выключено, 31.10.2026)
    "end_action": "stop",        # stop | next | repeat
    "seek_step": 5,              # секунды, ← →
    "seek_small_step": 1,        # секунды, Shift + ← →
    "volume_step": 5,            # проценты, ↑ ↓
    "hold_rate": 2.0,            # ускорение при удержании мыши / пробела
    "hold_rate_max": 3.0,        # предел, если потянуть мышь вправо
    # Внешний вид (тема — отдельный ключ "theme", как и раньше)
    "window_outline": "none",    # none | soft | accent
    "show_stop": False,
    "messages": True,            # уведомления поверх видео
    "message_seconds": 1.5,
    # «Своя» тема (тема "custom"): основа, цвет интерфейса, цвет уведомлений
    "custom_base": "dark",           # dark | light
    "custom_accent": "#4f8cff",
    "custom_notify": "same",         # same | lighter | deeper | hue_minus | hue_plus | own
    "custom_notify_color": "#4f8cff",  # для own
    # Язык интерфейса: ru | en; пусто — по языку Windows (i18n.py). Меняется после перезапуска.
    "language": "",
    # Окно
    "single_instance": True,     # новые видео — в уже открытом окне
    # Скриншоты
    "screenshot_dir": "",        # пусто — «Изображения\Snip Player»
    "screenshot_format": "png",  # png | jpg
    "screenshot_clipboard": True,
    # Обрезка и сохранение
    "encoder": "auto",           # auto (видеокарта, если умеет) | cpu
    "export_quality": "lossless",  # lossless | fast
    "save_mode": "copy",         # copy | replace
}

# Пределы чисел: (наименьшее, наибольшее, шаг кнопок − / +).
RANGES = {
    "seek_step": (1, 60, 1),
    "seek_small_step": (1, 30, 1),
    "volume_step": (1, 25, 1),
    "hold_rate": (1.25, 4.0, 0.25),
    "hold_rate_max": (1.25, 4.0, 0.25),
    "message_seconds": (0.5, 5.0, 0.5),
}

CHOICES = {
    "language": ("", "ru", "en"),
    "end_action": ("stop", "next", "repeat"),
    "window_outline": ("none", "soft", "accent"),
    "custom_base": ("dark", "light"),
    "custom_notify": ("same", "lighter", "deeper", "hue_minus", "hue_plus", "own"),
    "screenshot_format": ("png", "jpg"),
    "encoder": ("auto", "cpu"),
    "export_quality": ("lossless", "fast"),
    "save_mode": ("copy", "replace"),
}


COLORS = ("custom_accent", "custom_notify_color")  # цвета «#rrggbb»


def _convert(raw, default):
    if isinstance(default, bool):
        return raw if isinstance(raw, bool) else str(raw).lower() in ("true", "1", "yes")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def read(settings: QSettings, key: str):
    """Значение настройки из QSettings (без объекта Prefs — например, в main.py до создания окна)."""
    default = DEFAULTS[key]
    raw = settings.value(key, default)
    try:
        value = _convert(raw, default)
    except (TypeError, ValueError):
        return default
    if key in CHOICES and value not in CHOICES[key]:
        return default
    if key in COLORS and not QColor(value).isValid():
        return default
    if key in RANGES:
        low, high, _ = RANGES[key]
        value = min(max(value, low), high)
    return value


class Prefs(QObject):
    changed = Signal(str)

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

    def get(self, key: str):
        return read(self.settings, key)

    def set(self, key: str, value):
        if value == self.get(key):
            return
        self.settings.setValue(key, value)
        if key == "hold_rate_max" and value < self.get("hold_rate"):
            self.set("hold_rate", value)  # стартовая скорость не выше предела
        if key == "hold_rate" and value > self.get("hold_rate_max"):
            self.set("hold_rate_max", value)
        self.changed.emit(key)

"""Темы оформления.

Тёмная и светлая — JSON-файлы с цветами в папке themes/, «Своя» собирается из настроек
(build_custom_theme). Общий шаблон стилей (style.qss)
подставляет эти цвета вместо $переменных. Чтобы добавить тему, скопируйте любой
JSON-файл, поменяйте цвета и перезапустите плеер.
"""

import json
from string import Template

from PySide6.QtGui import QColor, QFontDatabase

from .i18n import tr
from .paths import THEMES_DIR

DEFAULT_THEME = "dark"


def icon_font() -> str:
    families = QFontDatabase.families()
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return "Segoe UI Symbol"


def load_themes() -> dict[str, dict]:
    """Возвращает {id темы: её настройки}, id — имя файла без .json."""
    themes = {}
    for path in sorted(THEMES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"Тема {path.name} пропущена: {error}")
            continue
        data.setdefault("name", path.stem)
        themes[path.stem] = data
    return themes


def build_stylesheet(theme: dict) -> str:
    template = Template((THEMES_DIR / "style.qss").read_text(encoding="utf-8"))
    values = {key: value for key, value in theme.items() if key != "name"}
    values["icon_font"] = icon_font()
    # Капсулы в заголовке круглее остальных элементов, но не больше половины их высоты (36 px),
    # иначе Qt игнорирует скругление и рисует прямые углы.
    values["radius_pill"] = min(int(theme.get("radius", 8)) + 8, 18)
    return template.safe_substitute(values)


# --- «Своя» тема (макет `концепты/своя_тема_оттенки.png`) ----------------------------------------
# Основа — тёмная или светлая тема (фон, панели, текст), цвет интерфейса и цвет уведомлений — свои.
# Уведомления — оттенок цвета интерфейса (NOTIFY_SHADES) или любой свой цвет.

CUSTOM_THEME = "custom"
SWATCHES = (  # готовые цвета интерфейса: (цвет, подсказка)
    ("#4f8cff", tr("Синий")), ("#8b5cf6", tr("Фиолетовый")), ("#ff3ea5", tr("Розовый")), ("#ef4444", tr("Красный")),
    ("#f97316", tr("Оранжевый")), ("#eab308", tr("Жёлтый")), ("#22c55e", tr("Зелёный")), ("#14b8a6", tr("Бирюзовый")),
)
NOTIFY_SHADES = (  # оттенки для уведомлений: (ключ, подсказка)
    ("same", tr("Как интерфейс")), ("lighter", tr("Светлее")), ("deeper", tr("Глубже")),
    ("hue_minus", tr("Соседний оттенок")), ("hue_plus", tr("Соседний оттенок с другой стороны")),
)


def notify_shade(accent: str, shade: str) -> str:
    """Оттенок цвета интерфейса для уведомлений. Разброс заметный: уведомление полупрозрачное,
    через стекло просвечивает видео, и слабая разница пропадала бы."""
    c = QColor(accent)
    h, s, l = c.hslHueF(), c.hslSaturationF(), c.lightnessF()

    def hsl(hue, sat, light):
        return QColor.fromHslF(hue % 1.0, min(max(sat, 0.0), 1.0), min(max(light, 0.0), 1.0)).name()

    if shade == "lighter":
        return hsl(h, s * 0.85, l + 0.2)
    if shade == "deeper":
        return hsl(h, min(s * 1.15, 1.0), l - 0.18)
    if shade == "hue_minus":
        return hsl(h - 30 / 360, s, l)
    if shade == "hue_plus":
        return hsl(h + 30 / 360, s, l)
    return c.name()


def build_custom_theme(base: dict, accent: str, notify: str) -> dict:
    """«Своя» тема из основы (тёмной / светлой) и двух цветов. notify — готовый цвет уведомлений."""
    theme = dict(base)
    theme["name"] = "Своя"
    a = QColor(accent)
    dark = QColor(base["bg"]).lightness() < 128
    theme["accent"] = a.name()
    theme["accent_hover"] = (a.lighter(118) if dark else a.lighter(112)).name()
    # Текст на кнопках цвета акцента: на светлом акценте (жёлтый) — тёмный, иначе белый.
    luminance = 0.2126 * a.redF() + 0.7152 * a.greenF() + 0.0722 * a.blueF()
    theme["accent_text"] = "#ffffff" if luminance < 0.62 else "#15171c"
    theme["notify"] = QColor(notify).name()
    return theme

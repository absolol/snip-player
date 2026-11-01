"""Язык интерфейса: русский или английский (макет `концепты/язык_*.png`).

Надписи в коде пишутся по-русски и оборачиваются в tr(): tr("Настройки") → «Settings», если выбран английский.
Английские строки — словарь EN в lang_en.py (ключ — русская строка как есть). Подстановки — как в str.format:
tr("Назад на {n} с", n=5). Числа с дробью — num() (по-русски запятая, по-английски точка), слова после
чисел — plural().

Язык выбирается до создания окон (при первом импорте): настройка `language` в settings.ini, а если её нет —
по языку Windows. Смена языка в настройках действует после перезапуска плеера.
"""

import ctypes
import os

from PySide6.QtCore import QSettings

from .lang_en import EN
from .paths import DATA_DIR

LANGUAGES = ("ru", "en")
# Языки Windows, для которых по умолчанию русский (основной код языка LANGID): русский, белорусский, казахский.
_RUSSIAN_WINDOWS = {0x19, 0x23, 0x3F}


def windows_language() -> str:
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "ru" if langid & 0x3FF in _RUSSIAN_WINDOWS else "en"


def _chosen() -> str:
    forced = os.environ.get("PLAYER_LANG", "")  # для проверок: язык без правки settings.ini
    if forced in LANGUAGES:
        return forced
    value = str(QSettings(str(DATA_DIR / "settings.ini"), QSettings.Format.IniFormat).value("language", ""))
    return value if value in LANGUAGES else windows_language()


LANG = _chosen()


def tr(text: str, **values) -> str:
    if LANG == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text


def tr_in(lang: str, text: str, **values) -> str:
    """Надпись на другом языке — например, вопрос о перезапуске сразу на выбранном языке."""
    if lang == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text


def num(value, digits: int | None = None) -> str:
    """Число с дробью: 2.5 → «2,5» (по-русски) / «2.5». digits — знаков после запятой (None — как есть, :g)."""
    text = f"{value:g}" if digits is None else f"{value:.{digits}f}"
    return text.replace(".", ",") if LANG == "ru" else text


def rate(value: float) -> str:
    """Скорость: 2.0 → «2,0×», 2.25 → «2,25×» (по-английски — с точкой)."""
    text = f"{value:.2f}".rstrip("0")
    text = text + "0" if text.endswith(".") else text
    return (text.replace(".", ",") if LANG == "ru" else text) + "×"


def plural(n: int, ru: tuple[str, str, str], en: tuple[str, str]) -> str:
    """Слово после числа: ru — (1 кусок, 2 куска, 5 кусков), en — (1 segment, 2 segments)."""
    if LANG == "en":
        return en[0] if n == 1 else en[1]
    if n % 10 == 1 and n % 100 != 11:
        return ru[0]
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return ru[1]
    return ru[2]

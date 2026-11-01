"""Регистрация плеера в Windows — только для текущего пользователя (HKCU), без прав администратора.

    python -m player.registration install     записать
    python -m player.registration uninstall   удалить всё, что записали

После записи плеер есть в «Открыть с помощью» для видео и в «Параметры → Приложения →
Приложения по умолчанию». Сделать себя программой по умолчанию сам он не может (Windows 10/11
это запрещает) — это делает человек: «Открыть с помощью → Выбрать другое приложение →
Snip Player → Всегда».
"""

import ctypes
import sys
import winreg
from pathlib import Path

from .i18n import tr
from .paths import APP_DIR, APP_NAME, FROZEN
from .utils import VIDEO_EXTENSIONS

OLD_APP_NAME = "Проигрыватель"  # прежнее имя-ключ в RegisteredApplications: убираем при установке и удалении
PROG_ID = "Proigryvatel.Video"
APP_USER_MODEL_ID = "Proigryvatel.Player"  # тот же, что в main.py — одна кнопка на панели задач
CAPABILITIES = r"Software\Proigryvatel\Capabilities"
APP_KEY = r"Software\Proigryvatel"
CLASSES = r"Software\Classes"
REGISTERED_APPS = r"Software\RegisteredApplications"

MAIN_PY = APP_DIR / "main.py"
ICON_PATH = APP_DIR / "Snip Player.ico"


def pythonw_path() -> Path:
    """pythonw.exe рядом с тем Python, который запустил регистрацию (без окна консоли)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def open_command() -> str:
    if FROZEN:  # собранная версия: сам Snip Player.exe
        return f'"{sys.executable}" "%1"'
    return f'"{pythonw_path()}" "{MAIN_PY}" "%1"'


def _set(root_path: str, values: dict):
    """Создать ключ HKCU\\root_path и записать значения ("" — значение «по умолчанию»)."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, root_path, 0, winreg.KEY_WRITE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _delete_tree(root_path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(f"{root_path}\\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root_path)
    except FileNotFoundError:
        pass


def _delete_value(root_path: str, name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _delete_if_empty(root_path: str):
    """Убрать ключ, если в нём ничего не осталось (пустые ключи .mp4 создала сама регистрация)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path) as key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
        if subkeys == 0 and values == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root_path)
    except OSError:
        pass


def _notify_explorer():
    # SHCNE_ASSOCCHANGED, SHCNF_IDLIST — Проводник перечитывает сопоставления файлов.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)


def make_icon():
    from PySide6.QtGui import QGuiApplication

    from .app_icon import save_ico
    from .themes import DEFAULT_THEME, load_themes

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 — QPixmap без него не рисует
    theme = load_themes().get(DEFAULT_THEME) or next(iter(load_themes().values()))
    save_ico(ICON_PATH, theme["accent"], theme["accent_hover"])


def _icon_value() -> str:
    if FROZEN:  # иконка вшита в exe
        return f"{sys.executable},0"
    return f"{ICON_PATH},0"  # без кавычек: путь в кавычках Проводник не читает и рисует значок pythonw


def status() -> str:
    """"ok" — зарегистрирован для этой папки, "moved" — для другой (папку перенесли), "outdated" — записан
    прежней версией (другая иконка или имя «Проигрыватель»), "none" — нет."""
    try:
        command = winreg.QueryValue(winreg.HKEY_CURRENT_USER, f"{CLASSES}\\{PROG_ID}\\shell\\open\\command")
        icon = winreg.QueryValue(winreg.HKEY_CURRENT_USER, f"{CLASSES}\\{PROG_ID}\\DefaultIcon")
    except OSError:
        return "none"
    if command != open_command():
        return "moved"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTERED_APPS) as key:
            winreg.QueryValueEx(key, OLD_APP_NAME)
        old_name = True
    except OSError:
        old_name = False
    return "outdated" if icon != _icon_value() or old_name else "ok"


def install():
    if not FROZEN and not ICON_PATH.exists():
        make_icon()
    icon = _icon_value()

    prog = f"{CLASSES}\\{PROG_ID}"
    name = APP_NAME  # что видно в «Открыть с помощью»
    kind = tr("Видео ({app})", app=name)
    description = tr("Видеоплеер с обрезкой видео")
    _set(prog, {"": kind, "FriendlyTypeName": kind})
    _set(f"{prog}\\DefaultIcon", {"": icon})
    _set(f"{prog}\\Application", {
        "ApplicationName": name,
        "ApplicationIcon": icon,
        "ApplicationDescription": description,
        "AppUserModelID": APP_USER_MODEL_ID,
    })
    _set(f"{prog}\\shell", {"": "open"})
    _set(f"{prog}\\shell\\open", {"FriendlyAppName": name, "Icon": icon})
    _set(f"{prog}\\shell\\open\\command", {"": open_command()})

    _set(APP_KEY, {"": name})
    _set(CAPABILITIES, {
        "ApplicationName": name,
        "ApplicationDescription": description,
        "ApplicationIcon": icon,
    })
    associations = {f".{ext}": PROG_ID for ext in VIDEO_EXTENSIONS}
    _set(f"{CAPABILITIES}\\FileAssociations", associations)
    _delete_value(REGISTERED_APPS, OLD_APP_NAME)  # иначе в «Приложениях по умолчанию» осталась бы вторая запись
    _set(REGISTERED_APPS, {APP_NAME: CAPABILITIES})

    for ext in VIDEO_EXTENSIONS:
        _set(f"{CLASSES}\\.{ext}\\OpenWithProgids", {PROG_ID: ""})
    _notify_explorer()


def uninstall():
    for ext in VIDEO_EXTENSIONS:
        _delete_value(f"{CLASSES}\\.{ext}\\OpenWithProgids", PROG_ID)
        _delete_if_empty(f"{CLASSES}\\.{ext}\\OpenWithProgids")
        _delete_if_empty(f"{CLASSES}\\.{ext}")
    _delete_value(REGISTERED_APPS, APP_NAME)
    _delete_value(REGISTERED_APPS, OLD_APP_NAME)
    _delete_tree(APP_KEY)
    _delete_tree(f"{CLASSES}\\{PROG_ID}")
    _notify_explorer()


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "install":
        install()
        print(tr("Готово: «{app}» добавлен в «Открыть с помощью» для видео.", app=APP_NAME))
        print(tr("Команда открытия: {command}", command=open_command()))
        print()
        print(tr("Чтобы видео открывались в нём двойным щелчком: правой кнопкой по видео →"))
        print(tr("«Открыть с помощью» → «Выбрать другое приложение» → «{app}» → «Всегда».", app=APP_NAME))
        print(tr("Это нужно сделать по одному разу для каждого формата (mp4, mkv, …)."))
        return 0
    if command == "uninstall":
        uninstall()
        print(tr("Готово: регистрация «{app}» в Windows удалена.", app=APP_NAME))
        print(tr("Если плеер был выбран по умолчанию, Windows при следующем открытии видео спросит, чем его открыть."))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

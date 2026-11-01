"""Где что лежит — в исходниках (python main.py) и в собранной версии (Snip Player.exe).

В сборке (PyInstaller, одна папка) рядом с exe лежит папка _internal: в ней темы, libmpv и FFmpeg.
"""

import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
APP_NAME = "Snip Player"  # имя программы на всех языках: заголовок окна, папки, «Открыть с помощью»
_OLD_APP_NAME = "Проигрыватель"  # так программа называлась до 01.11.2026

# Папка программы: где лежит exe (или main.py).
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
# Файлы программы (темы, lib): в сборке — _internal, в исходниках — сама папка проекта.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
THEMES_DIR = RESOURCE_DIR / "themes"
LIB_DIR = RESOURCE_DIR / "lib"
FFMPEG_DIR = RESOURCE_DIR / "ffmpeg"


def _writable(folder: Path) -> bool:
    probe = folder / f".write_test_{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_dir() -> Path:
    """Куда писать settings.ini и error.log: рядом с программой («переносная» папка), а если туда
    писать нельзя (например, Program Files) — в %APPDATA%\\Snip Player."""
    if not FROZEN or _writable(APP_DIR):
        return APP_DIR
    appdata = Path(os.environ.get("APPDATA") or Path.home())
    folder, old = appdata / APP_NAME, appdata / _OLD_APP_NAME
    if old.is_dir() and not folder.exists():
        try:
            old.rename(folder)  # настройки из прежней папки «Проигрыватель» не теряются
        except OSError:
            return old
    folder.mkdir(parents=True, exist_ok=True)
    return folder


DATA_DIR = _data_dir()


def tool(name: str) -> str | None:
    """Полный путь к ffmpeg / ffprobe: сначала свой (в папке программы), потом из PATH."""
    own = FFMPEG_DIR / f"{name}.exe"
    if own.is_file():
        return str(own)
    return shutil.which(name)

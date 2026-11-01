"""Собрать плеер в одну папку «скачал — запустил» (без установки Python и FFmpeg).

    python сборка\\build.py [--ffmpeg ПАПКА] [--7z] [--zip]

Нужен PyInstaller (лучше в отдельном окружении: python -m venv --system-site-packages …).
--ffmpeg — папка, где лежат ffmpeg.exe и ffprobe.exe; по умолчанию — сборка\\ffmpeg\\ (FFmpeg essentials
9.0.2 с gyan.dev, sha256 архива сверен), а если её нет — те, что находятся через PATH.
Итог: «D:\\claude anim\\ПРОИГРЫВАТЕЛЬ — для скачивания\\Snip Player\\», рядом — архивы для скачивания:
--7z — Snip Player.7z (7-Zip, вдвое меньше zip: ~80 МБ против ~145; Windows 11 открывает .7z сама),
--zip — Snip Player.zip (для Windows 10 без 7-Zip). Старые архивы удаляются в начале сборки.
"""

import argparse
import importlib.metadata
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_ROOT = ROOT.parent / f"{ROOT.name} — для скачивания"
NAME = "Snip Player"  # папка сборки, архивы, exe и spec


def find_ffmpeg(folder: str | None) -> Path:
    if folder:
        base = Path(folder)
    elif (HERE / "ffmpeg" / "ffmpeg.exe").is_file():  # облегчённая сборка gyan «essentials» — в 2 раза меньше full
        base = HERE / "ffmpeg"
    else:
        found = shutil.which("ffmpeg")
        if not found:
            sys.exit("FFmpeg не найден в PATH — укажите папку: --ffmpeg ПАПКА")
        base = Path(found).resolve().parent  # winget кладёт в PATH ярлык — идём к настоящему файлу
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        if not (base / name).is_file():
            sys.exit(f"Нет {base / name}")
    return base


def ffmpeg_version(base: Path) -> str:
    first = subprocess.run([str(base / "ffmpeg.exe"), "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    return first.split()[2] if first.startswith("ffmpeg version") else "?"


def find_7zip() -> Path:
    found = shutil.which("7z") or shutil.which("7za")
    for candidate in (found, r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    sys.exit("7-Zip не найден — установите его (winget install 7zip.7zip) или соберите только --zip")


def make_7z(folder: Path, archive: Path):
    """Архив .7z с папкой folder внутри: LZMA2, максимальное сжатие, «сплошной» (одинаковое в ffmpeg.exe и
    ffprobe.exe сжимается один раз — поэтому .7z вдвое меньше .zip)."""
    archive.unlink(missing_ok=True)
    subprocess.run([str(find_7zip()), "a", "-t7z", "-mx=9", "-mmt=on", "-bso0", "-bsp0", str(archive), str(folder)],
                   check=True)


def text_for_windows(src: Path, dst: Path, **values):
    """Текст для Блокнота: переводы строк Windows и UTF-8 с BOM."""
    text = src.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    dst.write_text(text.replace("\r\n", "\n").replace("\n", "\r\n"), encoding="utf-8-sig", newline="")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg")
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--7z", dest="seven_zip", action="store_true")
    args = parser.parse_args()
    ffmpeg_dir = find_ffmpeg(args.ffmpeg)
    if args.seven_zip:
        find_7zip()  # нет 7-Zip — сказать сразу, а не после долгой сборки

    OUT_ROOT.mkdir(exist_ok=True)
    dist = OUT_ROOT / NAME
    if dist.exists():
        shutil.rmtree(dist)
    for old in (OUT_ROOT / f"{NAME}.zip", OUT_ROOT / f"{NAME}.7z"):
        old.unlink(missing_ok=True)  # архив прежней сборки не должен остаться рядом с новой папкой
    with tempfile.TemporaryDirectory() as work:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
                        "--distpath", str(OUT_ROOT), "--workpath", work, str(HERE / f"{NAME}.spec")], check=True)

    internal = dist / "_internal"
    (internal / "ffmpeg").mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(ffmpeg_dir / name, internal / "ffmpeg" / name)

    licenses = dist / "Лицензии"
    licenses.mkdir()
    for src in [*(ROOT / "licenses").glob("*.txt"), *(HERE / "лицензии").glob("*.txt")]:
        text_for_windows(src, licenses / src.name,
                         ffmpeg_version=ffmpeg_version(ffmpeg_dir),
                         mpv_version=importlib.metadata.version("mpv"),
                         qt_version=importlib.metadata.version("PySide6_Essentials"),
                         python_version=platform.python_version())
    for readme in ("Прочитай меня.txt", "Read me.txt"):  # по-русски и по-английски
        text_for_windows(HERE / readme, dist / readme)

    size = sum(f.stat().st_size for f in dist.rglob("*") if f.is_file())
    print(f"Готово: {dist}  ({size / 2**20:.0f} МБ)")

    if args.seven_zip:
        archive = OUT_ROOT / f"{NAME}.7z"
        make_7z(dist, archive)
        print(f"Архив: {archive}  ({archive.stat().st_size / 2**20:.0f} МБ)")
    if args.zip:
        archive = shutil.make_archive(str(OUT_ROOT / NAME), "zip", OUT_ROOT, NAME)
        print(f"Архив: {archive}  ({Path(archive).stat().st_size / 2**20:.0f} МБ)")


if __name__ == "__main__":
    main()
